"""Tests for ollama_client.py — Ollama SDK wrapper."""

from unittest.mock import MagicMock

import pytest

import ollama_client


def _make_mock(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    return mock


# --- is_available ---

def test_is_available_true_when_list_succeeds(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.list.return_value = {}
    assert ollama_client.is_available() is True


def test_is_available_false_when_list_raises(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.list.side_effect = ConnectionRefusedError("down")
    assert ollama_client.is_available() is False


# --- generate ---

def test_generate_returns_response_string(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.generate.return_value = {"response": "answer text"}
    result = ollama_client.generate("sys", "prompt")
    assert result == "answer text"


def test_generate_passes_correct_args(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.generate.return_value = {"response": "ok"}
    ollama_client.generate("system", "user prompt", temperature=0.5)
    mock.generate.assert_called_once_with(
        model=ollama_client._MODEL,
        system="system",
        prompt="user prompt",
        options={"temperature": 0.5},
    )


def test_generate_raises_runtime_error_on_failure(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.generate.side_effect = Exception("boom")
    with pytest.raises(RuntimeError, match="Ollama generate failed"):
        ollama_client.generate("s", "p")


def test_generate_default_temperature(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.generate.return_value = {"response": "ok"}
    ollama_client.generate("s", "p")
    _, kwargs = mock.generate.call_args
    assert kwargs.get("options", {}).get("temperature") == 0.3


def test_generate_custom_temperature(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.generate.return_value = {"response": "ok"}
    ollama_client.generate("s", "p", temperature=0.9)
    _, kwargs = mock.generate.call_args
    assert kwargs.get("options", {}).get("temperature") == 0.9


# --- chat ---

def test_chat_returns_content_string(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.chat.return_value = {"message": {"content": "chat reply"}}
    result = ollama_client.chat([{"role": "user", "content": "hi"}])
    assert result == "chat reply"


def test_chat_passes_messages(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.chat.return_value = {"message": {"content": "ok"}}
    msgs = [{"role": "user", "content": "hello"}]
    ollama_client.chat(msgs)
    mock.chat.assert_called_once_with(
        model=ollama_client._MODEL,
        messages=msgs,
        options={"temperature": 0.7},
    )


def test_chat_raises_runtime_error_on_failure(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.chat.side_effect = Exception("fail")
    with pytest.raises(RuntimeError, match="Ollama chat failed"):
        ollama_client.chat([])


def test_chat_default_temperature(monkeypatch):
    mock = _make_mock(monkeypatch)
    mock.chat.return_value = {"message": {"content": "ok"}}
    ollama_client.chat([])
    _, kwargs = mock.chat.call_args
    assert kwargs.get("options", {}).get("temperature") == 0.7


def test_ollama_model_env_var(monkeypatch):
    monkeypatch.setattr(ollama_client, "_MODEL", "custom-model:7b")
    mock = _make_mock(monkeypatch)
    mock.generate.return_value = {"response": "ok"}
    ollama_client.generate("s", "p")
    _, kwargs = mock.generate.call_args
    assert kwargs.get("model") == "custom-model:7b"
