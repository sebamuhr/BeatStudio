"""Minimal OpenAI-compatible chat client (stdlib only — no requests dependency).

Talks to whatever server the user points at in AI Settings: Ollama, vLLM, LM Studio and
llama.cpp all expose POST {base_url}/chat/completions. We only need base_url + model, so the
user can swap servers/models freely without touching code.
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error
import urllib.parse


class LLMError(RuntimeError):
    pass


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _no_think_messages(messages: list[dict]) -> list[dict]:
    """Force reasoning models OFF. This app never wants a hidden chain-of-thought — it's slow and
    we only need the JSON. Qwen3's chat template honours a `/no_think` directive; we append it to
    the system message (or add one). Combined with the payload `think:false` flag below, this
    covers Ollama + Qwen3 whether or not a given endpoint reads the flag."""
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "system":
            m["content"] = (m.get("content", "").rstrip() + "\n\n/no_think").strip()
            return out
    return [{"role": "system", "content": "/no_think"}] + out


def normalize_base_url(url: str) -> str:
    """Be forgiving about what the user types. A bare '192.168.2.200' becomes
    'http://192.168.2.200:11434/v1' (Ollama defaults); an explicit scheme/port/path is kept."""
    url = (url or "").strip()
    if not url:
        return url
    if "://" not in url:
        url = "http://" + url
    parts = urllib.parse.urlsplit(url)
    netloc = parts.netloc
    try:
        has_port = bool(parts.port)
    except ValueError:
        has_port = True
    if not has_port:
        netloc = netloc + ":11434"          # default Ollama port
    path = parts.path.rstrip("/")
    if path == "":
        path = "/v1"                         # default OpenAI-compatible base path
    return urllib.parse.urlunsplit((parts.scheme, netloc, path, "", ""))


def _endpoint(base_url: str) -> str:
    base = normalize_base_url(base_url).rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def chat(base_url: str, model: str, messages: list[dict], api_key: str = "",
         temperature: float = 0.7, timeout: float = 120.0, max_tokens: int | None = None) -> str:
    """Send a chat completion and return the assistant text. Raises LLMError on any failure."""
    if not base_url or not model:
        raise LLMError("AI server not configured (set a URL + model in AI Settings).")
    payload = {"model": model, "messages": _no_think_messages(messages),
               "temperature": temperature, "stream": False, "think": False}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(_endpoint(base_url), data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except ValueError as e:
        raise LLMError(f"That URL doesn't look right ({base_url!r}): {e}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        raise LLMError(f"Server returned HTTP {e.code}. {detail}")
    except urllib.error.URLError as e:
        raise LLMError(f"Can't reach the AI server at {base_url} ({e.reason}). "
                       f"Is it running and on the network?")
    except Exception as e:
        raise LLMError(f"AI request failed: {e}")
    try:
        content = body["choices"][0]["message"]["content"]
    except Exception:
        raise LLMError("Unexpected response shape from the AI server.")
    return _THINK_RE.sub("", content or "").strip()      # drop any leftover <think>…</think>


def list_models(base_url: str, api_key: str = "", timeout: float = 15.0) -> list[str]:
    """Ask the server what models it has (OpenAI-compatible /v1/models — Ollama/vLLM/LM Studio all
    expose it). Returns a sorted list of model ids. Raises LLMError on failure."""
    base = normalize_base_url(base_url).rstrip("/")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(base + "/models", headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except ValueError as e:
        raise LLMError(f"That URL doesn't look right ({base_url!r}): {e}")
    except urllib.error.HTTPError as e:
        raise LLMError(f"Server returned HTTP {e.code} listing models.")
    except urllib.error.URLError as e:
        raise LLMError(f"Can't reach {base} ({e.reason}). Is the server running?")
    except Exception as e:
        raise LLMError(f"Couldn't list models: {e}")
    data = body.get("data") if isinstance(body, dict) else None
    if not data:
        raise LLMError("Server responded but listed no models.")
    ids = [m.get("id") for m in data if isinstance(m, dict) and m.get("id")]
    return sorted(ids)


def ping(base_url: str, model: str, api_key: str = "", timeout: float = 90.0) -> tuple[bool, str]:
    """Reachability check for the AI Settings 'Test' button. Returns (ok, message). Timeout is
    generous because a big model (e.g. 32B) can take a while to load into VRAM on the first call.
    Catches EVERYTHING so the caller always gets an answer (never a silently-dead thread)."""
    try:
        txt = chat(base_url, model, [{"role": "user", "content": "reply with the word: ok"}],
                   api_key=api_key, temperature=0.0, timeout=timeout, max_tokens=8)
        where = normalize_base_url(base_url)
        return True, f"Connected to {where}. Model replied: {txt.strip()[:50]}"
    except Exception as e:
        return False, str(e)
