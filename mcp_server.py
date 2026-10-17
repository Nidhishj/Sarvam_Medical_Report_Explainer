"""MCP server (stdio): exposes the medical report explainer as tools for AI agents.

Scope is health/medical only: non-medical questions come back with off_topic=true and a polite refusal,
and non-medical documents come back with not_medical=true.

Run:   .venv\\Scripts\\python.exe mcp_server.py
Uses Sarvam (SARVAM_API_KEY) by default. To use another provider set, in .env:
  LLM_PROVIDER=openai|anthropic|gemini|openrouter|custom, LLM_API_KEY=..., LLM_MODEL=..., LLM_BASE_URL=...
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402  (message is shown to the agent)

from core import explainer, sarvam  # noqa: E402  (importing sarvam loads .env)
from core.prompts import LANGUAGES  # noqa: E402

ALLOWED_EXTENSIONS = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".png": "image/png", ".webp": "image/webp"}

server = MCPServer(
    name="samjho-medical",
    title="Samjho: Medical Report Explainer",
    instructions=(
        "Explains medical reports and answers health/medical doubts in simple words, in 11 Indian languages. "
        "Only use these tools for health and medical topics; other topics are refused. "
        "Explanations are for understanding only, not medical advice."
    ),
)


def _provider() -> dict | None:
    pid = os.getenv("LLM_PROVIDER", "sarvam").strip().lower()
    if pid == "sarvam":
        return None
    return {"provider": pid, "api_key": os.getenv("LLM_API_KEY", ""), "model": os.getenv("LLM_MODEL", ""),
            "base_url": os.getenv("LLM_BASE_URL", "")}


def _check_language(language: str) -> None:
    if language not in LANGUAGES:
        raise ToolError(f"Unsupported language '{language}'. Use one of: {', '.join(LANGUAGES)}")


def _tool_error(e: Exception) -> ToolError:
    if isinstance(e, ToolError):
        return e
    status = getattr(e, "status_code", None)
    if status in (401, 403):
        return ToolError("Sarvam rejected the API key. Check SARVAM_API_KEY in .env.")
    if status == 429:
        return ToolError("Rate limited by the AI provider. Try again in a few seconds.")
    return ToolError(str(e)[:300])


@server.tool()
def explain_medical_report(report_text: str, language: str = "en-IN") -> dict:
    """Explain a medical/lab report in simple words for a non-medical person.

    Returns a summary, overall status (normal / attention / urgent), each test with value, normal range,
    status and meaning, questions to ask the doctor, and safe everyday tips. If the text is not a medical
    report, returns not_medical=true. language is a code like hi-IN, ta-IN, en-IN (see list_languages).
    """
    _check_language(language)
    try:
        out = explainer.explain(report_text, language, _provider())
    except Exception as e:
        raise _tool_error(e) from e
    if out["result"]:
        out.pop("raw", None)  # parsed fine; the raw reply is just noise for the agent
    return out


@server.tool()
def ask_medical_question(question: str, language: str = "en-IN", report_text: str = "") -> dict:
    """Answer a health or medical doubt in simple words, optionally using the user's report as context.

    Only health/medical questions are answered. Anything else returns off_topic=true with a polite refusal.
    Never diagnoses or prescribes; urges emergency help for emergency signs.
    """
    _check_language(language)
    try:
        return explainer.ask(question, language, report_text, provider=_provider())
    except Exception as e:
        raise _tool_error(e) from e


@server.tool()
def extract_report_text(file_path: str) -> dict:
    """Read the text from a local medical report file (PDF, JPG, PNG or WEBP, max 4 MB).

    Digital PDFs are read directly; scans and photos use Sarvam Vision OCR.
    """
    path = Path(file_path).expanduser()
    content_type = ALLOWED_EXTENSIONS.get(path.suffix.lower())
    if not content_type:
        raise ToolError("Only PDF, JPG, PNG or WEBP report files are supported.")
    if not path.is_file():
        raise ToolError(f"File not found: {path}")
    data = path.read_bytes()
    if len(data) > 4 * 1024 * 1024:
        raise ToolError("File is bigger than 4 MB.")
    try:
        text, source = sarvam.extract_text(path.name, data, content_type)
    except Exception as e:
        raise _tool_error(e) from e
    return {"text": text, "source": source}


@server.tool()
def list_languages() -> list[dict]:
    """List the supported explanation languages (code, English name, native name)."""
    return [{"code": c, "name": n, "native": nat} for c, (n, nat) in LANGUAGES.items()]


if __name__ == "__main__":
    server.run()  # stdio
