from typing import Any, Dict, List, Optional, Tuple

from . import search_github as gh
from .caps import compute_cap, compute_risks
from .parse_dependencies import analyze_dependencies, dependency_risks
from .parse_license import analyze_license
from .score_candidates import (code_quality_score, documentation_score,
                               health_score, maintenance_score, reusability_score)


def _warning(kind: str, full_name: str, detail: str) -> Dict[str, str]:
    return {"type": kind, "repository": full_name, "detail": detail}


def _top_level_entries(paths: List[str], limit: int) -> List[str]:
    entries = sorted({p.split("/")[0] + ("/" if "/" in p else "") for p in paths})
    return entries[:limit]


def analyze_repository(repo: Dict[str, Any], token: str, now_ts: float,
                       config: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    full_name = repo["full_name"]
    branch = repo.get("default_branch") or "HEAD"
    analysis_cfg = config["analysis"]
    warnings: List[Dict[str, str]] = []
    data_gaps: List[str] = []

    paths, truncated, tree_error = gh.fetch_file_tree(full_name, branch, token)
    if tree_error:
        warnings.append(_warning("tree_fetch_failed", full_name, tree_error["detail"]))
        data_gaps.append("file_tree")
    if truncated:
        warnings.append(_warning("tree_truncated", full_name,
                                 "檔案樹過大被截斷，結構訊號可能不完整。"))

    readme_text, readme_error = gh.fetch_readme(full_name, token)
    if readme_error:
        warnings.append(_warning("readme_fetch_failed", full_name, readme_error["detail"]))
        data_gaps.append("readme")

    has_release, release_error = gh.fetch_has_release_or_tag(full_name, token)
    if release_error:
        warnings.append(_warning("release_check_failed", full_name,
                                 release_error["detail"]))
        data_gaps.append("releases")

    license_info = analyze_license(repo, paths, config)
    dependencies, dep_warnings = analyze_dependencies(
        paths, lambda path: gh.fetch_raw_file(full_name, branch, path, token))
    warnings.extend(_warning(w["type"], full_name, w["detail"]) for w in dep_warnings)
    if tree_error:
        dependencies["status"] = "unavailable"
    if dependencies["status"] in ("failed", "unavailable"):
        data_gaps.append("dependencies")

    days = gh.days_since(repo.get("pushed_at"), now_ts)
    maintenance = maintenance_score(days, config)
    documentation = documentation_score(readme_text, paths, config)
    quality = code_quality_score(paths, config)
    reusability = reusability_score(paths, dependencies, has_release, config)
    dep_risks = dependency_risks(dependencies, config)
    cap, cap_reasons = compute_cap(license_info, dep_risks, dependencies["status"],
                                   maintenance, config)

    excerpt_limit = int(analysis_cfg["readme_excerpt_chars"])
    facts = {
        "url": repo.get("html_url"),
        "description": repo.get("description") or "",
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "language": repo.get("language"),
        "topics": repo.get("topics") or [],
        "default_branch": branch,
        "pushed_at": repo.get("pushed_at"),
        "days_since_push": days,
        "license": license_info,
        "dependencies": dependencies,
        "scores": {
            "maintenance": maintenance,
            "code_quality": quality["score"],
            "documentation": documentation["score"],
            "reusability": reusability["score"],
        },
        "signals": {
            "code_quality": quality["signals"],
            "documentation": documentation["signals"],
            "reusability": reusability["signals"],
        },
        "risks": compute_risks(license_info, dep_risks, dependencies["status"],
                               maintenance, days, config),
        "cap": cap,
        "cap_reasons": cap_reasons,
        "evidence": {
            "readme_excerpt": (readme_text or "")[:excerpt_limit],
            "readme_truncated": len(readme_text or "") > excerpt_limit,
            "top_level_entries": _top_level_entries(
                paths, int(analysis_cfg["top_level_entries_limit"])),
            "file_count": len(paths),
        },
        "data_gaps": data_gaps,
        "warnings": warnings,
    }
    facts["scores"]["health"] = health_score(facts["scores"], config)
    return facts, readme_text
