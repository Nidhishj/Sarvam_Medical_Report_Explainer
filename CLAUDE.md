# Medical Report Explainer (Sarvam Hackathon)

A simple web dashboard where anyone uploads a medical report (PDF, photo, or pasted text) and gets it
explained **in their own language**, in plain words a non-medical person understands. They can listen to
the explanation and ask follow-up questions by voice. Built on Sarvam AI APIs. Time budget: ~2 hours.

## Target user
Patients and family members with no medical background, often more comfortable in an Indian language than
English, sometimes with limited literacy. Everything (UI copy, explanations, audio) must be simple,
friendly, and short. Avoid jargon; when a medical term is unavoidable, explain it in one line.

## Tech stack (decided)
| Layer | Choice | Why |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** | Fast to write; runs on Vercel's Python runtime |
| Sarvam access | **`sarvamai` SDK** (v0.1.37) | Official SDK, covers every API below |
| Frontend | **Single static `public/index.html`** + vanilla JS + plain CSS | No build step, no Node needed, deploys anywhere |
| PDF text | **`pypdf`** | Instant for digital PDFs; skip OCR when text exists |
| Hosting | **Vercel** (stretch goal) | `api/index.py` serverless + `public/` static |
| Extra | **MCP server** (`mcp_server.py`, stretch goal) | Exposes the explainer as tools for Claude/Kivi-style agents |

No database, no login. Reports are never stored; everything lives in the request and in browser memory.

## Sarvam APIs used (verified against installed SDK)
```python
from sarvamai import SarvamAI
client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
```
- **Read report (scans/photos):** `client.doc_ai.digitise(file=[...], language="en-IN", content_type="printed")`
  → async job: poll `client.doc_ai.get_status(job_id)` until `completed | partially_completed | failed | rejected`,
  then `client.doc_ai.get_results(job_id, format="md")`. Use only when `pypdf` finds little or no text.
- **Explain / answer (LLM):** `client.chat.completions_v2(messages=[...], model=..., temperature=0.2)`
  → `resp.choices[0].message.content` (some models also return `reasoning_content`; ignore it in the UI).
  Models: `sarvam-105b` (default, best for Indic), `glm5.3`, `gemma4`, `deepseekv4.1-flash`.
  Live list: `client.chat_completion.list_models_v2().data` (each has `.id`). Show the model used on every answer.
- **Listen (TTS):** `client.text_to_speech.convert(text=..., language_code="hi-IN", model="bulbul:v3")`
  → `resp.audios` = list of base64 WAV strings. Chunk text to ~1000 chars at sentence boundaries; play in order.
- **Voice question (STT):** `client.speech_to_text.transcribe(file=..., model="saaras:v3", mode="transcribe", language_code="unknown")`
  → `.transcript`, `.language_code` (auto-detected). REST limit ≈ 30 s audio; cap recording at 30 s.
- **Translate (fallback):** `client.text.translate(...)`, used only if a chosen model answers poorly in Indic languages.

Supported output languages (TTS): `hi-IN bn-IN ta-IN te-IN kn-IN ml-IN mr-IN gu-IN pa-IN od-IN en-IN`.

## Core flows
1. **Submit report:** upload PDF/JPG/PNG or paste text, or click "Try sample report" (needed for demos).
   Then `POST /api/extract` returns `{text, source: "pdf-text" | "sarvam-vision" | "pasted"}`.
2. **Explain:** `POST /api/explain {report_text, language, model}`. The LLM returns JSON:
   ```json
   {"summary": "...", "overall": "normal|attention|urgent",
    "findings": [{"test": "", "value": "", "normal_range": "", "status": "normal|high|low|unclear", "meaning": ""}],
    "questions_for_doctor": ["..."], "lifestyle_tips": ["..."]}
   ```
   Parse it carefully: strip ```json fences, take the first `{...}` block, and fall back to showing the raw text.
3. **Listen:** `POST /api/tts {text, language}` returns `{audios: [base64...]}`.
4. **Ask by voice/text:** `POST /api/ask` (multipart: optional audio, question, report_text, history, language, model)
   returns `{transcript, detected_language, answer, audio, model, timings_ms}`.
5. **Models:** `GET /api/models` returns the live list, falling back to the static list above if the call fails.

## Dashboard layout
- **Top bar:** app name, **language picker** (native script labels, e.g. हिन्दी, தமிழ்), **model picker**.
- **Left:** upload, paste, or sample, then the extracted text (collapsible).
- **Main:** summary card with a traffic-light badge (green normal / amber attention / red urgent),
  a findings table with coloured status chips, "Questions to ask your doctor", and a 🔊 Listen button.
- **Right/bottom:** chat panel with a big 🎤 mic button, chat bubbles, and an auto-played audio answer.
- Every answer shows a small "answered by `<model>` · `<ms>`" tag.
- A permanent disclaimer is always visible.
- Mobile-friendly (single column under 768px). Large fonts and buttons.

## Medical safety rules (put these in the system prompt; never remove them)
- Explain, don't diagnose or prescribe. Never suggest starting, stopping, or changing a medicine or dose.
- Always compare values against the reference range printed on the report. If none is printed, say so.
- If a value is critically abnormal or the text mentions emergency signs, set `overall: "urgent"` and say
  "Please contact a doctor today" plainly at the top.
- Don't invent values that are not in the report. If unsure, say "unclear, ask your doctor".
- Use a warm, calm tone; no fear-inducing words. Short sentences (aim for 6th-grade reading level).
- Reply entirely in the user's chosen language (keep test names like "HbA1c" in English in brackets).
- UI disclaimer: "This is for understanding only, not medical advice. Always consult your doctor."

## Project structure
```
api/index.py          FastAPI app: /api/config, extract, explain, ask, test-provider (Vercel entrypoint)
core/sarvam.py        Sarvam client, live model list, extract_text (pypdf → Sarvam Vision fallback)
core/llm.py           Provider routing: sarvam | OpenAI-compatible | anthropic (bring-your-own-key)
core/explainer.py     explain() + ask() with medical-only guardrails; shared by web API and MCP
core/prompts.py       System prompts, OFF_TOPIC tag, languages, sample report
public/index.html     Entire frontend (HTML + CSS + JS in one file)
mcp_server.py         MCP stdio server (mcp SDK v2: MCPServer, raise ToolError for user-facing errors)
requirements.txt      fastapi, uvicorn, python-multipart, sarvamai, pypdf, python-dotenv, httpx, mcp>=2,<3
vercel.json           rewrite /api/(.*) → /api/index
.env                  SARVAM_API_KEY=... (SARVAM_API also accepted); optional LLM_* for MCP (never commit)
README.md             User/judge-facing docs: how it works, BYOK, guardrails, MCP setup, deploy
```
`api/index.py` must add the project root to `sys.path` so `core` imports work on Vercel.
Locally, FastAPI also serves `public/` at `/`, so one command runs everything.

### Bring your own key & medical-only scope (implemented)
- The browser sends `provider: {provider, api_key, model, base_url}` with explain/ask; `null` = Sarvam + server key.
  Keys are per-request only: never log, store, or echo them. Custom base URLs must be public https (SSRF check in `llm.check_public_https`).
- Medical-only: `ASK_SYSTEM` makes the model reply `[OFF_TOPIC] …` for non-health questions → backend sets
  `off_topic: true`; off-topic turns are not added to chat history. `EXPLAIN_SYSTEM` returns `{"not_medical": true}`
  for non-medical documents. Guardrails live in `core/explainer.py` + prompts, so they apply to every provider and to MCP.
- Sarvam chat model ids come live from `chat_completion.list_models_v2()` (ids without ":"); currently
  `sarvam-105b, glm5.3-flash, glm5.3, gemma4, deepseekv4.1-flash`.

## Commands (Windows / PowerShell)
```powershell
# plain `python` on this machine is 3.6, so ALWAYS use the venv (Python 3.12)
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn api.index:app --reload --port 8000   # open http://localhost:8000
python mcp_server.py                          # MCP over stdio (launched by an MCP client)
```
Deploy (stretch): push to GitHub, import the repo in Vercel, set the `SARVAM_API_KEY` env var, deploy.

## Build order (2-hour plan, MVP first)
1. Backend skeleton + `/api/models` + paste-text → `/api/explain` working with `sarvam-105b`.
2. Dashboard: language/model pickers, summary card, findings table, sample report button.
3. File upload: `pypdf` first, Sarvam Vision (doc_ai) fallback for scans/photos.
4. 🔊 Listen (TTS) for the summary.
5. 🎤 Voice follow-up questions (STT, then LLM, then TTS).
6. Stretch: Vercel deploy, then a "compare two models" view.

Done so far: steps 1–3, bring-your-own-key providers, "Have a doubt?" chat (medical-only), MCP server, README.

Each step should leave the app demo-able. Don't start the next step until the current one works end to end.

## Conventions & gotchas
- Keep it simple: no frameworks, no build tools, no extra abstractions. Hackathon code; readable over clever.
- Never log or persist report contents. Never commit `.env`.
- Return friendly error messages to the UI (e.g. "Couldn't read this file, try a clearer photo").
- Vercel request body limit is 4.5 MB: reject larger uploads client-side with a clear message.
- Browser recording: `MediaRecorder` gives webm/opus, which STT accepts (`webm`/`opus`); send it as-is.
- Doc AI jobs can take tens of seconds: show a progress state and time out at ~60 s.
- Test with the built-in sample report before every demo.
