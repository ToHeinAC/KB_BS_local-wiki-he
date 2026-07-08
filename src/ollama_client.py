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

# Cap the KV context for generate(). Models like gemma4:e4b (Gemma 3n) default
# to a 131072-token window; that inflates the compute graph enough to trip the
# ggml scheduler assert (GGML_SCHED_MAX_SPLIT_INPUTS) during ingest synthesis.
# An ingest piece is <= MAX_INGEST_CHARS (~13K tokens) + system + output, so 32K
# is ample while keeping the graph small enough to stay on one GPU.
_NUM_CTX = int(os.getenv("INGEST_NUM_CTX", "32768"))


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
            options={"temperature": temperature, "num_ctx": _NUM_CTX},
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


def unload(model_id: str) -> None:
    """Evict a model from VRAM (keep_alive=0). Frees the GPU so a following
    generate() model isn't forced to share/split. Best-effort; ignores errors."""
    try:
        _client().generate(model=model_id, prompt="", keep_alive=0)
    except Exception:
        pass


def loaded_model() -> str:
    """Model currently loaded in Ollama VRAM; falls back to configured _MODEL when idle."""
    try:
        resp = _client().ps()
        models = getattr(resp, "models", None) or (resp.get("models") if isinstance(resp, dict) else None) or []
        if models:
            m = models[0]
            return getattr(m, "model", None) or (m.get("model") if isinstance(m, dict) else None) or _MODEL
    except Exception:
        pass
    return _MODEL


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
