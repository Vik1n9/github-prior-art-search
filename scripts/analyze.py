from typing import Any, Dict, List, Optional

from . import search_github as gh
from .build_recommendation import candidate_summary, decide_reuse
from .parse_dependencies import (analyze_dependencies, dependency_risks,
                                 empty_dependency_summary)
from .parse_license import analyze_license
from .score_candidates import calculate_scores, compute_risks

README_FALLBACKS = ("README.md", "README.rst", "README.txt")


def _fetch_readme(full_name: str, branch: str, token: str, paths: List[str],
                  tree_available: bool) -> Optional[str]:
    if tree_available:
        path = gh.find_readme_path(paths)
        if not path:
            return None
        return gh.fetch_raw_file(full_name, branch, path, token)[0]

    for name in README_FALLBACKS:
        text, _error = gh.fetch_raw_file(full_name, branch, name, token)
        if text is not None:
            return text
    return None


def _collect_warnings(full_name: str, tree_error: Optional[Dict[str, str]],
                      truncated: bool, release_error: Optional[Dict[str, str]],
                      license_info: Dict[str, Any]) -> List[Dict[str, str]]:
    warnings: List[Dict[str, str]] = []
    if tree_error:
        warnings.append({"type": "tree_fetch_failed",
                         "detail": f"{full_name}: {tree_error['detail']}"})
    if truncated:
        warnings.append({"type": "tree_truncated",
                         "detail": f"{full_name}: 檔案樹過大被截斷，訊號可能不完整。"})
    if release_error:
        warnings.append({"type": "release_check_failed",
                         "detail": f"{full_name}: {release_error['detail']}"})
    if license_info["source"] == "license_file_unparsed":
        warnings.append({"type": "license_unparsed",
                         "detail": f"{full_name}: 存在授權檔但無法識別 SPDX，標記 unknown。"})
    return warnings


def analyze_candidate(repo: Dict[str, Any], input_data: Dict[str, Any], token: str,
                      now_ts: float, max_age_days: int,
                      config: Dict[str, Any]) -> Dict[str, Any]:
    full_name = repo["full_name"]
    branch = repo.get("default_branch") or "HEAD"

    paths, truncated, tree_error = gh.fetch_file_tree(full_name, branch, token)
    if tree_error:
        paths, truncated = [], False

    readme_text = _fetch_readme(full_name, branch, token, paths, tree_error is None)
    license_info = analyze_license(repo, paths, config)

    dependency_summary, dependency_warnings = analyze_dependencies(
        paths, lambda path: gh.fetch_raw_file(full_name, branch, path, token)[0])
    has_release, release_error = gh.fetch_has_release(full_name, token)

    scores = calculate_scores(input_data, repo, license_info, dependency_summary,
                              readme_text, paths, bool(has_release),
                              now_ts=now_ts, config=config)
    risks = compute_risks(license_info,
                          dependency_risks(dependency_summary, config)
                          if dependency_summary else [],
                          repo, max_age_days, now_ts)

    candidate = {
        "repository": full_name,
        "url": repo.get("html_url"),
        "description": repo.get("description") or "",
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "language": repo.get("language"),
        "license": {key: license_info[key] for key in
                    ("spdx_id", "category", "source", "action", "risk_level")},
        "pushed_at": repo.get("pushed_at"),
        "archived": repo.get("archived", False),
        "topics": repo.get("topics") or [],
        "scores": {k: v for k, v in scores.items() if k != "_detail"},
        "score_detail": scores["_detail"],
        "reuse_decision": decide_reuse(scores, risks, repo, config),
        "dependencies": dependency_summary or {
            **empty_dependency_summary(), "parsing_failed": True},
        "risks": risks,
    }
    candidate["summary"] = candidate_summary(candidate)

    warnings = list(dependency_warnings) + _collect_warnings(
        full_name, tree_error, truncated, release_error, license_info)
    return {"candidate": candidate, "warnings": warnings}
