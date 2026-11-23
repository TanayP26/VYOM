from fastapi.testclient import TestClient
from app.main import app

def test_health_contract_survives_missing_local_dataset():
    with TestClient(app) as client:
        r=client.get('/api/system/health')
        assert r.status_code==200
        body=r.json()
        assert body['status'] in {'ok','degraded'}
        assert body['command_capability'] is False
        assert 'dataset' in body['checks'] and 'telemetry_store' in body['checks']
