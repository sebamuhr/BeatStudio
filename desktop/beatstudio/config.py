"""App-level settings persisted to desktop/config.json.

Right now this holds the AI arrange server: a base URL + model name (+ optional API key).
Kept deliberately generic — the client speaks the OpenAI-compatible chat API, which Ollama,
vLLM, LM Studio and llama.cpp all expose, so pointing at a new server/model is just editing
these two fields. You can change them anytime from the AI Settings dialog.
"""
from __future__ import annotations
import os
import json

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../desktop
_PATH = os.path.join(_HERE, "config.json")

# Sensible default: a local Ollama on this machine. The user will usually point base_url at
# their home server (e.g. http://192.168.1.50:11434/v1) and set their own model tag.
DEFAULTS = {
    "ai_base_url": "http://localhost:11434/v1",
    "ai_model": "qwen2.5:32b-instruct",
    "ai_api_key": "",            # most local servers ignore this; some want a dummy token
    "ai_enabled": True,
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f) or {})
    except FileNotFoundError:
        pass
    except Exception:
        pass                     # a corrupt config should never block startup
    return cfg


def save(cfg: dict) -> None:
    merged = dict(DEFAULTS)
    merged.update(cfg or {})
    try:
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
    except Exception:
        pass


def ai_configured(cfg: dict | None = None) -> bool:
    cfg = cfg or load()
    return bool(cfg.get("ai_enabled")) and bool(cfg.get("ai_base_url")) and bool(cfg.get("ai_model"))
