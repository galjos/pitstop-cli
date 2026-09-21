"""Bounded download retries: transient failures retried, permanent ones raised fast."""

from __future__ import annotations

import io
import urllib.error

from pitstop import cache


class _Resp:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _req():
    import urllib.request

    return urllib.request.Request("https://example.test/x")


def test_retry_then_success(monkeypatch):
    monkeypatch.setattr(cache, "RETRY_BASE_DELAY", 0)
    calls = {"n": 0}

    def flaky(req, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, io.BytesIO())
        return _Resp(b"ok")

    monkeypatch.setattr(cache.urllib.request, "urlopen", flaky)
    assert cache.fetch_bytes(_req(), 5) == b"ok"
    assert calls["n"] == 3


def test_no_retry_on_404(monkeypatch):
    monkeypatch.setattr(cache, "RETRY_BASE_DELAY", 0)
    calls = {"n": 0}

    def missing(req, timeout):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 404, "nope", {}, io.BytesIO())

    monkeypatch.setattr(cache.urllib.request, "urlopen", missing)
    try:
        cache.fetch_bytes(_req(), 5)
    except urllib.error.HTTPError as e:
        assert e.code == 404
    else:
        raise AssertionError("expected HTTPError")
    assert calls["n"] == 1
