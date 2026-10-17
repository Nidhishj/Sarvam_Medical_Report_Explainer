"""Route chat requests to Sarvam (built-in) or a user-supplied provider (bring your own key).

Users' keys are used only for the request in flight; never log or store them.
"""

import ipaddress
import socket
import time
from urllib.parse import urlparse

import httpx

from core import sarvam

# id -> preset. "kind" decides the wire format.
PROVIDERS = {
    "sarvam": {"label": "Sarvam AI (built-in)", "kind": "sarvam", "needs_key": False,
               "default_model": sarvam.DEFAULT_MODEL, "base_url": ""},
    "openai": {"label": "OpenAI", "kind": "openai", "needs_key": True,
               "default_model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
    "anthropic": {"label": "Anthropic Claude", "kind": "anthropic", "needs_key": True,
                  "default_model": "claude-haiku-5-5", "base_url": "https://api.anthropic.com/v1"},
    "gemini": {"label": "Google Gemini", "kind": "openai", "needs_key": True,
               "default_model": "gemini-2.5-flash",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "openrouter": {"label": "OpenRouter", "kind": "openai", "needs_key": True,
                   "default_model": "openai/gpt-4o-mini", "base_url": "https://openrouter.ai/api/v1"},
    "custom": {"label": "Other (OpenAI-compatible)", "kind": "openai", "needs_key": True,
               "default_model": "", "base_url": ""},
}

TIMEOUT_S = 90


class ProviderError(RuntimeError):
    """Error with a message that is safe to show to the user."""


def public_presets() -> list[dict]:
    return [{"id": pid, **{k: v for k, v in p.items() if k != "kind"}} for pid, p in PROVIDERS.items()]


def chat(messages: list[dict], provider: dict | None = None, sarvam_model: str | None = None,
         max_tokens: int = 3000, temperature: float = 0.2) -> dict:
    """Return {"text", "model", "provider", "ms"}. provider=None means Sarvam with the server key."""
    provider = provider or {}
    pid = provider.get("provider") or "sarvam"
    if pid not in PROVIDERS:
        raise ProviderError(f"Unknown AI provider: {pid}")
    preset = PROVIDERS[pid]
    start = time.time()

    if preset["kind"] == "sarvam":
        model = sarvam_model or sarvam.DEFAULT_MODEL
        resp = sarvam.client().chat.completions_v2(
            messages=messages, model=model, temperature=temperature, max_tokens=max_tokens)
        text = resp.choices[0].message.content or ""
    else:
        key = (provider.get("api_key") or "").strip()
        model = (provider.get("model") or preset["default_model"]).strip()
        base = (provider.get("base_url") or preset["base_url"]).strip().rstrip("/")
        if not key:
            raise ProviderError(f"Please add your {preset['label']} API key in AI provider settings.")
        if not model:
            raise ProviderError("Please enter a model name in AI provider settings.")
        if pid == "custom":
            check_public_https(base)
        call = _anthropic if preset["kind"] == "anthropic" else _openai_compatible
        text = call(base, key, model, messages, max_tokens, temperature, preset["label"], pid)

    return {"text": text, "model": model, "provider": pid, "ms": int((time.time() - start) * 1000)}


def _openai_compatible(base, key, model, messages, max_tokens, temperature, label, pid):
    body = {"model": model, "messages": messages, "temperature": temperature}
    # OpenAI's newer models want max_completion_tokens; most compatible APIs still use max_tokens
    body["max_completion_tokens" if pid == "openai" else "max_tokens"] = max_tokens
    data = _post(f"{base}/chat/completions", {"Authorization": f"Bearer {key}"}, body, label, model)
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise ProviderError(f"{label} sent an unexpected reply.")


def _anthropic(base, key, model, messages, max_tokens, temperature, label, pid):
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    convo = [m for m in messages if m["role"] != "system"]
    body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": convo,
            "temperature": temperature}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    data = _post(f"{base}/messages", headers, body, label, model)
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _post(url, headers, body, label, model):
    with httpx.Client(timeout=TIMEOUT_S) as http:
        r = http.post(url, headers=headers, json=body)
        # some models reject a custom temperature: retry once without it
        if r.status_code == 400 and "temperature" in r.text.lower():
            body = {k: v for k, v in body.items() if k != "temperature"}
            r = http.post(url, headers=headers, json=body)
    if r.status_code in (401, 403):
        raise ProviderError(f"{label} rejected the API key. Check it in AI provider settings.")
    if r.status_code == 404:
        raise ProviderError(f"{label} couldn't find the model '{model}'. Check the model name.")
    if r.status_code == 429:
        raise ProviderError(f"{label} rate limit or quota reached. Try again in a bit.")
    if r.status_code >= 400:
        raise ProviderError(f"{label} error {r.status_code}: {_error_text(r)}")
    return r.json()


def _error_text(r: httpx.Response) -> str:
    try:
        err = r.json().get("error", r.json())
        msg = err.get("message") if isinstance(err, dict) else err
        return str(msg)[:200]
    except Exception:
        return r.text[:200]


def check_public_https(url: str) -> None:
    """Block custom base URLs that point at this server's own network (SSRF)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ProviderError("Custom base URL must start with https://")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise ProviderError(f"Couldn't reach {parsed.hostname}. Check the base URL.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ProviderError("Custom base URL must be a public internet address.")
