"""Каркас сервиса: раздаёт интерфейс и реализует API из ТЗ (раздел 10).
Запуск:  pip install fastapi uvicorn python-multipart
         API_KEY=мой-ключ uvicorn main:app --host 0.0.0.0 --port 8000
"""
import os, json, uuid, tempfile, shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Header, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles

API_KEY = os.getenv("API_KEY", "change-me")
app = FastAPI(title="Кассовый контроль")
JOBS: dict[str, dict] = {}

# Справочник правил: единый источник и для сервера, и для интерфейса (static/rules.json)
_catalog = json.loads((Path(__file__).parent / "static" / "rules.json").read_text(encoding="utf-8"))
RULE_SOURCE = _catalog["source"]
RULES = {r["id"]: r for r in _catalog["rules"]}


def enrich(violation: dict) -> dict:
    """По rule_id подставляет тип нарушения и строку «документ, пункт»."""
    rule = RULES.get(violation.get("rule_id"))
    if rule:
        violation.setdefault("type", rule["title"])
        violation["rule"] = f'{RULE_SOURCE}, {rule["point"]}'
    return violation


def check_key(key: str | None):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Неверный API-ключ")


def analyze_video(path: str) -> dict:
    """СЮДА ПОДКЛЮЧАЕТСЯ ВАША МОДЕЛЬ (локально, без облачных API).
    Верните dict: {"verdict": "violation"|"no_violation", "violations": [
      {"rule_id": "<id из static/rules.json>", "timecode_sec": float, "description": str,
       "evidence_frames": [{"timestamp_sec": float, "image_base64": "<jpeg base64>"}]}]}
    Поля "type" и "rule" (документ, пункт) сервер подставит сам по rule_id."""
    return {"verdict": "no_violation", "violations": []}


def run_job(job_id: str, path: str):
    try:
        result = analyze_video(path)
        result["violations"] = [enrich(v) for v in result.get("violations", [])]
        JOBS[job_id].update(status="done", **result)
    except Exception as e:
        JOBS[job_id].update(status="failed", error=str(e))
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


@app.post("/api/v1/analyze")
async def analyze(bg: BackgroundTasks, file: UploadFile = File(...), x_api_key: str | None = Header(None)):
    check_key(x_api_key)
    if not (file.filename or "").lower().endswith(".mov"):
        raise HTTPException(status_code=400, detail="Нужен файл .mov")
    d = tempfile.mkdtemp()
    path = os.path.join(d, "video.mov")
    with open(path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    job_id = uuid.uuid4().hex[:8]
    JOBS[job_id] = {"job_id": job_id, "status": "processing"}
    bg.add_task(run_job, job_id, path)
    return {"job_id": job_id}


@app.get("/api/v1/jobs/{job_id}")
def job(job_id: str, x_api_key: str | None = Header(None)):
    check_key(x_api_key)
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return JOBS[job_id]


app.mount("/", StaticFiles(directory="static", html=True), name="ui")
