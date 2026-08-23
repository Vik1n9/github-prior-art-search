# -*- coding: utf-8 -*-
"""共用工具：設定載入、環境變數、帶快取的 HTTP 客戶端、文字處理。"""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_ROOT / "config.yaml"

_CONFIG_CACHE: Optional[Dict[str, Any]] = None


class ScriptFailure(Exception):
    """致命錯誤：技能必須停止並回報原因（§22.1）。"""

    def __init__(self, message: str, reason_code: str = "failed"):
        super().__init__(message)
        self.reason_code = reason_code


def load_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _CONFIG_CACHE = yaml.safe_load(f)
    return _CONFIG_CACHE


def get_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise ScriptFailure(
            "缺少環境變數 GITHUB_TOKEN，技能不得執行。"
            "請先設定：export GITHUB_TOKEN=<your_personal_access_token>",
            reason_code="missing_github_token",
        )
    return token


def resolve_dir(env_var: str, default_relative: str) -> Path:
    value = os.environ.get(env_var, "").strip()
    p = Path(value) if value else (Path.cwd() / default_relative)
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    cfg = load_config()
    return resolve_dir("SKILL_CACHE_DIR", cfg["cache_dir_default"])


def output_dir() -> Path:
    cfg = load_config()
    return resolve_dir("SKILL_OUTPUT_DIR", cfg["output_dir_default"])


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# HTTP 客戶端：磁碟快取 + rate limit 處理（§22.3 → status=partial）
# ---------------------------------------------------------------------------

class HttpResult:
    def __init__(self, data: Any = None, error: Optional[Dict[str, str]] = None,
                 from_cache: bool = False):
        self.data = data
        self.error = error          # {"kind": "rate_limit"|"http"|"network", "detail": "..."}
        self.from_cache = from_cache

    @property
    def ok(self) -> bool:
        return self.error is None


def _cache_path(url: str, params: Optional[Dict[str, Any]]) -> Path:
    raw = url + "?" + json.dumps(params or {}, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", url.split("//", 1)[-1])[:80]
    return cache_dir() / "api" / f"{safe_name}.{digest}.json"


def http_get_json(url: str, token: Optional[str] = None,
                  params: Optional[Dict[str, Any]] = None,
                  headers: Optional[Dict[str, str]] = None,
                  use_cache: bool = True) -> HttpResult:
    """GET 並回傳 JSON。命中磁碟快取時不發請求。"""
    cp = _cache_path(url, params)
    if use_cache and cp.exists():
        try:
            return HttpResult(data=read_json(cp), from_cache=True)
        except Exception:
            pass  # 快取損毀則重新抓取

    base_headers = {"Accept": "application/vnd.github+json"}
    if token:
        base_headers["Authorization"] = f"Bearer {token}"
    if headers:
        base_headers.update(headers)

    cfg = load_config()["search"]
    max_wait = int(cfg.get("rate_limit_max_wait_seconds", 130))

    for attempt in (0, 1):  # rate limit 時最多重試一次
        try:
            resp = requests.get(url, params=params or {}, headers=base_headers, timeout=30)
        except requests.RequestException as exc:
            return HttpResult(error={"kind": "network", "detail": str(exc)})

        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                return HttpResult(error={"kind": "http", "detail": "回應非 JSON"})
            if use_cache:
                write_json(cp, data)
            return HttpResult(data=data)

        if resp.status_code in (403, 429) and attempt == 0:
            remaining = resp.headers.get("x-ratelimit-remaining")
            reset_hdr = resp.headers.get("x-ratelimit-reset")
            is_rate_limit = (remaining == "0") or (
                resp.status_code == 429 and not resp.headers.get("retry-after"))
            if is_rate_limit:
                wait = max_wait
                if reset_hdr and reset_hdr.isdigit():
                    wait = min(max(int(reset_hdr) - int(time.time()) + 2, 5), max_wait)
                else:
                    retry_after = resp.headers.get("retry-after")
                    if retry_after and retry_after.isdigit():
                        wait = min(max(int(retry_after), 5), max_wait)
                time.sleep(wait)
                continue
            return HttpResult(error={"kind": "http",
                                     "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"})

        return HttpResult(error={"kind": "http",
                                 "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"})

    return HttpResult(error={"kind": "rate_limit",
                             "detail": "GitHub API rate limit，重試後仍失敗"})


def http_get_text(url: str, token: Optional[str] = None,
                  accept: str = "text/plain; charset=utf-8") -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    """抓取純文字內容（README、依賴清單）。回傳 (text, error)。"""
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        return None, {"kind": "network", "detail": str(exc)}
    if resp.status_code == 200:
        return resp.text, None
    if resp.status_code == 404:
        return None, None  # 檔案不存在不算錯誤
    return None, {"kind": "http", "detail": f"HTTP {resp.status_code} for {url}"}


# ---------------------------------------------------------------------------
# 文字處理：分詞與中英混合比對
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_+.#-]+")


def tokenize(text: str) -> List[str]:
    tokens = []
    for tok in _TOKEN_RE.findall((text or "").lower()):
        tok = tok.strip(".-_+#")
        if tok:
            tokens.append(tok)
    # CJK 連續段落整段保留，供子字串比對
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text or ""):
        tokens.append(chunk)
    return tokens


def term_matches(term: str, haystack: str) -> bool:
    """英文以詞邊界比對，CJK 以子字串比對。"""
    term = (term or "").strip().lower()
    hay = (haystack or "").lower()
    if not term:
        return False
    if _CJK_RE.search(term):
        return term in hay
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", hay) is not None


def any_term_matches(terms: List[str], text: str) -> bool:
    return any(term_matches(t, text) for t in terms)


def ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def truncate_text(text: str, limit: int = 20000) -> str:
    return (text or "")[:limit]
