"""Thin wrapper around the Ollama SDK."""

import os
import time

from dotenv import load_dotenv

import ollama_server

load_dotenv()

_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")

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
# Note the cap is per request slot: the server allocates num_ctx * OLLAMA_NUM_PARALLEL,
# so a parallel setting > 1 silently re-inflates the graph this cap exists to shrink.
_NUM_CTX = int(os.getenv("INGEST_NUM_CTX", "32768"))

# A crashed llama-server (not a bad request) — the ggml scheduler assert above is the
# usual cause. Ollama restarts the worker, so one retry at half the context can succeed.
_CRASH_MARKERS = ("GGML_ASSERT", "process has terminated", "status code: 500")


def host() -> str:
    """Base URL of the Ollama daemon this app talks to.

    Resolved on first use: a GPU-pinned daemon of our own when one can be
    started, else the configured OLLAMA_HOST unchanged. See src/ollama_server.py.
    Every caller must go through this — never read OLLAMA_HOST directly, or half
    the app ends up on the split daemon.
    """
    return ollama_server.host()


def _client():
    import ollama

    return ollama.Client(host=host())


def is_available() -> bool:
    try:
        _client().list()
        return True
    except Exception:
        return False


def embed(texts: list[str], model_id: str) -> list[list[float]]:
    """Return one embedding vector per input text via the local Ollama /api/embed.

    Used by the semantic retrieval arm (src/embed_index.py). No cloud API.
    """
    try:
        resp = _client().embed(model=model_id, input=list(texts))
        vecs = resp["embeddings"] if isinstance(resp, dict) else resp.embeddings
        if not vecs:
            raise RuntimeError("empty embeddings response")
        return vecs
    except Exception as exc:
        raise RuntimeError(f"Ollama embed failed ({model_id}): {exc}") from exc


def _generate_once(model: str, system: str, prompt: str, temperature: float, num_ctx: int) -> str:
    resp = _client().generate(
        model=model,
        system=system,
        prompt=prompt,
        options={"temperature": temperature, "num_ctx": num_ctx},
    )
    return resp["response"]


def generate(
    system: str, prompt: str, temperature: float = 0.3, model_id: str | None = None
) -> str:
    model = model_id or _MODEL
    try:
        return _generate_once(model, system, prompt, temperature, _NUM_CTX)
    except Exception as exc:
        if not any(m in str(exc) for m in _CRASH_MARKERS):
            raise RuntimeError(f"Ollama generate failed: {exc}") from exc
    time.sleep(3)  # let Ollama respawn the worker before the half-context retry
    try:
        return _generate_once(model, system, prompt, temperature, _NUM_CTX // 2)
    except Exception as exc:
        raise RuntimeError(f"Ollama generate failed: {exc}") from exc


def chat(messages: list[dict], temperature: float = 0.7) -> str:
    try:
        resp = _client().chat(
            model=_MODEL,
            messages=messages,
            options={"temperature": temperature, "num_ctx": _NUM_CTX},
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
        models = (
            getattr(resp, "models", None)
            or (resp.get("models") if isinstance(resp, dict) else None)
            or []
        )
        if models:
            m = models[0]
            return (
                getattr(m, "model", None)
                or (m.get("model") if isinstance(m, dict) else None)
                or _MODEL
            )
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
