"""Separate Railway entrypoint. Native app and scientific engine are unchanged."""
import base64
import binascii
import hmac
import os
import json
import shutil
from pathlib import Path
from collections import defaultdict, deque
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

ROOT = Path("/vyom-data")
MODE = os.getenv("VYOM_CLOUD_MODE", "import")
USERNAME = os.getenv("VYOM_CLOUD_USER", "")
PASSWORD = os.getenv("VYOM_CLOUD_PASSWORD", "")
DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
LIMITS = {"/api/chat": (10, 60), "/api/research/search": (6, 60),
          "/api/analysis/runs": (1, 60)}
MAX_BODY = 128_000
if MODE not in {"import", "serve"}:
    raise RuntimeError("Invalid cloud mode")

def credentials_ok(header, username, password):
    if not username or len(password) < 24 or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:], validate=True)
        name, secret = raw.split(b":", 1)
    except (ValueError, binascii.Error):
        return False
    return (hmac.compare_digest(name, username.encode("utf-8"))
            & hmac.compare_digest(secret, password.encode("utf-8")))

def same_origin(origin, domain):
    if not origin or not domain:
        return False
    try:
        parsed = urlsplit(origin)
        return parsed.scheme == "https" and parsed.netloc.lower() == domain.lower() and not parsed.path and not parsed.query and not parsed.fragment
    except ValueError:
        return False

class Gate:
    """Fail closed. Single worker, global endpoint throttles, bounded JSON requests."""
    def __init__(self, app):
        self.app = app
        self.calls = defaultdict(deque)
        self.lock = Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path, method = scope["path"], scope["method"]
        async def deny(code, detail, headers=None):
            await JSONResponse({"detail": detail}, status_code=code,
                               headers=headers or {})(scope, receive, send)
        if path == "/cloud_health" and method in {"GET", "HEAD"}:
            await JSONResponse({"status": "ok"})(scope, receive, send)
            return
        if MODE != "serve":
            return await deny(503, "Cloud migration in progress")
        if not credentials_ok(request.headers.get("authorization", ""), USERNAME, PASSWORD):
            return await deny(401, "Authentication required",
                              {"WWW-Authenticate": 'Basic realm="VYOM research workspace", charset="UTF-8"',
                               "Cache-Control": "no-store"})
        if path.rstrip("/") == "/api/knowledge/ingest":
            return await deny(403, "Remote knowledge ingestion disabled")
        if method not in {"GET", "HEAD", "POST"}:
            return await deny(405, "Method not allowed")
        if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"} and (method == "POST" or path.rstrip("/") == "/api/research/search"):
            return await deny(403, "Cross-origin operation blocked")
        if method == "POST":
            if not same_origin(request.headers.get("origin", ""), DOMAIN):
                return await deny(403, "Same-origin HTTPS request required")
        rate_key = path.rstrip("/")
        if rate_key in LIMITS and (rate_key != "/api/analysis/runs" or method == "POST"):
            count, seconds = LIMITS[rate_key]
            now = monotonic()
            with self.lock:
                q = self.calls[rate_key]
                while q and q[0] <= now - seconds:
                    q.popleft()
                blocked = len(q) >= count
                if not blocked:
                    q.append(now)
            if blocked:
                return await deny(429, "Request limit reached; try again later",
                                  {"Retry-After": str(seconds)})
        if method == "POST":
            body = bytearray()
            while True:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    return
                body.extend(msg.get("body", b""))
                if len(body) > MAX_BODY:
                    return await deny(413, "Request too large")
                if not msg.get("more_body", False):
                    break
            if rate_key == "/api/analysis/runs":
                try:
                    payload = json.loads(body)
                    if not isinstance(payload, dict):
                        raise ValueError("Expected object")
                    channels = payload.get("channels") or ["channel_12", "channel_41", "channel_61"]
                    if not isinstance(channels, list) or any(not isinstance(x, str) for x in channels) or len(channels) > 76 or len(set(channels)) != len(channels):
                        raise ValueError("Invalid or duplicate channel selection")
                    batch = payload.get("batch_rows", 5000)
                    if type(batch) is not int or not 500 <= batch <= 5000:
                        raise ValueError("Cloud batch size must be between 500 and 5000")
                    required = (76 if payload.get("full_mission") else len(channels)) * 2 * 1024**3 + 2 * 1024**3
                except (ValueError, TypeError, UnicodeError) as exc:
                    return await deny(422, str(exc))
                if shutil.disk_usage(ROOT).free < required:
                    return await deny(409, "Insufficient cloud storage headroom for requested analysis; increase persistent volume capacity")
            delivered = False
            original_receive = receive
            async def replay():
                nonlocal delivered
                if delivered:
                    return await original_receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            receive = replay
        async def secured_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                headers = list(message.get("headers", []))
                headers.extend([(b"x-content-type-options", b"nosniff"),
                                (b"x-frame-options", b"DENY"),
                                (b"referrer-policy", b"no-referrer"),
                                (b"cache-control", b"no-store")])
                message["headers"] = headers
            await send(message)
        await self.app(scope, receive, secured_send)

if MODE == "serve":
    if not USERNAME or ":" in USERNAME or len(PASSWORD) < 24:
        raise RuntimeError("Set VYOM_CLOUD_USER and a strong VYOM_CLOUD_PASSWORD")
    if not (ROOT / "migration_verified.json").is_file():
        raise RuntimeError("Verify uploaded evidence before enabling serve mode")
    marker = json.loads((ROOT / "migration_verified.json").read_text(encoding="utf-8"))
    if marker.get("status") != "verified" or marker.get("channels") != 76 or marker.get("observations") != 744856895:
        raise RuntimeError("Cloud migration verification marker is invalid")
    from app.main import app as inner
    inner.mount("/", StaticFiles(directory="/app/static", html=True), name="frontend")
else:
    # Import mode intentionally does not open or create the destination SQLite DB.
    inner = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

app = Gate(inner)
