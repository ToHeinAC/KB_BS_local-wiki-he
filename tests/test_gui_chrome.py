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
        "pinned_gpu": 0,
        "gpus": [{"name": "NVIDIA GeForce RTX 4090", "temp": "58", "util": "41", "fan": "30"}],
        "index": {"raw": 10, "wiki": 4},
    }
    assert gui_chrome.folio_text(data) == [
        "gemma4:e4b on GPU 0",
        "RTX 4090 at 58 °C, load 41 %",
        "Search index: 14 passages",
    ]


_CARDS = [
    {"name": "NVIDIA GeForce RTX 4090", "temp": "55", "util": "0", "fan": "0"},
    {"name": "NVIDIA GeForce RTX 4090", "temp": "68", "util": "90", "fan": "51"},
]


def test_folio_shows_the_pinned_card_not_the_first() -> None:
    data = {"model": "m", "pinned_gpu": 1, "gpus": _CARDS, "index": {"raw": 1, "wiki": 0}}
    assert gui_chrome.folio_text(data)[:2] == ["m on GPU 1", "RTX 4090 at 68 °C, load 90 %"]


def test_folio_without_a_pin_shows_the_busiest_card_and_names_it() -> None:
    cards = [{**_CARDS[1], "util": "[N/A]"}, _CARDS[0], _CARDS[1]]
    data = {"model": "m", "pinned_gpu": None, "gpus": cards, "index": {"raw": 1, "wiki": 0}}
    assert gui_chrome.folio_text(data)[1] == "GPU 2: RTX 4090 at 68 °C, load 90 %"


def test_folio_text_without_gpu_or_index() -> None:
    data = {"model": "m", "pinned_gpu": None, "gpus": [], "index": {"raw": 0, "wiki": 0}}
    assert gui_chrome.folio_text(data) == ["m on the shared daemon", "No search index"]
