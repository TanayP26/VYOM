import base64
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cloud import entry
from fastapi import FastAPI
from fastapi.testclient import TestClient

def client(monkeypatch, mode="serve"):
    monkeypatch.setattr(entry, "MODE", mode)
    monkeypatch.setattr(entry, "USERNAME", "researcher")
    monkeypatch.setattr(entry, "PASSWORD", "x"*32)
    monkeypatch.setattr(entry, "DOMAIN", "vyom.example")
    inner = FastAPI()
    @inner.get("/")
    def home(): return {"ok": True}
    @inner.post("/api/chat")
    def chat(body: dict): return body
    @inner.post("/api/knowledge/ingest")
    def ingest(body: dict): return body
    return TestClient(entry.Gate(inner))

def auth():
    return {"Authorization": "Basic " + base64.b64encode(("researcher:"+"x"*32).encode()).decode()}

def test_import_mode(monkeypatch):
    c=client(monkeypatch,"import")
    assert c.get("/cloud_health").status_code==200
    assert c.get("/",headers=auth()).status_code==503

def test_auth_and_origin(monkeypatch):
    c=client(monkeypatch)
    assert c.get("/").status_code==401
    assert c.get("/",headers=auth()).status_code==200
    assert c.post("/api/chat",json={},headers=auth()).status_code==403
    headers={**auth(),"Origin":"https://vyom.example"}
    assert c.post("/api/chat",json={"question":"hello"},headers=headers).json()=={"question":"hello"}
    assert c.post("/api/knowledge/ingest",json={},headers=headers).status_code==403
    assert c.post("/api/chat",json={},headers={**headers,"Sec-Fetch-Site":"cross-site"}).status_code==403

def test_limits(monkeypatch):
    c=client(monkeypatch)
    headers={**auth(),"Origin":"https://vyom.example"}
    for i in range(10):
        assert c.post("/api/chat",json={},headers=headers).status_code==200
    assert c.post("/api/chat",json={},headers=headers).status_code==429
    c=client(monkeypatch)
    assert c.post("/api/chat",json={"data":"x"*130000},headers=headers).status_code==413
