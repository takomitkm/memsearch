"""Contract tests for the self-hosted rerank adapter, without network calls."""

import copy
import http.client
import io
import json
import threading
import urllib.error
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from memsearch.core import MemSearch
from memsearch.qwen_reranker import DEFAULT_URL, QwenApiReranker
from memsearch.reranker import rerank


def response(scores):
    return {
        "model": "Qwen3-Reranker-8B",
        "results": [{"index": index, "relevance_score": score} for index, score in enumerate(scores)],
        "usage": {"documents": len(scores)},
    }


def open_request(scores, calls):
    def handler(request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(json.dumps(response(scores)).encode())

    return handler


def test_dispatch_strips_prefix_and_scores_every_candidate(monkeypatch):
    candidates = [
        {"content": "long memory " * 2000, "source": "a.md", "score": 9},
        {"content": "second", "source": "b.md", "chunk_id": "b"},
        {"content": "third", "source": "c.md"},
    ]
    before = copy.deepcopy(candidates)
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", open_request([0.2, 0.8, 0.8], calls))

    ranked = rerank("question", candidates, model_name="qwen-api:Qwen3-Reranker-8B", top_k=2)

    assert [r["source"] for r in ranked] == ["b.md", "c.md"]
    assert ranked[0]["chunk_id"] == "b"
    assert candidates == before
    assert len(calls) == 1
    request, timeout = calls[0]
    payload = json.loads(request.data)
    assert payload == {
        "model": "Qwen3-Reranker-8B",
        "query": "question",
        "documents": [c["content"] for c in candidates],
    }
    assert request.full_url == DEFAULT_URL
    assert request.get_header("Content-type") == "application/json"
    assert timeout == 60


def test_url_comes_from_environment(monkeypatch):
    monkeypatch.setenv("MEMSEARCH_QWEN_RERANKER_URL", "http://127.0.0.1:9999/rerank")
    assert QwenApiReranker().url == "http://127.0.0.1:9999/rerank"
    assert QwenApiReranker(url="http://explicit/rerank").url == "http://explicit/rerank"


def test_unranked_candidates_are_dropped(monkeypatch):
    # A top_n response ranks only two of the four candidates.
    short = {"model": "Qwen3-Reranker-8B", "results": [{"index": 2, "relevance_score": 0.9}]}
    calls = []

    def handler(request, timeout):
        calls.append(request)
        return io.BytesIO(json.dumps(short).encode())

    monkeypatch.setattr("urllib.request.urlopen", handler)
    candidates = [{"content": f"passage {i}"} for i in range(4)]
    ranked = QwenApiReranker().rerank("question", candidates)
    assert [r["content"] for r in ranked] == ["passage 2"]


def test_empty_candidates_need_no_request(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("empty candidate list must not reach the network")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    assert QwenApiReranker().rerank("query", []) == []


@pytest.mark.parametrize("score", [None, True, "0.5", float("nan"), float("inf")])
def test_invalid_scores_fail(score):
    result = response([0.5])
    result["results"][0]["relevance_score"] = score
    with pytest.raises(ValueError, match="score"):
        QwenApiReranker.scores(result, 1)


@pytest.mark.parametrize("index", [-1, 1, 4, "0", True, None])
def test_invalid_indexes_fail(index):
    result = response([0.5])
    result["results"][0]["index"] = index
    with pytest.raises(ValueError, match="index"):
        QwenApiReranker.scores(result, 1)


def test_missing_results_or_duplicates_fail():
    with pytest.raises(ValueError, match="results list"):
        QwenApiReranker.scores({"model": "x"}, 1)
    duplicated = {"results": [{"index": 0, "relevance_score": 0.1}, {"index": 0, "relevance_score": 0.2}]}
    with pytest.raises(ValueError, match="duplicate"):
        QwenApiReranker.scores(duplicated, 2)


@pytest.mark.parametrize("code", [401, 429, 503])
def test_http_errors_do_not_leak_body_or_fall_back(monkeypatch, code):
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError(DEFAULT_URL, code, "private payload", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(RuntimeError, match=f"HTTP {code}") as exc:
        QwenApiReranker().rerank("query", [{"content": "private text"}])
    assert "private" not in str(exc.value)


def test_disconnected_remote_request_fails_explicitly(monkeypatch):
    def disconnect(*args, **kwargs):
        raise http.client.RemoteDisconnected("Remote end closed connection")

    monkeypatch.setattr("urllib.request.urlopen", disconnect)
    with pytest.raises(RuntimeError, match="failed or timed out"):
        QwenApiReranker().rerank("query", [{"content": "text"}])


def test_invalid_configuration():
    with pytest.raises(ValueError):
        QwenApiReranker(model="")
    with pytest.raises(ValueError):
        QwenApiReranker(timeout=0)
    with pytest.raises(ValueError):
        QwenApiReranker().rerank("q", [], top_k=-1)


@pytest.mark.asyncio
async def test_search_fetches_extra_candidates_and_returns_qwen_top_k(monkeypatch):
    candidates = [{"content": f"passage {i}", "chunk_id": str(i)} for i in range(6)]
    store = Mock()
    store.search.return_value = candidates
    mem = MemSearch.__new__(MemSearch)
    mem._embedder = SimpleNamespace(embed=AsyncMock(return_value=[[0.1, 0.2]]))
    mem._store = store
    mem._reranker_model = "qwen-api:Qwen3-Reranker-8B"

    def remote_request(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        return io.BytesIO(json.dumps(response([0.1, 0.2, 0.3, 0.9, 0.4, 0.8])).encode())

    monkeypatch.setattr("urllib.request.urlopen", remote_request)
    results = await mem.search("question", top_k=2)
    assert [r["chunk_id"] for r in results] == ["3", "5"]
    assert store.search.call_args.kwargs["top_k"] == 6
