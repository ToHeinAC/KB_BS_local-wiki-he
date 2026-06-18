"""Live GPU stats widget via same-origin route injection.

Streamlit 1.57 serves its web app with Starlette/uvicorn (not Tornado). This
module injects a ``/_api/gpu`` route into the live Starlette app so the sidebar
iframe can poll the relative URL ``/_api/gpu`` every second. Because the URL is
same-origin, this works locally and over SSH/Cloudflare tunnels with no CORS,
no mixed-content issues, and no extra port — mirroring the researcher project's
proven design.

The live ``Starlette`` instance is discovered via ``gc.get_objects()`` since it
is only referenced indirectly (through ``uvicorn.Config.app``).
"""

import gc
import json
import logging
import subprocess
import time

import streamlit as st
import streamlit.components.v1 as components

logger = logging.getLogger(__name__)

_timer: dict = {"start": None, "end": None}


def set_research_start() -> None:
    _timer["start"] = time.monotonic()
    _timer["end"] = None


def set_research_end() -> None:
    if _timer["start"] is not None:
        _timer["end"] = time.monotonic()


def reset_research_timer() -> None:
    _timer["start"] = None
    _timer["end"] = None


# ---------------------------------------------------------------------------
# GPU stats
# ---------------------------------------------------------------------------

def _get_gpu_stats() -> list[dict]:
    """Query nvidia-smi. Returns [] on failure."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,fan.speed,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return []
        gpus = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 4:
                gpus.append({
                    "name": parts[0],
                    "fan": parts[1],
                    "temp": parts[2],
                    "util": parts[3],
                })
        return gpus
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def _build_payload() -> str:
    """Build JSON payload for the GPU stats endpoint."""
    gpus = _get_gpu_stats()
    elapsed = None
    is_running = False
    start = _timer["start"]
    if start is not None:
        end = _timer["end"] if _timer["end"] is not None else time.monotonic()
        elapsed = int(end - start)
        is_running = _timer["end"] is None
    return json.dumps({
        "gpus": gpus,
        "elapsed": elapsed,
        "is_running": is_running,
    })


# ---------------------------------------------------------------------------
# Starlette route injection (Streamlit >= 1.57)
# ---------------------------------------------------------------------------

def _inject_gpu_route() -> bool:
    """Inject ``/_api/gpu`` into Streamlit's live Starlette app. Returns success.

    Finds the live ``Starlette`` instance via gc (it is only referenced
    indirectly through ``uvicorn.Config.app``) and prepends a ``/_api/gpu``
    route so it is matched before the SPA static catch-all.
    """
    try:
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Route

        apps = [o for o in gc.get_objects() if isinstance(o, Starlette)]
        if not apps:
            logger.debug("No Starlette app found via gc")
            return False
        # The main Streamlit app has the most routes (health, media, ws, static, ...)
        app = max(apps, key=lambda a: len(a.router.routes))

        # Guard against double-registration (survives module reloads).
        for r in app.router.routes:
            if getattr(r, "path", None) == "/_api/gpu":
                return True

        # Sync endpoint — Starlette runs non-async handlers in a threadpool.
        def gpu_handler(request):
            return Response(
                content=_build_payload(),
                media_type="application/json",
                headers={"Cache-Control": "no-store"},
            )

        app.router.routes.insert(0, Route("/_api/gpu", endpoint=gpu_handler))
        logger.info("Injected /_api/gpu Starlette route for GPU widget")
        return True

    except Exception:
        logger.debug("Could not inject Starlette GPU route", exc_info=True)
        return False


_route_injected: bool = False


def _ensure_gpu_route() -> bool:
    """One-time injection per process. Returns True if the route is live."""
    global _route_injected
    if _route_injected:
        return True
    if not _get_gpu_stats():
        return False  # no GPU available
    _route_injected = _inject_gpu_route()
    return _route_injected


# ---------------------------------------------------------------------------
# HTML/JS template (fetches relative /_api/gpu)
# ---------------------------------------------------------------------------

def _gpu_html(model: str, accent: str = "#234637") -> str:
    return f"""\
<div id="gpu-stats" style="font-family:monospace; font-size:13px; color:#aaa; white-space:nowrap;">
  Lade GPU...
</div>
<script>
const accent = "{accent}";
function fetchGPU() {{
  fetch("/_api/gpu")
    .then(r => r.json())
    .then(data => {{
      const gpus = data.gpus || [];
      if (!gpus.length) return;
      let html = gpus.map(g => {{
        let name = g.name.replace("NVIDIA GeForce ", "").padEnd(10);
        let t = parseInt(g.temp);
        let u = parseInt(g.util);
        let tCol = t >= 80 ? "#ff4b4b" : t >= 70 ? "#ffa421" : accent;
        let uCol = u >= 80 ? "#ff4b4b" : u >= 50 ? "#ffa421" : accent;
        let fan = String(g.fan).padStart(2);
        let tmp = String(t).padStart(2);
        let load = String(u).padStart(3);
        return name
          + " <span style='color:" + tCol + "'>" + tmp + "&deg;C</span>"
          + "|Fan:" + fan + "%"
          + "|<span style='color:" + uCol + "'>Load:" + load + "%</span>";
      }}).join("<br>");
      html += "<br><span style='color:#aaa'>llm: {model}</span>";
      if (data.elapsed !== null && data.elapsed !== undefined) {{
        let eCol = data.is_running ? "#21c354" : "#aaa";
        let dots = data.is_running ? "..." : "";
        html += "<br><span style='color:" + eCol + "'>t: " + data.elapsed + "s" + dots + "</span>";
      }}
      document.getElementById("gpu-stats").innerHTML = html;
    }})
    .catch(() => {{}});
}}
fetchGPU();
setInterval(fetchGPU, 1000);
</script>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_gpu_sidebar(accent: str = "#234637") -> None:
    """Render live GPU widget in sidebar via Starlette route injection."""
    if not _ensure_gpu_route():
        return
    import ollama_client as _oc
    st.sidebar.markdown("**GPU**")
    with st.sidebar:
        components.html(_gpu_html(_oc._MODEL, accent), height=85, scrolling=False)
