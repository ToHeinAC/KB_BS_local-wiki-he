"""Pure helpers of the Broadsheet chrome (src/gui_chrome.py)."""

import gui_chrome


def test_stamp_is_plain_violet_or_reversed_by_level() -> None:
    assert gui_chrome.stamp("KI") == ("Normal", "")
    assert gui_chrome.stamp("KI@confidential") == ("Confidential", "conf")
    assert gui_chrome.stamp("KI@strict") == ("Strictly confidential", "strict")


def test_nav_starts_at_2brain_and_has_no_upload_page() -> None:
    assert gui_chrome.NAV == (
        ("2BrAIn", "/"),
        ("Explorer", "/explorer"),
        ("Chat", "/chat"),
        ("Research", "/research"),
        ("Maintenance", "/maintenance"),
    )


def test_folio_text_reports_model_gpu_and_index() -> None:
    data = {
        "model": "gemma4:e4b",
        "pinned_gpu": 1,
        "gpus": [{"name": "NVIDIA GeForce RTX 4090", "temp": "58", "util": "41", "fan": "30"}],
        "index": {"raw": 10, "wiki": 4},
    }
    assert gui_chrome.folio_text(data) == [
        "gemma4:e4b on GPU 1",
        "RTX 4090 at 58 °C, load 41 %",
        "Search index: 14 passages",
    ]


def test_folio_text_without_gpu_or_index() -> None:
    data = {"model": "m", "pinned_gpu": None, "gpus": [], "index": {"raw": 0, "wiki": 0}}
    assert gui_chrome.folio_text(data) == ["m on the shared daemon", "No search index"]
