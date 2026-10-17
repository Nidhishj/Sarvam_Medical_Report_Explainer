"""Thin wrappers around the Sarvam AI SDK."""

import io
import json
import os
import re
import time

from dotenv import load_dotenv
from pypdf import PdfReader
from sarvamai import SarvamAI

from core.prompts import EXPLAIN_SYSTEM, EXPLAIN_USER, LANGUAGES

load_dotenv()

DEFAULT_MODEL = "sarvam-105b"
FALLBACK_MODELS = ["sarvam-105b", "glm5.3", "gemma4", "deepseekv4.1-flash"]
MIN_PDF_TEXT = 80  # fewer chars than this means a scanned PDF -> use Sarvam Vision
DOC_AI_TIMEOUT_S = 60

_client = None


def client() -> SarvamAI:
    global _client
    if _client is None:
        key = (os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_API") or "").strip()
        if not key or key.startswith("paste_your"):
            raise RuntimeError("SARVAM_API_KEY is not set. Add it to the .env file.")
        _client = SarvamAI(api_subscription_key=key)
    return _client


def list_models() -> tuple[list[str], str]:
    """Return (chat model ids, source) where source is 'live' or 'fallback'."""
    try:
        # STT/TTS ids look like "saaras:v3" / "bulbul:v3"; chat ids have no colon
        ids = [m.id for m in client().chat_completion.list_models_v2().data if ":" not in m.id]
        if ids:
            ids.sort(key=lambda i: i != DEFAULT_MODEL)
            return ids, "live"
    except Exception:
        pass
    return FALLBACK_MODELS, "fallback"


def extract_text(filename: str, data: bytes, content_type: str) -> tuple[str, str]:
    """Return (report text, source) for an uploaded PDF or image."""
    is_pdf = content_type == "application/pdf" or filename.lower().endswith(".pdf")
    if is_pdf:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        if len(text) >= MIN_PDF_TEXT:
            return text, "pdf-text"
    return _digitise(filename, data, content_type), "sarvam-vision"


def _digitise(filename: str, data: bytes, content_type: str) -> str:
    """OCR a scanned PDF / photo with Sarvam Vision (doc_ai digitise job)."""
    c = client()
    job = c.doc_ai.digitise(file=[(filename, data, content_type)], language="en-IN", content_type="printed")
    deadline = time.time() + DOC_AI_TIMEOUT_S
    status = job.status
    while status not in ("completed", "partially_completed", "failed", "rejected"):
        if time.time() > deadline:
            raise TimeoutError("Reading the report took too long. Try a clearer or smaller file.")
        time.sleep(2)
        status = c.doc_ai.get_status(job.job_id).status
    if status in ("failed", "rejected"):
        raise RuntimeError("Sarvam Vision could not read this file. Try a clearer photo or a PDF.")
    results = c.doc_ai.get_results(job.job_id, format="md")
    pages = [p.content or "" for doc in (results.documents or []) for p in (doc.pages or [])]
    text = "\n\n".join(pages).strip()
    if not text:
        raise RuntimeError("No text found in this file. Try a clearer photo or a PDF.")
    return text


def explain(report_text: str, language: str, model: str) -> dict:
    name, native = LANGUAGES.get(language, LANGUAGES["en-IN"])
    messages = [
        {"role": "system", "content": EXPLAIN_SYSTEM.format(language_name=name, language_native=native)},
        {"role": "user", "content": EXPLAIN_USER.format(report_text=report_text[:15000])},
    ]
    start = time.time()
    resp = client().chat.completions_v2(messages=messages, model=model or DEFAULT_MODEL, temperature=0.2, max_tokens=4000)
    elapsed_ms = int((time.time() - start) * 1000)
    raw = resp.choices[0].message.content or ""
    return {"result": parse_json(raw), "raw": raw, "model": model or DEFAULT_MODEL, "ms": elapsed_ms}


def parse_json(text: str) -> dict | None:
    """Pull the first JSON object out of an LLM reply (tolerates ```json fences and stray text)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
