import pytest

from scripts import common


class Headers(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda _seconds: None)


def _responder(status, headers, body="", counter=None):
    def fake_fetch(url, request_headers, timeout=30):
        if counter is not None:
            counter.append(url)
        return status, Headers(headers), body
    return fake_fetch


class TestRateLimitReporting:
    def test_exhausted_retry_reports_rate_limit(self, monkeypatch, no_sleep):
        attempts = []
        monkeypatch.setattr(common, "_fetch", _responder(
            403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"},
            "rate limited", attempts))
        result = common.http_get_json("https://api.github.com/x", token="t")
        assert result.error["kind"] == "rate_limit"
        assert len(attempts) == 2

    def test_plain_403_is_not_a_rate_limit(self, monkeypatch, no_sleep):
        monkeypatch.setattr(common, "_fetch", _responder(
            403, {"x-ratelimit-remaining": "42"}, "forbidden"))
        result = common.http_get_json("https://api.github.com/x", token="t")
        assert result.error["kind"] == "http"

    def test_429_with_retry_after_is_not_a_rate_limit(self, monkeypatch, no_sleep):
        monkeypatch.setattr(common, "_fetch", _responder(
            429, {"retry-after": "5"}, "slow down"))
        result = common.http_get_json("https://api.github.com/x", token="t")
        assert result.error["kind"] == "http"

    def test_network_error_reported(self, monkeypatch):
        def boom(url, headers, timeout=30):
            raise common.NetworkError("dns failure")
        monkeypatch.setattr(common, "_fetch", boom)
        result = common.http_get_json("https://api.github.com/x", token="t")
        assert result.error["kind"] == "network"


class TestNoDiskCache:
    def test_repeated_calls_always_hit_the_network(self, monkeypatch):
        attempts = []
        monkeypatch.setattr(common, "_fetch", _responder(
            200, {}, '{"items": []}', attempts))
        for _ in range(3):
            assert common.http_get_json("https://api.github.com/x").error is None
        assert len(attempts) == 3
