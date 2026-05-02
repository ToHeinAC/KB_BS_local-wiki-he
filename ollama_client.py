"""Thin wrapper around the Ollama SDK."""

import os

from dotenv import load_dotenv

load_dotenv()

_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


def _client():
    import ollama
    return ollama.Client(host=_HOST)


def is_available() -> bool:
    try:
        _client().list()
        return True
    except Exception:
        return False


def generate(system: str, prompt: str, temperature: float = 0.3) -> str:
    try:
        resp = _client().generate(
            model=_MODEL,
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
