"""FastAPI app: all /api/* routes. Vercel entrypoint; also serves public/ locally."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from core import explainer, llm, sarvam  # noqa: E402
from core.prompts import LANGUAGES, SAMPLE_REPORT  # noqa: E402

MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # Vercel caps request bodies at 4.5 MB
ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}

app = FastAPI(title="Medical Report Explainer")


def friendly_error(e: Exception, fallback: str) -> HTTPException:
    if isinstance(e, (RuntimeError, TimeoutError)):  # includes llm.ProviderError
        return HTTPException(502, str(e))
    status = getattr(e, "status_code", None)
    if status in (401, 403):
        return HTTPException(502, "Sarvam rejected the API key. Check SARVAM_API_KEY in .env and restart the server.")
    if status == 429:
        return HTTPException(429, "Too many requests to Sarvam right now. Wait a few seconds and try again.")
    return HTTPException(502, f"{fallback} ({type(e).__name__}: {str(e)[:200]})")


class ProviderConfig(BaseModel):
    """Bring-your-own-key settings from the browser. Never logged or stored."""
    provider: str = "sarvam"
    api_key: str = ""
    model: str = ""
    base_url: str = ""


def provider_dict(p: ProviderConfig | None) -> dict | None:
    return p.model_dump() if p and p.provider != "sarvam" else None


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    models, source = sarvam.list_models()
    return {
        "languages": [{"code": c, "name": n, "native": nat} for c, (n, nat) in LANGUAGES.items()],
        "models": models,
        "models_source": source,
        "default_model": sarvam.DEFAULT_MODEL,
        "providers": llm.public_presets(),
        "sample_report": SAMPLE_REPORT,
    }


@app.post("/api/extract")
async def extract(file: UploadFile | None = File(None), text: str = Form("")):
    if file is None:
        if not text.strip():
            raise HTTPException(400, "Please upload a report or paste its text.")
        return {"text": text.strip(), "source": "pasted"}

    content_type = file.content_type or ""
    if content_type not in ALLOWED_TYPES and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF, JPG or PNG file.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is too big. Please keep it under 4 MB.")
    try:
        report_text, source = sarvam.extract_text(file.filename, data, content_type)
    except Exception as e:
        raise friendly_error(e, "Couldn't read this file. Try a clearer photo or a PDF.")
    return {"text": report_text, "source": source}


class ExplainRequest(BaseModel):
    report_text: str
    language: str = "hi-IN"
    model: str = sarvam.DEFAULT_MODEL  # Sarvam model, used when provider is Sarvam
    provider: ProviderConfig | None = None


@app.post("/api/explain")
def explain(req: ExplainRequest):
    if not req.report_text.strip():
        raise HTTPException(400, "The report is empty.")
    try:
        return explainer.explain(req.report_text, req.language, provider_dict(req.provider), req.model)
    except Exception as e:
        raise friendly_error(e, "Couldn't explain the report right now. Please try again.")


class AskRequest(BaseModel):
    question: str
    language: str = "hi-IN"
    report_text: str = ""
    history: list[dict] = []
    model: str = sarvam.DEFAULT_MODEL
    provider: ProviderConfig | None = None


@app.post("/api/ask")
def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(400, "Please type a question.")
    try:
        return explainer.ask(req.question, req.language, req.report_text, req.history,
                             provider_dict(req.provider), req.model)
    except Exception as e:
        raise friendly_error(e, "Couldn't answer right now. Please try again.")


class TestProviderRequest(BaseModel):
    provider: ProviderConfig
    model: str = sarvam.DEFAULT_MODEL


@app.post("/api/test-provider")
def test_provider(req: TestProviderRequest):
    try:
        out = llm.chat([{"role": "user", "content": "Reply with the single word: OK"}],
                       provider_dict(req.provider), req.model, max_tokens=20)
    except Exception as e:
        raise friendly_error(e, "Connection test failed.")
    return {"ok": True, "model": out["model"], "ms": out["ms"]}


public_dir = ROOT / "public"
if public_dir.exists():
    app.mount("/", StaticFiles(directory=public_dir, html=True), name="public")
