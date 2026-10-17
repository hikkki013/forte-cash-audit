"""Single-worker local API. Uploads never leave this process/machine."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import copy
import hmac
import os
from pathlib import Path
import threading
import time
import uuid
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal


class Accepted(BaseModel):
    job_id: str


class JobResponse(BaseModel):
    job_id: str
    status: Literal["processing", "done", "failed"]
    result: dict | None = None
    error: str | None = None


def create_app(analyzer=None, api_key=None, upload_dir=None, max_bytes=200*1024*1024):
    secret = api_key if api_key is not None else os.environ.get("FORTE_API_KEY", "")
    root = Path(upload_dir or "runtime/uploads").resolve()
    jobs, guard = {}, threading.Lock()
    slots = threading.BoundedSemaphore(2)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forte-gpu")
    state = {"analyzer":analyzer, "load_error":None}

    @asynccontextmanager
    async def lifespan(app):
        root.mkdir(parents=True, exist_ok=True)
        yield
        pool.shutdown(wait=True, cancel_futures=False)

    app = FastAPI(title="Forte local prototype", version="0.1.0", lifespan=lifespan)
    origins = [x.strip() for x in os.environ.get("FORTE_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if x.strip()]
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=["GET","POST"],allow_headers=["X-API-Key","Content-Type"])

    def auth(x_api_key: str | None = Header(default=None)):
        if not secret:
            raise HTTPException(503,"Set FORTE_API_KEY before starting the server")
        if not x_api_key or not hmac.compare_digest(x_api_key.encode(),secret.encode()):
            raise HTTPException(401,"Invalid API key")

    def cleanup():
        now = time.monotonic()
        expired = [key for key,v in jobs.items() if v["status"]!="processing" and now-v["created"]>3600]
        for key in expired:
            del jobs[key]
        finished = sorted((v["created"],k) for k,v in jobs.items() if v["status"]!="processing")
        for _,key in finished[:-18]:
            del jobs[key]

    def work(job_id, path, deadline):
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError("Queue wait exhausted processing budget")
            if state["analyzer"] is None:
                from forte.vision import Detector
                from forte.pipeline import Pipeline
                state["analyzer"] = Pipeline(Detector(os.environ.get("FORTE_MODEL_DIR","models/grounding-dino-tiny")))
            result = state["analyzer"].analyze(path, deadline=deadline)
            if time.monotonic() > deadline:
                raise TimeoutError("Analysis exceeded processing budget")
            # Per-frame diagnostics are local CLI output, not the frontend payload.
            result = {k:v for k,v in result.items() if k != "observations"}
            with guard:
                jobs[job_id].update(status="done",result=result)
        except TimeoutError:
            with guard:
                jobs[job_id].update(status="failed",error="analysis_timeout")
        except (ValueError, FileNotFoundError) as exc:
            with guard:
                jobs[job_id].update(status="failed",error=str(exc))
        except Exception:
            # Do not leak paths, tokens or internal exceptions over the API.
            with guard:
                jobs[job_id].update(status="failed",error="analysis_failed")
        finally:
            try:
                path.unlink(missing_ok=True)  # Only the UUID upload copy, never originals.
            finally:
                slots.release()

    @app.get("/health")
    def health():
        return {"status":"ok","prototype":True,"api_key_configured":bool(secret),
            "model_files_present":Path(os.environ.get("FORTE_MODEL_DIR","models/grounding-dino-tiny"),"model.safetensors").exists()}

    @app.post("/api/v1/analyze",status_code=202,response_model=Accepted,dependencies=[Depends(auth)])
    async def analyze(file: UploadFile = File(...)):
        if Path(file.filename or "").suffix.lower() not in {".mov",".mp4"}:
            await file.close()
            raise HTTPException(415,"Use MOV or MP4")
        if not slots.acquire(blocking=False):
            await file.close()
            raise HTTPException(429,"Worker busy; retry later")
        job_id = uuid.uuid4().hex
        root.mkdir(parents=True,exist_ok=True)
        path = root/f"{job_id}.video"
        submitted = False
        created = time.monotonic()
        try:
            size = 0
            with path.open("xb") as out:
                while chunk := await file.read(1024*1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(413,"Video exceeds upload limit")
                    if time.monotonic()-created > 60:
                        raise HTTPException(408,"Upload took too long")
                    out.write(chunk)
            if not size:
                raise HTTPException(400,"Empty file")
            with guard:
                cleanup()
                jobs[job_id] = {"job_id":job_id,"status":"processing","created":created,"result":None,"error":None}
            pool.submit(work,job_id,path,created+240)
            submitted = True
            return {"job_id":job_id}
        finally:
            await file.close()
            if not submitted:
                path.unlink(missing_ok=True)
                slots.release()

    @app.get("/api/v1/jobs/{job_id}",response_model=JobResponse,dependencies=[Depends(auth)])
    def get_job(job_id: str):
        with guard:
            cleanup()
            if job_id not in jobs:
                raise HTTPException(404,"Job not found or expired")
            record = copy.deepcopy(jobs[job_id])
        record.pop("created",None)
        return record

    return app


app = create_app()
