"""Thin wrappers around the Sarvam AI SDK."""

import html
import io
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from pypdf import PdfReader
from sarvamai import SarvamAI

# explicit path so it also works when an MCP client launches us from another folder
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_MODEL = "sarvam-105b"
FALLBACK_MODELS = ["sarvam-105b", "glm5.3", "gemma4", "deepseekv4.1-flash"]
MIN_PDF_TEXT = 80  # fewer chars than this means a scanned PDF -> use Sarvam Vision
DOC_AI_TIMEOUT_S = 60

# Voice: Bulbul (text-to-speech) and Saaras (speech-to-text)
TTS_MODEL = "bulbul:v3"
TTS_MAX_CHARS = 2500  # bulbul:v3 limit per request
TTS_VOICES = ["shubh", "ritu", "priya", "simran", "kavya", "aditya", "rahul", "anand"]  # bulbul:v3 speakers
DEFAULT_VOICE = os.getenv("SARVAM_TTS_VOICE", "ritu")
STT_MODEL = "saaras:v3"

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


def speak(text: str, language: str, voice: str | None = None) -> list[str]:
    """Text -> speech with Bulbul. Returns base64 WAV clips to play in order."""
    voice = voice if voice in TTS_VOICES else DEFAULT_VOICE
    resp = client().text_to_speech.convert(
        text=text[:TTS_MAX_CHARS], language_code=language, model=TTS_MODEL, speaker=voice, pace=0.95)
    return resp.audios


def transcribe(filename: str, data: bytes, content_type: str) -> dict:
    """Speech -> text with Saaras; the spoken language is auto-detected."""
    resp = client().speech_to_text.transcribe(
        file=(filename, data, content_type), model=STT_MODEL, mode="transcribe", language_code="unknown")
    return {"transcript": (resp.transcript or "").strip(), "language": resp.language_code}


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
    # "md" is refused for jobs that produce html, and "html" comes back as a zip, so use json:
    # documents[].pages[].blocks[] with {text, reading_order}; tables arrive as <table> html inside text
    results = c.doc_ai.get_results(job.job_id, format="json").model_dump()
    parts = []
    for doc in results.get("documents") or []:
        for page in doc.get("pages") or []:
            blocks = sorted(page.get("blocks") or [], key=lambda b: b.get("reading_order") or 0)
            parts += [b.get("text") or "" for b in blocks] or [page.get("content") or ""]
    text = "\n\n".join(_html_to_text(p) for p in parts if p.strip()).strip()
    if not text:
        raise RuntimeError("No text found in this file. Try a clearer photo or a PDF.")
    return text


def _html_to_text(s: str) -> str:
    """Flatten Sarvam Vision block html (tables, line breaks) into plain lines: 'cell | cell | cell'."""
    s = re.sub(r"</t[dh]>\s*", " | ", s, flags=re.I)
    s = re.sub(r"</tr>|<br\s*/?>|</p>|</li>|</h\d>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    lines = (line.strip(" |") for line in s.splitlines())
    return "\n".join(line for line in lines if line)


