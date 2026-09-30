import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional, Tuple

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_ROOT / "config.json"
USER_AGENT = "github-prior-art-search"
RATE_LIMIT_STATUSES = (403, 429)
SECONDARY_LIMIT_MARKER = "secondary rate limit"


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


def output_dir(override: Optional[str] = None) -> Path:
    configured = override or os.environ.get("SKILL_OUTPUT_DIR", "").strip()
    return Path(configured) if configured else (
        Path.cwd() / load_config()["output_dir_default"])


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_json(path: Path, missing_reason: str = "invalid_input") -> Any:
    if not path.exists():
        raise ScriptFailure(f"找不到檔案：{path}", missing_reason)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScriptFailure(f"{path} 不是合法 JSON：{exc}", missing_reason)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HttpResult(NamedTuple):
    data: Any = None
    error: Optional[Dict[str, str]] = None


class NetworkError(Exception):
    pass


def _request_headers(token: Optional[str], accept: str) -> Dict[str, str]:
    headers = {"Accept": accept, "User-Agent": USER_AGENT,
               "X-GitHub-Api-Version": "2022-11-28"}
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


def _is_rate_limited(status: int, headers: Any, body: str) -> bool:
    if status not in RATE_LIMIT_STATUSES:
        return False
    if headers.get("x-ratelimit-remaining") == "0" or headers.get("retry-after"):
        return True
    return status == 429 or SECONDARY_LIMIT_MARKER in body.lower()


def _rate_limit_wait_seconds(headers: Any, max_wait: int) -> int:
    retry_after = headers.get("retry-after")
    if retry_after and str(retry_after).isdigit():
        return min(max(int(retry_after), 1), max_wait)
    reset = headers.get("x-ratelimit-reset")
    if headers.get("x-ratelimit-remaining") == "0" and reset and str(reset).isdigit():
        return min(max(int(reset) - int(time.time()) + 2, 5), max_wait)
    return min(60, max_wait)


def http_get(url: str, token: Optional[str] = None,
             params: Optional[Dict[str, Any]] = None,
             accept: str = "application/vnd.github+json",
             not_found_ok: bool = False) -> HttpResult:
    full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    headers = _request_headers(token, accept)
    max_wait = int(load_config()["search"]["rate_limit_max_wait_seconds"])

    for attempt in range(2):
        try:
            status, response_headers, text = _fetch(full_url, headers)
        except NetworkError as exc:
            return HttpResult(error={"kind": "network", "detail": str(exc)})

        if status == 200:
            return HttpResult(data=text)
        if status == 404 and not_found_ok:
            return HttpResult()
        if not _is_rate_limited(status, response_headers, text):
            return HttpResult(error={"kind": "http",
                                     "detail": f"HTTP {status}: {text[:200]}"})
        if attempt == 0:
            time.sleep(_rate_limit_wait_seconds(response_headers, max_wait))

    return HttpResult(error={"kind": "rate_limit",
                             "detail": "GitHub API rate limit，等待重試後仍失敗"})


def http_get_json(url: str, token: Optional[str] = None,
                  params: Optional[Dict[str, Any]] = None) -> HttpResult:
    result = http_get(url, token, params)
    if result.error:
        return result
    try:
        return HttpResult(data=json.loads(result.data))
    except ValueError:
        return HttpResult(error={"kind": "http", "detail": "回應非 JSON"})


_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
_SEPARATOR_RE = re.compile(r"[\s_\-]+")
_INFLECTIONS = r"(?:s|es|er|ers|ing|ed)?"


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


@lru_cache(maxsize=4096)
def _term_pattern(term: str) -> "re.Pattern[str]":
    words = [p for p in _SEPARATOR_RE.split(term) if p]
    body = r"[\s_\-]*".join(re.escape(p) for p in words)
    if has_cjk(term):
        return re.compile(body)
    suffix = _INFLECTIONS if words and len(words[-1]) >= 4 else ""
    return re.compile(r"(?<![a-z0-9])" + body + suffix + r"(?![a-z0-9])")


def term_matches(term: str, haystack: str) -> bool:
    term = (term or "").strip().lower()
    if not term or not haystack:
        return False
    return _term_pattern(term).search(haystack.lower()) is not None
