import pytest

from scripts import common


class Headers(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(common.time, "sleep", recorded.append)
    return recorded


def _responder(responses, counter):
    def fake_fetch(url, request_headers, timeout=30):
        counter.append(url)
        status, headers, body = responses[min(len(counter) - 1, len(responses) - 1)]
        return status, Headers(headers), body
    return fake_fetch


def _call(monkeypatch, responses, **kwargs):
    attempts = []
    monkeypatch.setattr(common, "_fetch", _responder(responses, attempts))
    return common.http_get_json("https://api.github.com/x", token="t", **kwargs), attempts


class TestRateLimit:
    def test_primary_limit_exhausted_after_one_retry(self, monkeypatch, sleeps):
        result, attempts = _call(monkeypatch, [
            (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}, "limited")])
        assert result.error["kind"] == "rate_limit"
        assert len(attempts) == 2
        assert len(sleeps) == 1

    def test_secondary_limit_with_retry_after_waits_and_retries(self, monkeypatch, sleeps):
        result, attempts = _call(monkeypatch, [
            (429, {"retry-after": "7"}, "slow down"),
            (200, {}, '{"ok": true}')])
        assert result.data == {"ok": True}
        assert sleeps == [7]

    def test_secondary_limit_detected_from_body(self, monkeypatch, sleeps):
        result, attempts = _call(monkeypatch, [
            (403, {}, "You have exceeded a secondary rate limit"),
            (200, {}, "[]")])
        assert result.data == []
        assert sleeps == [60]

    def test_plain_403_is_not_retried(self, monkeypatch, sleeps):
        result, attempts = _call(monkeypatch, [
            (403, {"x-ratelimit-remaining": "42"}, "forbidden")])
        assert result.error["kind"] == "http"
        assert len(attempts) == 1
        assert sleeps == []


class TestOtherResponses:
    def test_network_error_reported(self, monkeypatch):
        def boom(url, headers, timeout=30):
            raise common.NetworkError("dns failure")
        monkeypatch.setattr(common, "_fetch", boom)
        result = common.http_get_json("https://api.github.com/x", token="t")
        assert result.error == {"kind": "network", "detail": "dns failure"}

    def test_404_is_empty_when_allowed(self, monkeypatch):
        attempts = []
        monkeypatch.setattr(common, "_fetch", _responder([(404, {}, "")], attempts))
        result = common.http_get("https://x", not_found_ok=True)
        assert result.data is None and result.error is None

    def test_404_is_error_by_default(self, monkeypatch):
        attempts = []
        monkeypatch.setattr(common, "_fetch", _responder([(404, {}, "")], attempts))
        assert common.http_get("https://x").error["kind"] == "http"

    def test_non_json_body_reported(self, monkeypatch):
        result, _ = _call(monkeypatch, [(200, {}, "<html>")])
        assert result.error["detail"] == "回應非 JSON"


class TestTermMatching:
    @pytest.mark.parametrize("term,haystack,expected", [
        ("rate limit", "A Rate-Limit middleware", True),
        ("rate limit", "rate_limit helpers", True),
        ("rate limiter", "ratelimiter for go", True),
        ("rate limit", "moderate limits", False),
        ("rate limit", "rate limiting middleware", True),
        ("rate limit", "rate limitation", False),
        ("go", "golang", False),
        ("go", "going further", False),
        ("redis", "Redis-backed store", True),
        ("滑動視窗", "支援滑動視窗演算法", True),
        ("", "anything", False),
    ])
    def test_term_matches(self, term, haystack, expected):
        assert common.term_matches(term, haystack) is expected
