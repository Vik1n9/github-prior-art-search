import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .common import http_get, http_get_json, load_config

API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"


def effective_min_stars(input_data: Dict[str, Any]) -> int:
    floor = int(load_config()["defaults"]["enforced_min_stars"])
    return max(int(input_data.get("min_stars") or floor), floor)


def effective_max_age_days(input_data: Dict[str, Any]) -> int:
    configured = int(load_config()["defaults"]["last_commit_within_days"])
    return int(input_data.get("last_commit_within_days") or configured)


def ensure_star_filter(query: str, min_stars: int) -> str:
    if "stars:" in query:
        return query
    return f"{query} stars:>={min_stars}"


def search_repositories(query: str, token: str, min_stars: int
                        ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, str]]]:
    search = load_config()["search"]
    result = http_get_json(search["endpoint"], token=token, params={
        "q": ensure_star_filter(query, min_stars),
        "per_page": search["per_page"],
    })
    if result.error:
        return [], result.error
    items = result.data.get("items", []) if isinstance(result.data, dict) else []
    return items, None


def days_since(timestamp: Optional[str], now_ts: float) -> Optional[int]:
    if not timestamp:
        return None
    try:
        parsed = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return max((datetime.fromtimestamp(now_ts, tz=timezone.utc) - parsed).days, 0)


def _normalize_exclude(exclude_repos: List[str]) -> set:
    exclude = set()
    for entry in exclude_repos or []:
        normalized = entry.strip().lower().rstrip("/")
        exclude.add(normalized.replace("https://github.com/", ""))
    return exclude


def _discard_reason(repo: Dict[str, Any], min_stars: int, exclude: set,
                    max_age_days: int, now_ts: float) -> Optional[str]:
    if repo.get("stargazers_count", 0) < min_stars:
        return f"stars<{min_stars}"
    if repo.get("archived") is True:
        return "archived"
    if repo.get("disabled") is True:
        return "disabled"
    if repo.get("full_name", "").lower() in exclude:
        return "excluded"
    days = days_since(repo.get("pushed_at"), now_ts)
    if days is not None and days > max_age_days:
        return f"last_push>{max_age_days}d"
    return None


def filter_repositories(items: List[Dict[str, Any]], exclude_repos: List[str],
                        min_stars: int, max_age_days: int,
                        now_ts: Optional[float] = None
                        ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    now_ts = time.time() if now_ts is None else now_ts
    exclude = _normalize_exclude(exclude_repos)
    kept: List[Dict[str, Any]] = []
    discarded: List[Dict[str, str]] = []
    for repo in items:
        reason = _discard_reason(repo, min_stars, exclude, max_age_days, now_ts)
        if reason:
            discarded.append({"repository": repo.get("full_name", ""), "reason": reason})
        else:
            kept.append(repo)
    return kept, discarded


def merge_hits(hits: List[Tuple[str, Dict[str, Any]]]
               ) -> List[Tuple[Dict[str, Any], List[str]]]:
    merged: Dict[str, Tuple[Dict[str, Any], List[str]]] = {}
    for query, repo in hits:
        name = repo.get("full_name", "")
        if name not in merged:
            merged[name] = (repo, [query])
        elif query not in merged[name][1]:
            merged[name][1].append(query)
    return list(merged.values())


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def fetch_file_tree(full_name: str, branch: str, token: str
                    ) -> Tuple[List[str], bool, Optional[Dict[str, str]]]:
    url = f"{API_BASE}/repos/{full_name}/git/trees/{_quote(branch)}"
    result = http_get_json(url, token=token, params={"recursive": "1"})
    if result.error:
        return [], False, result.error
    data = result.data if isinstance(result.data, dict) else {}
    paths = [entry.get("path", "") for entry in data.get("tree", [])
             if entry.get("type") == "blob"]
    return paths, bool(data.get("truncated", False)), None


def fetch_readme(full_name: str, token: str
                 ) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    result = http_get(f"{API_BASE}/repos/{full_name}/readme", token=token,
                      accept="application/vnd.github.raw+json", not_found_ok=True)
    return result.data, result.error


def fetch_raw_file(full_name: str, branch: str, path: str, token: str
                   ) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    url = f"{RAW_BASE}/{full_name}/{_quote(branch)}/{urllib.parse.quote(path)}"
    result = http_get(url, token=token, accept="text/plain", not_found_ok=True)
    return result.data, result.error


def fetch_has_release_or_tag(full_name: str, token: str
                             ) -> Tuple[Optional[bool], Optional[Dict[str, str]]]:
    for endpoint in ("releases", "tags"):
        result = http_get_json(f"{API_BASE}/repos/{full_name}/{endpoint}",
                               token=token, params={"per_page": 1})
        if result.error:
            return None, result.error
        if isinstance(result.data, list) and result.data:
            return True, None
    return False, None
