import threading
import time
import json
from fastapi.testclient import TestClient
from forte.api import create_app

class FakeAnalyzer:
    def analyze(self,path,deadline=None):
        if path.read_bytes()==b"corrupt":
            raise ValueError(f"Invalid video: {path}")
        return {"verdict":"no_violation","violations":[],"warnings":["TEST ONLY"],"observations":[]}

def poll(c,jid):
    for _ in range(100):
        r=c.get('/api/v1/jobs/'+jid,headers={"X-API-Key":"test"})
        if r.json()["status"]!="processing":
            return r.json()
        time.sleep(.01)
    raise AssertionError("worker did not finish")

def test_auth_and_file_limits(tmp_path):
    with TestClient(create_app(FakeAnalyzer(),"test",tmp_path,max_bytes=8)) as c:
        assert c.post('/api/v1/analyze',files={"file":("x.mov",b"x")}).status_code==401
        for name,data,status in [("x.txt",b"x",415),("x.mov",b"",400),("x.mov",b"012345678",413)]:
            assert c.post('/api/v1/analyze',headers={"X-API-Key":"test"},files={"file":(name,data)}).status_code==status
        assert not list(tmp_path.iterdir())

def test_success_and_failure_cleanup(tmp_path):
    with TestClient(create_app(FakeAnalyzer(),"test",tmp_path)) as c:
        for data,expected in [(b"video","done"),(b"corrupt","failed")]:
            response=c.post('/api/v1/analyze',headers={"X-API-Key":"test"},files={"file":("../../original.mov",data)})
            assert response.status_code==202
            job=poll(c,response.json()["job_id"])
            assert job["status"]==expected
            if expected=="done":
                assert "observations" not in job["result"]
                assert job["verdict"] == job["result"]["verdict"] == "no_violation"
                assert job["violations"] == job["result"]["violations"] == []
            else:
                assert job["result"] is None
                assert job["verdict"] is None and job["violations"] is None
                assert job["error"] == "invalid_video_or_configuration"
                assert str(tmp_path) not in str(job)
        assert c.get('/api/v1/jobs/missing',headers={"X-API-Key":"test"}).status_code==404
    assert not list(tmp_path.iterdir())

def test_missing_server_key_fails_closed(tmp_path):
    with TestClient(create_app(FakeAnalyzer(),"",tmp_path)) as c:
        assert c.post('/api/v1/analyze',files={"file":("x.mov",b"x")}).status_code==503


def test_jury_top_level_contract_with_multiple_events(tmp_path):
    # Contract-only test; model accuracy is evaluated separately on real videos.
    class Multiple:
        def analyze(self, path, deadline=None):
            return {"verdict":"violation", "coverage_status":"partial",
                "violations":[{"type":"Тестовое событие", "timecode_sec":t,
                    "description":"Синтетическое наблюдение для теста контракта",
                    "evidence_frames":[]} for t in [1.0, 5.0]]}
    with TestClient(create_app(Multiple(), "test", tmp_path)) as c:
        accepted=c.post('/api/v1/analyze',headers={"X-API-Key":"test"},files={"file":("x.mov",b"test")})
        job=poll(c,accepted.json()['job_id'])
        assert job['status']=='done' and job['verdict']=='violation'
        assert len(job['violations'])==2
        assert job['violations']==job['result']['violations']
        assert job['result']['coverage_status']=='partial'

def test_bounded_queue(tmp_path):
    gate=threading.Event()
    class Blocking:
        def analyze(self,path,deadline=None):
            gate.wait(3)
            return {"verdict":"no_violation","violations":[]}
    with TestClient(create_app(Blocking(),"test",tmp_path)) as c:
        try:
            codes=[c.post('/api/v1/analyze',headers={"X-API-Key":"test"},files={"file":("x.mov",b"x")}).status_code for _ in range(3)]
            assert codes==[202,202,429]
        finally:
            gate.set()


def test_jury_mode_requires_header_and_writes_minimal_audit(tmp_path, monkeypatch):
    audit = tmp_path / "jury-audit.jsonl"
    monkeypatch.setenv("FORTE_API_KEY_ONLY", "1")
    monkeypatch.setenv("FORTE_AUDIT_LOG", str(audit))
    with TestClient(create_app(FakeAnalyzer(), "test", tmp_path)) as c:
        assert c.post('/api/v1/analyze', files={"file":("private-name.mov",b"video")}).status_code == 401
        accepted = c.post('/api/v1/analyze', headers={"X-API-Key":"test"},
                          files={"file":("private-name.mov",b"video")})
        assert accepted.status_code == 202
        assert poll(c, accepted.json()["job_id"])["status"] == "done"
    rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["accepted", "finished"]
    assert rows[-1]["status"] == "done"
    assert "private-name.mov" not in audit.read_text(encoding="utf-8")
