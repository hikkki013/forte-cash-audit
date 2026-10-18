"""Single-worker local API. Uploads never leave this process/machine."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import copy
import hmac
import json
import os
import secrets
from pathlib import Path
import threading
import time
import uuid
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal
from forte.rule_metadata import rule_metadata


class Accepted(BaseModel):
    job_id: str


class JobResponse(BaseModel):
    job_id: str
    status: Literal["processing", "done", "failed"]
    verdict: Literal["violation", "no_violation"] | None = None
    violations: list[dict] | None = None
    result: dict | None = None
    error: str | None = None


def create_app(analyzer=None, api_key=None, upload_dir=None, max_bytes=200*1024*1024):
    secret = api_key if api_key is not None else os.environ.get("FORTE_API_KEY", "")
    root = Path(upload_dir or "runtime/uploads").resolve()
    jobs, guard = {}, threading.Lock()
    slots = threading.BoundedSemaphore(2)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forte-gpu")
    state = {"analyzer":analyzer, "load_error":None}
    ui_session = secrets.token_urlsafe(32)
    ui_root = Path(__file__).resolve().parent.parent / "frontend"
    variants = {"with-rules":"forte_с_правилами", "simple":"forte_без_правил"}
    assets = {"app.js", "style.css", "rules.json", "images/logo.png", "images/icon.png"}

    @asynccontextmanager
    async def lifespan(app):
        root.mkdir(parents=True, exist_ok=True)
        yield
        pool.shutdown(wait=True, cancel_futures=False)

    app = FastAPI(title="Forte local prototype", version="0.3.0", lifespan=lifespan)
    origins = [x.strip() for x in os.environ.get("FORTE_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if x.strip()]
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=["GET","POST"],allow_headers=["X-API-Key","Content-Type"])

    def local_browser(request: Request):
        # No secret in JS, URL, or public bootstrap response. A foreign website
        # cannot bootstrap/use this cookie with a cross-origin form or fetch.
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if (not request.client or request.client.host not in {"127.0.0.1", "::1"}
                or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}
                or request.headers.get("x-forte-local") != "1"
                or (origin is not None and origin != expected)
                or request.headers.get("sec-fetch-site", "same-origin") not in {"same-origin", "none"}):
            raise HTTPException(403, "Open the UI on this computer at http://127.0.0.1:8000")

    def auth(request: Request, x_api_key: str | None = Header(default=None)):
        # An explicit key also works in Swagger when the browser has a UI cookie.
        if x_api_key is not None:
            if not secret:
                raise HTTPException(503,"Set FORTE_API_KEY before starting the server")
            if not hmac.compare_digest(x_api_key.encode(),secret.encode()):
                raise HTTPException(401,"Invalid API key")
            return
        cookie = request.cookies.get("forte_local_session", "")
        if cookie and hmac.compare_digest(cookie.encode(), ui_session.encode()):
            local_browser(request)
            return
        if not secret:
            raise HTTPException(503,"Set FORTE_API_KEY before starting the server")
        if not x_api_key or not hmac.compare_digest(x_api_key.encode(),secret.encode()):
            raise HTTPException(401,"Invalid API key")

    @app.post("/api/v1/session", dependencies=[Depends(local_browser)])
    def browser_session(response: Response):
        response.set_cookie("forte_local_session",ui_session,httponly=True,samesite="strict",path="/",max_age=28800)
        response.headers["Cache-Control"] = "no-store"
        return {"ready":True}

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/ui/with-rules/")

    @app.get("/ui/{variant}/", include_in_schema=False)
    def ui_page(variant: str):
        if variant not in variants:
            raise HTTPException(404)
        return FileResponse(ui_root/variants[variant]/"index.html",headers={"Cache-Control":"no-store"})

    @app.get("/ui/{variant}/{asset:path}", include_in_schema=False)
    def ui_asset(variant: str, asset: str):
        if variant not in variants or asset not in assets:
            raise HTTPException(404)
        return FileResponse(ui_root/variants[variant]/asset,headers={"Cache-Control":"no-store"})

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
            safe_errors = {
                "Unsupported camera aspect. Configure scene zones for this camera.",
                "No people detected; scene cannot be evaluated",
                "Local model missing. Run python -m scripts.download_model first.",
            }
            # Decoder exceptions may include the private upload path.
            message = str(exc) if str(exc) in safe_errors else "invalid_video_or_configuration"
            with guard:
                jobs[job_id].update(status="failed",error=message)
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

    @app.get("/api/v1/rules")
    def catalog():
        rows = json.loads((ui_root.parent/"config"/"rules.json").read_text(encoding="utf-8"))
        return {"source":"Постановление НБРК № 231: часть пунктов сверена с предоставленным PDF от 17.10.2026; остальные основания требуют проверки. Применимость к событию и актуальность онлайн-редакции не подтверждены.",
            "rules":[{**rule_metadata(r),"id":key,"title":r["title"],"point":r.get("paragraph") or "Без нормативной ссылки",
                "text":r["description"],"visible":"Автоматический поиск кандидатов" if r["mode"]=="automatic_candidate" else "Требуется ручная проверка; детектор не реализован",
                "limits":r["limits"],"mode":r["mode"]} for key,r in rows.items()]}

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
        if record["status"] == "done":
            # Required top-level fields from section 10 of the task. Keep
            # result as a compatibility extension for existing integrations.
            record["verdict"] = record["result"]["verdict"]
            record["violations"] = record["result"]["violations"]
        return record

    return app


app = create_app()
