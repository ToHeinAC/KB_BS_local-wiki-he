"""Tests for gpu_widget.py (live sidebar GPU monitor) and template_loader.py."""

import json
import subprocess

import pytest
from starlette.applications import Starlette
from starlette.routing import Route

import gpu_widget
import template_loader

SMI = "NVIDIA GeForce RTX 4090, 30, 45, 12\nmalformed line\nNVIDIA GeForce RTX 4090, 0, 38, 0\n"


def _smi(monkeypatch, stdout=SMI, returncode=0, exc=None):
    def run(cmd, **_kw):
        if exc:
            raise exc
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    monkeypatch.setattr(gpu_widget.subprocess, "run", run)


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.setattr(gpu_widget, "_route_injected", False)
    gpu_widget.reset_research_timer()


def test_gpu_stats_parse_well_formed_lines(monkeypatch):
    _smi(monkeypatch)
    stats = gpu_widget._get_gpu_stats()
    assert stats[0] == {"name": "NVIDIA GeForce RTX 4090", "fan": "30", "temp": "45", "util": "12"}
    assert len(stats) == 2


@pytest.mark.parametrize(
    "kwargs",
    [{"returncode": 1}, {"exc": FileNotFoundError()}, {"exc": subprocess.TimeoutExpired("x", 3)}],
)
def test_gpu_stats_empty_without_nvidia_smi(monkeypatch, kwargs):
    _smi(monkeypatch, **kwargs)
    assert gpu_widget._get_gpu_stats() == []


def test_payload_reports_timer_and_model(monkeypatch):
    _smi(monkeypatch)
    monkeypatch.setattr(gpu_widget.time, "monotonic", iter([100.0, 142.5]).__next__)
    monkeypatch.setattr("ollama_client.loaded_model", lambda: "gemma4:e4b")
    gpu_widget.set_research_start()
    gpu_widget.set_research_end()
    payload = json.loads(gpu_widget._build_payload())
    assert payload["elapsed"] == 42
    assert payload["is_running"] is False
    assert payload["model"] == "gemma4:e4b"
    assert len(payload["gpus"]) == 2


def test_payload_without_timer(monkeypatch):
    _smi(monkeypatch, stdout="")
    monkeypatch.setattr("ollama_client.loaded_model", lambda: "m")
    gpu_widget.set_research_end()  # no start: stays unset
    payload = json.loads(gpu_widget._build_payload())
    assert payload["elapsed"] is None
    assert payload["is_running"] is False


@pytest.mark.parametrize(("option", "expected"), [("wiwi", "/wiwi"), ("/wiwi/", "/wiwi"), ("", "")])
def test_base_path_follows_streamlit_config(monkeypatch, option, expected):
    monkeypatch.setattr(gpu_widget.st_config, "get_option", lambda name: option)
    assert gpu_widget._base_path() == expected


def test_route_is_injected_once_and_serves_json(monkeypatch):
    monkeypatch.setattr(gpu_widget, "_base_path", lambda: "/wiwi")
    monkeypatch.setattr(gpu_widget, "_build_payload", lambda: '{"gpus": []}')
    app = Starlette(routes=[Route("/health", lambda request: None)])
    assert gpu_widget._inject_gpu_route() is True
    assert gpu_widget._inject_gpu_route() is True  # guard: no second route
    paths = [getattr(r, "path", None) for r in app.router.routes]
    assert paths.count("/wiwi/_api/gpu") == 1
    response = app.router.routes[0].endpoint(None)
    assert response.body == b'{"gpus": []}'
    assert response.headers["cache-control"] == "no-store"


def test_route_injection_fails_without_starlette_app(monkeypatch):
    monkeypatch.setattr(gpu_widget.gc, "get_objects", list)
    assert gpu_widget._inject_gpu_route() is False


def test_ensure_route_needs_a_gpu(monkeypatch):
    monkeypatch.setattr(gpu_widget, "_get_gpu_stats", list)
    assert gpu_widget._ensure_gpu_route() is False
    monkeypatch.setattr(gpu_widget, "_get_gpu_stats", lambda: [{"name": "x"}])
    monkeypatch.setattr(gpu_widget, "_inject_gpu_route", lambda: True)
    assert gpu_widget._ensure_gpu_route() is True
    monkeypatch.setattr(gpu_widget, "_inject_gpu_route", lambda: False)
    assert gpu_widget._ensure_gpu_route() is True  # cached for the process


def test_sidebar_renders_only_with_a_live_route(monkeypatch):
    rendered = []
    monkeypatch.setattr(gpu_widget.components, "html", lambda html, **kw: rendered.append(html))
    monkeypatch.setattr(gpu_widget, "_ensure_gpu_route", lambda: False)
    gpu_widget.render_gpu_sidebar()
    assert rendered == []
    monkeypatch.setattr(gpu_widget, "_ensure_gpu_route", lambda: True)
    gpu_widget.render_gpu_sidebar(accent="#123456")
    assert 'const accent = "#123456";' in rendered[0]


def test_insert_template_field_order():
    assert template_loader.load_insert_template() == [
        "name",
        "fullname",
        "description",
        "effective as of",
        "part of",
    ]


def test_insert_template_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(template_loader, "_TEMPLATE_PATH", tmp_path / "none.md")
    assert template_loader.load_insert_template() == []
