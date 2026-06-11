"""Thin wrapper around the Ollama SDK."""

import os

from dotenv import load_dotenv

load_dotenv()

_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Per-role model overrides. Each defaults to _MODEL, so behaviour is unchanged
# unless the operator sets the env var. QUERY = precision/selection calls,
# INGEST = page synthesis, FAST = lightweight maintenance (lint).
_QUERY_MODEL = os.getenv("QUERY_MODEL") or _MODEL
_INGEST_MODEL = os.getenv("INGEST_MODEL") or _MODEL
_FAST_MODEL = os.getenv("FAST_MODEL") or _MODEL


def _client():
    import ollama
    return ollama.Client(host=_HOST)


def is_available() -> bool:
    try:
        _client().list()
        return True
    except Exception:
        return False


def generate(system: str, prompt: str, temperature: float = 0.3, model_id: str | None = None) -> str:
    try:
        resp = _client().generate(
            model=model_id or _MODEL,
            system=system,
            prompt=prompt,
            options={"temperature": temperature},
        )
        return resp["response"]
    except Exception as exc:
        raise RuntimeError(f"Ollama generate failed: {exc}") from exc


def chat(messages: list[dict], temperature: float = 0.7) -> str:
    try:
        resp = _client().chat(
            model=_MODEL,
            messages=messages,
            options={"temperature": temperature},
        )
        return resp["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"Ollama chat failed: {exc}") from exc


def ocr(model_id: str, prompt: str, image_b64: str, temperature: float = 0.0) -> str:
    """Run a vision OCR model on one base64 image. model_id must be vision-capable."""
    try:
        resp = _client().chat(
            model=model_id,
            messages=[{"role": "user", "content": prompt, "images": [image_b64]}],
            options={"temperature": temperature},
        )
        return resp["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"Ollama OCR failed ({model_id}): {exc}") from exc


def rewrite(model_id: str, prompt: str, temperature: float = 0.0) -> str:
    """Reformat text into Markdown via a text model, using a given model id."""
    try:
        resp = _client().chat(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": temperature},
        )
        return resp["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"Ollama rewrite failed ({model_id}): {exc}") from exc
