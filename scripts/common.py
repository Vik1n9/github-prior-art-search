import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_ROOT / "config.json"
USER_AGENT = "github-prior-art-search"
RATE_LIMIT_STATUSES = (403, 429)


class ScriptFailure(Exception):
    def __init__(self, message: str, reason_code: str = "failed"):
        super().__init__(message)
        self.reason_code = reason_code


@lru_cache(maxsize=1)
def load_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_skill_metadata() -> Dict[str, str]:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not frontmatter:
        raise ScriptFailure("SKILL.md 缺少 YAML frontmatter", "invalid_skill")
    block = frontmatter.group(1)
    name = re.search(r"^name:\s*(\S+)", block, re.M)
    if not name:
        raise ScriptFailure("SKILL.md frontmatter 缺少 name 欄位", "invalid_skill")
    version = re.search(r"^\s+version:\s*[\"']?([^\"'\s]+)", block, re.M)
    return {"name": name.group(1), "version": version.group(1) if version else ""}


def get_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise ScriptFailure(
            "缺少環境變數 GITHUB_TOKEN，技能不得執行。"
            "請先設定：export GITHUB_TOKEN=<your_personal_access_token>",
            reason_code="missing_github_token",
        )
    return token


def output_dir() -> Path:
    configured = os.environ.get("SKILL_OUTPUT_DIR", "").strip()
    path = Path(configured) if configured else (
        Path.cwd() / load_config()["output_dir_default"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


class HttpResult(NamedTuple):
    data: Any = None
    error: Optional[Dict[str, str]] = None


class NetworkError(Exception):
    pass


def _request_headers(token: Optional[str], accept: str) -> Dict[str, str]:
    headers = {"Accept": accept, "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch(url: str, headers: Dict[str, str], timeout: float = 30
           ) -> Tuple[int, Any, str]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            return status, response.headers, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return exc.code, exc.headers, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NetworkError(str(getattr(exc, "reason", exc)))


def _is_rate_limited(status: int, headers: Any) -> bool:
    if status not in RATE_LIMIT_STATUSES:
        return False
    if headers.get("x-ratelimit-remaining") == "0":
        return True
    return status == 429 and not headers.get("retry-after")


def _rate_limit_wait_seconds(headers: Any, max_wait: int) -> int:
    reset = headers.get("x-ratelimit-reset")
    if reset and str(reset).isdigit():
        return min(max(int(reset) - int(time.time()) + 2, 5), max_wait)
    retry_after = headers.get("retry-after")
    if retry_after and str(retry_after).isdigit():
        return min(max(int(retry_after), 5), max_wait)
    return max_wait


def http_get_json(url: str, token: Optional[str] = None,
                  params: Optional[Dict[str, Any]] = None) -> HttpResult:
    full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    headers = _request_headers(token, "application/vnd.github+json")
    max_wait = int(load_config()["search"]["rate_limit_max_wait_seconds"])

    for attempt in range(2):
        try:
            status, response_headers, text = _fetch(full_url, headers)
        except NetworkError as exc:
            return HttpResult(error={"kind": "network", "detail": str(exc)})

        if status == 200:
            try:
                return HttpResult(data=json.loads(text))
            except ValueError:
                return HttpResult(error={"kind": "http", "detail": "回應非 JSON"})

        if not _is_rate_limited(status, response_headers):
            return HttpResult(error={"kind": "http",
                                     "detail": f"HTTP {status}: {text[:200]}"})
        if attempt == 0:
            time.sleep(_rate_limit_wait_seconds(response_headers, max_wait))

    return HttpResult(error={"kind": "rate_limit",
                             "detail": "GitHub API rate limit，重試後仍失敗"})


def http_get_text(url: str, token: Optional[str] = None
                  ) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    headers = _request_headers(token, "text/plain; charset=utf-8")
    try:
        status, _headers, text = _fetch(url, headers)
    except NetworkError as exc:
        return None, {"kind": "network", "detail": str(exc)}
    if status == 200:
        return text, None
    if status == 404:
        return None, None
    return None, {"kind": "http", "detail": f"HTTP {status} for {url}"}


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_+.#-]+")
_CJK_CHUNK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


def tokenize(text: str) -> List[str]:
    text = text or ""
    tokens = [tok for tok in
              (raw.strip(".-_+#") for raw in _TOKEN_RE.findall(text.lower()))
              if tok]
    tokens.extend(_CJK_CHUNK_RE.findall(text))
    return tokens


def term_matches(term: str, haystack: str) -> bool:
    term = (term or "").strip().lower()
    haystack = (haystack or "").lower()
    if not term:
        return False
    if _CJK_RE.search(term):
        return term in haystack
    pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def truncate_text(text: Optional[str], limit: int = 30000) -> str:
    return (text or "")[:limit]
