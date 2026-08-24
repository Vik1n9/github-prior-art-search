import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .common import ScriptFailure, http_get_json, http_get_text, load_config

REQUIRED_INPUTS = ("project_goal", "core_features")
LIST_INPUTS = ("tech_stack", "architecture_style", "exclude_repos", "extra_keywords")
INT_INPUTS = ("max_candidates", "min_stars", "last_commit_within_days")

RAW_BASE = "https://raw.githubusercontent.com"
README_NAMES = {"readme", "readme.md", "readme.txt", "readme.rst"}
NO_KEYWORDS_WARNING = {
    "type": "no_extra_keywords",
    "detail": "輸入未提供 extra_keywords，僅以 project_goal 原文查詢。"
              "GitHub 語料以英文為主，非英文的 project_goal 命中率極低，"
              "請補上英文關鍵字以取得有意義的結果。",
}


def validate_input(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ScriptFailure("輸入必須是 JSON 物件", "invalid_input")

    errors: List[str] = []
    for key in REQUIRED_INPUTS:
        if key not in data or data[key] in (None, "", []):
            errors.append(f"缺少必要欄位: {key}")

    if not isinstance(data.get("project_goal", ""), str):
        errors.append("project_goal 必須是字串")

    features = data.get("core_features")
    if features is not None and (not isinstance(features, list)
                                 or not all(isinstance(x, str) for x in features)):
        errors.append("core_features 必須是字串陣列")

    for field in LIST_INPUTS:
        if data.get(field) is not None and not isinstance(data[field], list):
            errors.append(f"{field} 必須是陣列")

    for field in INT_INPUTS:
        if data.get(field) is not None and not isinstance(data[field], int):
            errors.append(f"{field} 必須是整數")

    if data.get("domain") is not None and not isinstance(data["domain"], str):
        errors.append("domain 必須是字串")

    if errors:
        raise ScriptFailure("輸入校驗失敗：" + "；".join(errors), "invalid_input")
    return data


def effective_min_stars(input_data: Dict[str, Any]) -> int:
    floor = int(load_config()["defaults"]["enforced_min_stars"])
    return max(int(input_data.get("min_stars") or floor), floor)


def effective_max_age_days(input_data: Dict[str, Any]) -> int:
    configured = int(load_config()["defaults"]["last_commit_within_days"])
    return int(input_data.get("last_commit_within_days") or configured)


def _normalize(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def build_queries(input_data: Dict[str, Any]
                  ) -> Tuple[List[str], List[Dict[str, str]]]:
    queries: List[str] = []
    seen: set = set()

    def add(query: str) -> None:
        query = _normalize(str(query))
        if query and query.lower() not in seen:
            seen.add(query.lower())
            queries.append(query)

    for keyword in input_data.get("extra_keywords") or []:
        add(keyword)

    warnings: List[Dict[str, str]] = []
    if not queries:
        add(input_data.get("project_goal") or "")
        warnings.append(dict(NO_KEYWORDS_WARNING))

    return queries[:int(load_config()["search"]["max_queries"])], warnings


def ensure_star_filter(query: str, min_stars: int) -> str:
    if "stars:" in query:
        return query
    return f"{query} stars:>={min_stars}"


def search_repositories(query: str, token: str, min_stars: int
                        ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, str]]]:
    search = load_config()["search"]
    result = http_get_json(search["endpoint"], token=token, params={
        "q": ensure_star_filter(query, min_stars),
        "sort": search["sort"],
        "order": search["order"],
        "per_page": search["per_page"],
    })
    if result.error:
        return [], result.error
    items = result.data.get("items", []) if isinstance(result.data, dict) else []
    return items, None


def _days_since_push(pushed_at: str, now_ts: float) -> Optional[int]:
    try:
        pushed = datetime.strptime(pushed_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.fromtimestamp(now_ts, tz=timezone.utc) - pushed).days


def _discard_reason(repo: Dict[str, Any], floor: int, exclude: set,
                    max_age_days: int, now_ts: float) -> Optional[str]:
    if repo.get("stargazers_count", 0) < floor:
        return f"stars<{floor}"
    if repo.get("archived") is True:
        return "archived"
    if repo.get("disabled", False) is True:
        return "disabled"
    if repo.get("full_name", "").lower() in exclude or \
            (repo.get("html_url") or "").lower() in exclude:
        return "excluded"
    pushed_at = repo.get("pushed_at")
    if pushed_at and max_age_days:
        days = _days_since_push(pushed_at, now_ts)
        if days is not None and days > max_age_days:
            return f"last_commit>{max_age_days}d"
    return None


def filter_repositories(items: List[Dict[str, Any]], exclude_repos: List[str],
                        max_age_days: Optional[int] = None,
                        now_ts: Optional[float] = None
                        ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    config = load_config()
    floor = int(config["defaults"]["enforced_min_stars"])
    if max_age_days is None:
        max_age_days = int(config["defaults"]["last_commit_within_days"])
    if now_ts is None:
        now_ts = time.time()

    exclude = set()
    for entry in exclude_repos or []:
        normalized = entry.strip().lower()
        exclude.add(normalized)
        exclude.add(normalized.rstrip("/").replace("https://github.com/", ""))

    kept: List[Dict[str, Any]] = []
    discarded: List[Dict[str, str]] = []
    for repo in items:
        reason = _discard_reason(repo, floor, exclude, max_age_days, now_ts)
        if reason:
            discarded.append({"repository": repo.get("full_name", ""), "reason": reason})
        else:
            kept.append(repo)
    return kept, discarded


def deduplicate(repos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for repo in repos:
        name = repo.get("full_name", "")
        if name not in best:
            best[name] = repo
            order.append(name)
        elif repo.get("stargazers_count", 0) > best[name].get("stargazers_count", 0):
            best[name] = repo
    return [best[name] for name in order]


def sort_initial(repos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(repos, key=lambda r: (r.get("stargazers_count", 0),
                                        r.get("pushed_at") or ""), reverse=True)


def fetch_file_tree(full_name: str, default_branch: str, token: str
                    ) -> Tuple[List[str], bool, Optional[Dict[str, str]]]:
    url = f"https://api.github.com/repos/{full_name}/git/trees/{default_branch}"
    result = http_get_json(url, token=token, params={"recursive": "1"})
    if result.error:
        return [], False, result.error
    data = result.data if isinstance(result.data, dict) else {}
    paths = [entry.get("path", "") for entry in data.get("tree", [])
             if entry.get("type") == "blob"]
    return paths, bool(data.get("truncated", False)), None


def find_readme_path(paths: List[str]) -> Optional[str]:
    for path in paths:
        if "/" not in path and path.lower() in README_NAMES:
            return path
    return None


def fetch_raw_file(full_name: str, default_branch: str, path: str, token: str
                   ) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    return http_get_text(f"{RAW_BASE}/{full_name}/{default_branch}/{path}", token=token)


def fetch_has_release(full_name: str, token: str
                      ) -> Tuple[bool, Optional[Dict[str, str]]]:
    url = f"https://api.github.com/repos/{full_name}/releases"
    result = http_get_json(url, token=token, params={"per_page": 1})
    if result.error:
        return False, result.error
    return bool(result.data if isinstance(result.data, list) else []), None
