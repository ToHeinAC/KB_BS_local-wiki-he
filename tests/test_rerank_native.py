"""The reranker's native path (_load / _tokenize / _score_one) against a fake llama_cpp.

The fake implements just the ctypes-level calls rerank.py makes, in pure Python: the
token buffer is a real ctypes array and the "model" scores a pair by how many query
tokens reappear in the document, so ordering assertions are meaningful.
"""

import ctypes
from types import SimpleNamespace

import pytest

import rerank

BOS, EOS, SEP = 1, 2, 3


class _Batch:
    def __init__(self, n: int) -> None:
        self.n_tokens = 0
        self.token = [0] * n
        self.pos = [0] * n
        self.n_seq_id = [0] * n
        self.seq_id = [[0] for _ in range(n)]
        self.logits = [False] * n


class FakeLlama:
    llama_token = ctypes.c_int32
    llama_log_callback = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)
    LLAMA_POOLING_TYPE_RANK = 4
    LLAMA_SPLIT_MODE_NONE = 0

    def __init__(self, *, load_ok: bool = True, ctx_ok: bool = True, decode_rc: int = 0):
        self.load_ok, self.ctx_ok, self.decode_rc = load_ok, ctx_ok, decode_rc
        self.freed = 0
        self._last: list[int] = []

    def llama_backend_init(self) -> None: ...
    def llama_log_set(self, cb: object, user_data: object) -> None: ...

    def llama_model_default_params(self) -> SimpleNamespace:
        return SimpleNamespace(split_mode=1, main_gpu=0)

    def llama_model_load_from_file(self, path: bytes, params: object) -> object:
        return "model" if self.load_ok else None

    def llama_context_default_params(self) -> SimpleNamespace:
        return SimpleNamespace()

    def llama_init_from_model(self, model: object, params: object) -> object:
        return "ctx" if self.ctx_ok else None

    def llama_model_get_vocab(self, model: object) -> str:
        return "vocab"

    def llama_tokenize(self, vocab, raw, n, buf, cap, add_special, parse_special) -> int:
        words = raw.decode().split()
        for i, w in enumerate(words[:cap]):
            buf[i] = 10 + sum(w.encode()) % 1000
        return len(words[:cap])

    def llama_vocab_bos(self, vocab: str) -> int:
        return BOS

    def llama_vocab_eos(self, vocab: str) -> int:
        return EOS

    def llama_vocab_sep(self, vocab: str) -> int:
        return SEP

    def llama_batch_init(self, n: int, embd: int, n_seq: int) -> _Batch:
        return _Batch(n)

    def llama_batch_free(self, batch: _Batch) -> None:
        self.freed += 1

    def llama_get_memory(self, ctx: object) -> str:
        return "mem"

    def llama_memory_clear(self, mem: object, data: bool) -> None: ...

    def llama_decode(self, ctx: object, batch: _Batch) -> int:
        self._last = batch.token[: batch.n_tokens]
        return self.decode_rc

    def llama_get_embeddings_seq(self, ctx: object, seq: int) -> list[float]:
        toks = self._last
        sep = toks.index(SEP)
        query, doc = set(toks[1 : sep - 1]), toks[sep + 1 : -1]
        return [float(sum(t in query for t in doc))]


@pytest.fixture
def fake(monkeypatch, tmp_path):
    gguf = tmp_path / "reranker.gguf"
    gguf.write_bytes(b"\0" * 64)
    llama = FakeLlama()
    monkeypatch.setattr(rerank, "_model_path", lambda: gguf)
    monkeypatch.setattr(rerank, "_llama_cpp", lambda: llama)
    monkeypatch.setattr(rerank, "_state", None)
    monkeypatch.setenv("RERANK_PIN_GPU", "off")
    monkeypatch.delenv("RERANK_ENABLED", raising=False)
    return llama


def test_score_pairs_ranks_by_the_cross_encoder(fake):
    scores = rerank.score_pairs("radon dose limit", ["weather today", "radon dose limit radon"])
    assert scores == [0.0, 4.0]
    assert fake.freed == 2  # every batch is freed


def test_state_is_loaded_once(fake):
    rerank.score_pairs("a", ["a"])
    first = rerank._state
    rerank.score_pairs("a", ["a"])
    assert rerank._state is first


@pytest.mark.parametrize("kwargs", [{"load_ok": False}, {"ctx_ok": False}, {"decode_rc": 1}])
def test_native_failures_fail_open(fake, monkeypatch, kwargs):
    llama = FakeLlama(**kwargs)
    monkeypatch.setattr(rerank, "_llama_cpp", lambda: llama)
    assert rerank.score_pairs("q", ["d"]) == []


def test_load_exception_fails_open(fake, monkeypatch):
    def boom() -> None:
        raise OSError("bad gguf")

    monkeypatch.setattr(fake, "llama_backend_init", boom)
    assert rerank._load() is None


@pytest.mark.parametrize(("query", "docs"), [("   ", ["d"]), ("q", [])])
def test_empty_inputs_score_nothing(fake, query, docs):
    assert rerank.score_pairs(query, docs) == []


def test_llama_cpp_absent_means_unavailable(monkeypatch):
    def missing(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr(rerank.importlib, "import_module", missing)
    assert rerank._llama_cpp() is None


def test_preload_cuda_loads_wheel_libraries(monkeypatch, tmp_path):
    for pkg in ("cuda_runtime", "cublas"):
        lib = tmp_path / pkg / "lib"
        lib.mkdir(parents=True)
        (lib / f"lib{pkg}.so.12").write_bytes(b"")
    loaded: list[str] = []

    def cdll(path: str, mode: int = 0) -> None:
        loaded.append(path.rsplit("/", 1)[-1])
        if "cublas" in path:
            raise OSError("wrong arch")  # suppressed: CPU build keeps working

    monkeypatch.setattr(
        rerank.importlib, "import_module", lambda n: SimpleNamespace(__path__=[str(tmp_path)])
    )
    monkeypatch.setattr(rerank.ctypes, "CDLL", cdll)
    rerank._preload_cuda()
    assert loaded == ["libcuda_runtime.so.12", "libcublas.so.12"]


def test_preload_cuda_without_wheels_is_a_no_op(monkeypatch):
    def missing(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr(rerank.importlib, "import_module", missing)
    monkeypatch.setattr(rerank.ctypes, "CDLL", lambda *a, **k: pytest.fail("no load"))
    rerank._preload_cuda()
