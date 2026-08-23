# -*- coding: utf-8 -*-
"""GitHub 搜尋：輸入校驗、模板化查詢生成（§9）、API 查詢與本地二次過濾（§10）。"""
import itertools
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from common import (ScriptFailure, http_get_json, http_get_text, load_config,
                    tokenize)

REQUIRED_INPUTS = ("project_goal", "core_features")


# ---------------------------------------------------------------------------
# 輸入校驗（§6）
# ---------------------------------------------------------------------------

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
    if features is not None:
        if not isinstance(features, list) or not all(isinstance(x, str) for x in features):
            errors.append("core_features 必須是字串陣列")

    for list_field in ("tech_stack", "architecture_style", "license_preference",
                       "exclude_repos", "extra_keywords"):
        if list_field in data and data[list_field] is not None and \
                not isinstance(data[list_field], list):
            errors.append(f"{list_field} 必須是陣列")

    for int_field in ("max_candidates", "min_stars", "last_commit_within_days"):
        if data.get(int_field) is not None and not isinstance(data[int_field], int):
            errors.append(f"{int_field} 必須是整數")
    if isinstance(data.get("domain"), str) is False and data.get("domain") is not None:
        errors.append("domain 必須是字串")

    if errors:
        raise ScriptFailure("輸入校驗失敗：" + "；".join(errors), "invalid_input")
    return data


def effective_min_stars(input_data: Dict[str, Any]) -> int:
    """即使輸入低於 100，仍強制使用 100（§6 硬性規則）。"""
    floor = int(load_config()["defaults"]["enforced_min_stars"])
    raw = input_data.get("min_stars") or floor
    return max(int(raw), floor)


# ---------------------------------------------------------------------------
# 模板化查詢生成（§9）：模板定義於 templates/queries.yaml，避免與程式碼漂移
# ---------------------------------------------------------------------------

_QUERIES_PATH = Path(__file__).resolve().parent.parent / "templates" / "queries.yaml"
_QUERIES_CACHE: Optional[Dict[str, Any]] = None


def _queries_config() -> Dict[str, Any]:
    global _QUERIES_CACHE
    if _QUERIES_CACHE is None:
        with open(_QUERIES_PATH, "r", encoding="utf-8") as f:
            _QUERIES_CACHE = yaml.safe_load(f)
    return _QUERIES_CACHE


def _first_words(text: str, count: int = 3) -> str:
    tokens = tokenize(text)
    return " ".join(tokens[:count])


def _expand_template(template: str, spec: Dict[str, Any],
                     goal: str, features: List[str],
                     domain: str, stacks: List[str]) -> List[str]:
    """展開單一模板：多值佔位符採笛卡兒積；任一佔位符無值回傳空清單。"""
    tokens = re.findall(r"\{(\w+)\}", template)
    options: Dict[str, List[str]] = {}
    for token in tokens:
        if token == "goal_first_words":
            value = _first_words(goal, 3)
            if not value:
                return []
            options[token] = [value]
        elif token == "domain":
            if not domain:
                return []
            options[token] = [domain]
        elif token == "feature":
            limit = int(spec.get("feature_limit", 1))
            values = [w for w in (_first_words(f, 2) for f in features[:limit]) if w]
            if not values:
                return []
            options[token] = values
        elif token == "tech_stack":
            limit = int(spec.get("stack_limit", 1))
            values = [s for s in stacks[:limit] if s]
            if not values:
                return []
            options[token] = values
        else:
            return []

    rendered: List[str] = []
    for combo in itertools.product(*(options[t] for t in tokens)):
        query = template
        for token, value in zip(tokens, combo):
            query = query.replace("{" + token + "}", value)
        query = re.sub(r"\s+", " ", query).strip()
        if query:
            rendered.append(query)
    return rendered


def build_queries(input_data: Dict[str, Any]) -> List[str]:
    cfg = load_config()
    cap = int(cfg["search"].get("max_queries", 10))

    goal = (input_data.get("project_goal") or "").strip()
    features: List[str] = [f for f in input_data.get("core_features", []) if f]
    domain = (input_data.get("domain") or "").strip().replace("_", " ")
    stacks: List[str] = list(input_data.get("tech_stack") or [])
    extra: List[str] = list(input_data.get("extra_keywords") or [])

    queries: List[str] = []

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q.lower() not in {x.lower() for x in queries}:
            queries.append(q)

    for item in _queries_config()["templates"]:
        template = item["template"] if isinstance(item, dict) else str(item)
        spec = item if isinstance(item, dict) else {}
        for expanded in _expand_template(template, spec, goal, features, domain, stacks):
            add(expanded)

    for kw in extra:
        add(kw)

    return queries[:cap]


def ensure_star_filter(query: str, min_stars: int) -> str:
    if "stars:" in query:
        return query
    return f"{query} stars:>={min_stars}"


# ---------------------------------------------------------------------------
# 搜尋與過濾（§10）
# ---------------------------------------------------------------------------

class SearchState:
    """跨查詢共享的狀態：rate limit 是否已耗盡。"""

    def __init__(self) -> None:
        self.rate_limited = False


def search_repositories(query: str, token: str, min_stars: int,
                        state: Optional[SearchState] = None
                        ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, str]]]:
    cfg = load_config()["search"]
    params = {
        "q": ensure_star_filter(query, min_stars),
        "sort": cfg["sort"],
        "order": cfg["order"],
        "per_page": cfg["per_page"],
    }
    result = http_get_json(cfg["endpoint"], token=token, params=params)
    if result.error:
        if result.error["kind"] == "rate_limit" and state is not None:
            state.rate_limited = True
        return [], result.error
    items = result.data.get("items", []) if isinstance(result.data, dict) else []
    return items, None


def filter_repositories(items: List[Dict[str, Any]], exclude_repos: List[str],
                        now_ts: Optional[float] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """本地二次過濾（§10.2、§10.3）：星數/archived/disabled/黑名單/最後提交天數。"""
    from datetime import datetime, timezone

    cfg = load_config()
    rules = cfg["hard_rules"]
    floor = int(cfg["defaults"]["enforced_min_stars"])
    max_age_days = int(cfg["defaults"]["last_commit_within_days"])

    exclude = set()
    for entry in exclude_repos or []:
        exclude.add(entry.strip().lower())
        exclude.add(entry.strip().lower().rstrip("/").replace("https://github.com/", ""))

    kept: List[Dict[str, Any]] = []
    discarded: List[Dict[str, str]] = []

    for repo in items:
        full_name = repo.get("full_name", "")
        reason: Optional[str] = None

        if repo.get("stargazers_count", 0) < floor:
            reason = f"stars<{floor}"
        elif repo.get("archived") is True:
            reason = "archived"
        elif repo.get("disabled", False) is True:
            reason = "disabled"
        elif full_name.lower() in exclude or (repo.get("html_url") or "").lower() in exclude:
            reason = "excluded"
        else:
            pushed_at = repo.get("pushed_at")
            if pushed_at and max_age_days:
                try:
                    pushed_dt = datetime.strptime(
                        pushed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    now = datetime.fromtimestamp(now_ts or time.time(), tz=timezone.utc)
                    if (now - pushed_dt).days > max_age_days:
                        reason = f"last_commit>{max_age_days}d"
                except ValueError:
                    pass

        if reason:
            discarded.append({"repository": full_name, "reason": reason})
        else:
            kept.append(repo)

    return kept, discarded


def deduplicate(repos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for repo in repos:
        name = repo.get("full_name", "")
        if name not in seen:
            seen[name] = repo
            order.append(name)
        else:
            existing = seen[name]
            if repo.get("stargazers_count", 0) > existing.get("stargazers_count", 0):
                seen[name] = repo
    return [seen[n] for n in order]


def sort_initial(repos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        repos,
        key=lambda r: (r.get("stargazers_count", 0), r.get("pushed_at") or ""),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# 候選專案資料抓取（深度分析用）
# ---------------------------------------------------------------------------

RAW_BASE = "https://raw.githubusercontent.com"


def fetch_file_tree(full_name: str, default_branch: str, token: str
                    ) -> Tuple[List[str], bool, Optional[Dict[str, str]]]:
    """回傳 (檔案路徑清單, 是否被截斷, error)。"""
    url = f"https://api.github.com/repos/{full_name}/git/trees/{default_branch}"
    result = http_get_json(url, token=token, params={"recursive": "1"})
    if result.error:
        return [], False, result.error
    tree = result.data.get("tree", []) if isinstance(result.data, dict) else []
    paths = [entry.get("path", "") for entry in tree if entry.get("type") == "blob"]
    truncated = bool(result.data.get("truncated", False)) if isinstance(result.data, dict) else False
    return paths, truncated, None


README_NAMES = {"readme", "readme.md", "readme.txt", "readme.rst"}


def find_readme_path(paths: List[str]) -> Optional[str]:
    for path in paths:
        parts = path.split("/")
        if len(parts) == 1 and parts[0].lower() in README_NAMES:
            return path
    return None


def fetch_readme(full_name: str, default_branch: str, token: str) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    url = f"{RAW_BASE}/{full_name}/{default_branch}/README.md"
    text, err = http_get_text(url, token=token)
    if text is None and err is None:
        # 嘗試其他常見名稱
        for name in ("README.rst", "README.txt"):
            text, err = http_get_text(f"{RAW_BASE}/{full_name}/{default_branch}/{name}", token=token)
            if text is not None:
                break
    return text, err


def fetch_raw_file(full_name: str, default_branch: str, path: str, token: str
                   ) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    url = f"{RAW_BASE}/{full_name}/{default_branch}/{path}"
    return http_get_text(url, token=token)


def fetch_has_release(full_name: str, token: str) -> Tuple[bool, Optional[Dict[str, str]]]:
    url = f"https://api.github.com/repos/{full_name}/releases"
    result = http_get_json(url, token=token, params={"per_page": 1})
    if result.error:
        return False, result.error
    releases = result.data if isinstance(result.data, list) else []
    return len(releases) > 0, None
