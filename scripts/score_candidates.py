# -*- coding: utf-8 -*-
"""評分模型（§13）：所有分數由腳本計算，模型不得修改。"""
from typing import Any, Dict, List, Optional

from common import load_config, term_matches, tokenize, truncate_text


# ---------------------------------------------------------------------------
# §13.2 相關度
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "for", "and", "the", "with", "from", "into", "that", "this",
    "system", "based", "using",
}


def _feature_words(feature: str) -> List[str]:
    words = [w for w in tokenize(feature)
             if w not in _STOPWORDS and len(w) > 1]
    return words or [feature.strip().lower()]


def _input_term_sets(input_data: Dict[str, Any]) -> Dict[str, List[str]]:
    def clean_list(value: Any) -> List[str]:
        return [str(v).strip().lower() for v in (value or []) if str(v).strip()]

    goal_words = [w for w in tokenize(input_data.get("project_goal") or "")
                  if w not in _STOPWORDS]
    domain_words = [w for w in tokenize(
        str(input_data.get("domain") or "").replace("_", " "))
        if w not in _STOPWORDS]

    features = clean_list(input_data.get("core_features"))
    feature_word_lists = [_feature_words(f) for f in features]
    return {
        "goal": goal_words,
        "features": features,
        "feature_words": [w for lst in feature_word_lists for w in lst],
        "domain": domain_words,
        "architecture": clean_list(input_data.get("architecture_style")),
        "stacks": clean_list(input_data.get("tech_stack")),
    }


def _ratio(matches: int, total: int) -> float:
    return 0.0 if total == 0 else min(matches / total, 1.0)


def relevance_score(input_data: Dict[str, Any], repo: Dict[str, Any],
                    readme_text: Optional[str], config: Optional[Dict[str, Any]] = None
                    ) -> Dict[str, float]:
    cfg = config or load_config()
    weights = cfg["relevance_signals"]
    terms = _input_term_sets(input_data)

    name = f"{repo.get('name', '')} {repo.get('full_name', '')}".strip()
    description = repo.get("description") or ""
    topics_list = [str(t) for t in (repo.get("topics") or [])]
    topics_text = " ".join(topics_list)
    language = repo.get("language") or ""
    readme = truncate_text(readme_text or "", 30000)

    # 名稱比對僅取前幾個核心詞，避免長目標稀釋（repo 名稱通常很短）
    name_terms = (terms["goal"][:3] + terms["domain"])[:5]
    desc_terms = (terms["goal"][:5] + terms["domain"] + terms["feature_words"])[:10]

    name_hits = sum(1 for t in name_terms if term_matches(t, name))
    desc_hits = sum(1 for t in desc_terms if term_matches(t, description))
    topic_hits = sum(1 for t in terms["domain"] + terms["architecture"]
                     if any(term_matches(t, topic) for topic in topics_list))
    readme_hits = 0
    if weights.get("enable_readme_match", True) and readme:
        readme_hits = sum(1 for t in desc_terms if term_matches(t, readme))

    # 功能覆蓋：功能詞組出現在 名稱/描述/topics/README 任一即算命中
    haystacks = [name, description, topics_text, readme]
    feature_total = max(len(terms["features"]), 1)
    feature_hits = sum(
        1 for feature in terms["features"]
        if any(any(term_matches(w, h) for w in _feature_words(feature))
               for h in haystacks))

    stack_hay = f"{language} {topics_text} {description}"
    stack_hits = sum(1 for s in terms["stacks"] if term_matches(s, stack_hay))

    return {
        "name_match": round(_ratio(name_hits, max(len(name_terms), 1)) * weights["name_match"], 1),
        "description_match": round(
            _ratio(desc_hits, max(len(desc_terms), 1)) * weights["description_match"], 1),
        "topics_match": round(_ratio(topic_hits,
                                     max(len(terms["domain"]) + len(terms["architecture"]), 1))
                              * weights["topics_match"], 1),
        "readme_match": round(_ratio(readme_hits, max(len(desc_terms), 1))
                              * weights["readme_match"], 1),
        "feature_match": round(_ratio(feature_hits, feature_total) * weights["feature_match"], 1),
        "tech_stack_match": round(_ratio(stack_hits, max(len(terms["stacks"]), 1))
                                  * weights["tech_stack_match"], 1),
    }


# ---------------------------------------------------------------------------
# §13.3 維護活躍度
# ---------------------------------------------------------------------------

def days_since(pushed_at: str, now_ts: Optional[float] = None) -> Optional[int]:
    from datetime import datetime, timezone
    if not pushed_at:
        return None
    try:
        # GitHub API 回傳 ISO 8601（如 2026-08-01T00:00:00Z），
        # Python 3.9 的 fromisoformat 不認得 Z 後綴，先轉為 +00:00。
        pushed_dt = datetime.fromisoformat(str(pushed_at).strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    now = datetime.fromtimestamp(now_ts, tz=timezone.utc) \
        if now_ts else datetime.now(timezone.utc)
    if pushed_dt.tzinfo is None:
        pushed_dt = pushed_dt.replace(tzinfo=timezone.utc)
    return max((now - pushed_dt).days, 0)


def maintenance_score(pushed_at: str, now_ts: Optional[float] = None,
                      config: Optional[Dict[str, Any]] = None) -> int:
    cfg = config or load_config()
    days = days_since(pushed_at, now_ts)
    if days is None:
        return 0
    for bucket in cfg["maintenance_buckets"]:
        if "max_days" in bucket and days <= bucket["max_days"]:
            return int(bucket["score"])
    last = cfg["maintenance_buckets"][-1]
    return int(last["score"])


# ---------------------------------------------------------------------------
# §13.4 文件品質
# ---------------------------------------------------------------------------

_INSTALL_RE = r"install|安裝|getting[ _-]?started|quick[ _-]?start|pip install|npm install|yarn add"
_USAGE_RE = r"usage|使用|example|範例|demo|getting[ _-]?started|how to use"


def documentation_score(readme_text: Optional[str], paths: List[str],
                        config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or load_config()
    w = cfg["documentation_signals"]

    top_dirs = {p.split("/")[0].lower() for p in paths if "/" in p}
    has_docs = bool(top_dirs & {"docs", "doc", "documentation"})
    has_examples = bool(top_dirs & {"examples", "example", "samples", "sample", "demos"})

    readme = truncate_text((readme_text or "").lower(), 30000)
    signals = {
        "has_readme": bool(readme),
        "readme_has_install": bool(readme and __import__("re").search(_INSTALL_RE, readme)),
        "readme_has_usage": bool(readme and __import__("re").search(_USAGE_RE, readme)),
        "has_docs_folder": has_docs,
        "has_examples_folder": has_examples,
    }
    score = sum(w[key] for key, hit in signals.items() if hit)
    return {"score": score, "signals": signals}


# ---------------------------------------------------------------------------
# §13.5 程式碼品質訊號
# ---------------------------------------------------------------------------

_TEST_HINTS = ("test", "tests", "spec", "__tests__")
_CI_PATHS = (".github/workflows", ".gitlab-ci.yml", ".circleci", "jenkinsfile",
             "azure-pipelines.yml", ".travis.yml")
_LINT_FILES = (".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
               "eslint.config.js", "eslint.config.mjs", ".flake8", "ruff.toml",
               ".ruff.toml", ".pylintrc", ".pre-commit-config.yaml", ".stylelintrc",
               ".rubocop.yml", "biome.json", ".golangci.yml")
_SRC_DIRS = {"src", "lib", "app", "pkg", "cmd", "source", "packages"}


def code_quality_score(paths: List[str], has_release: bool,
                       config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or load_config()
    w = cfg["code_quality_signals"]

    lowered = [p.lower() for p in paths]
    top_names = {p.split("/")[0].lower() for p in paths}
    top_files = {p for p in lowered if "/" not in p}

    segments = {seg.lower() for p in paths for seg in p.split("/") if seg}
    has_tests = bool(segments & set(_TEST_HINTS)) or \
        any(seg.startswith(("test_", "spec_")) or seg.endswith(("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts"))
            for seg in segments)
    has_ci = any(any(p.startswith(ci) or p == ci for ci in _CI_PATHS) for p in lowered)
    has_lint = bool(top_files & {f.lower() for f in _LINT_FILES})
    has_src = bool(top_names & _SRC_DIRS)

    signals = {
        "has_tests": bool(has_tests),
        "has_ci": has_ci,
        "has_lint_config": has_lint,
        "has_release": bool(has_release),
        "has_src_structure": has_src,
    }
    score = sum(w[key] for key, hit in signals.items() if hit)
    return {"score": score, "signals": signals}


# ---------------------------------------------------------------------------
# reusability（規格未定義細節，採 RULES.md 所載訊號，滿分 20）
# ---------------------------------------------------------------------------

_PACKAGED_FILES = {"dockerfile", "package.json", "setup.py", "pyproject.toml",
                   "cargo.toml", "go.mod", "pom.xml"}


def reusability_score(paths: List[str], dependency_summary: Optional[Dict[str, Any]],
                      has_release: bool, config: Optional[Dict[str, Any]] = None
                      ) -> Dict[str, Any]:
    cfg = config or load_config()
    w = cfg["reusability_signals"]
    top_files = {p.split("/")[0].lower() for p in paths if "/" not in p}
    top_dirs = {p.split("/")[0].lower() for p in paths if "/" in p}

    lockfile_present = bool(dependency_summary and dependency_summary.get("lockfile_present"))
    total_deps = int(dependency_summary.get("total_count", 0)) if dependency_summary else 0
    if total_deps <= 100:
        moderate = w["moderate_dependency_count"]
    elif total_deps >= 200:
        moderate = 0
    else:
        ratio = (200 - total_deps) / 100.0
        moderate = round(w["moderate_dependency_count"] * ratio, 1)

    signals = {
        "lockfile_present": lockfile_present,
        "has_release_or_tags": has_release,
        "moderate_dependency_count": moderate,
        "has_examples": bool(top_dirs & {"examples", "example", "samples", "sample"}),
        "packaged_project": bool(top_files & _PACKAGED_FILES),
    }
    score = sum(v for v in [
        w["lockfile_present"] if signals["lockfile_present"] else 0,
        w["has_release_or_tags"] if signals["has_release_or_tags"] else 0,
        moderate,
        w["has_examples"] if signals["has_examples"] else 0,
        w["packaged_project"] if signals["packaged_project"] else 0,
    ])
    return {"score": score, "signals": signals}


# ---------------------------------------------------------------------------
# 彙總（§13.1 加權）
# ---------------------------------------------------------------------------

def calculate_scores(input_data: Dict[str, Any], repo: Dict[str, Any],
                     license_info: Dict[str, Any], dependency_summary: Optional[Dict[str, Any]],
                     readme_text: Optional[str], paths: List[str], has_release: bool,
                     now_ts: Optional[float] = None,
                     config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or load_config()
    weights = cfg["scoring_weights"]

    rel = relevance_score(input_data, repo, readme_text, cfg)
    # 六個訊號內部權重總和為 100，故 relevance 子分數本身即為 0–100
    relevance = min(round(sum(rel.values()), 1), 100)
    reuse = reusability_score(paths, dependency_summary, has_release, cfg)
    maintenance = maintenance_score(repo.get("pushed_at", ""), now_ts, cfg)
    quality = code_quality_score(paths, has_release, cfg)
    docs = documentation_score(readme_text, paths, cfg)
    license_fit = int(license_info["license_fit_score"])

    total = round(
        (relevance * weights["relevance"]
         + reuse["score"] * weights["reusability"]
         + maintenance * weights["maintenance_activity"]
         + quality["score"] * weights["code_quality"]
         + docs["score"] * weights["documentation"]
         + license_fit * weights["license_fit"]) / 100.0, 1)

    return {
        "relevance": relevance,
        "reusability": reuse["score"],
        "maintenance_activity": maintenance,
        "code_quality": quality["score"],
        "documentation": docs["score"],
        "license_fit": license_fit,
        "total": min(total, 100.0),
        "_detail": {
            "relevance_signals": rel,
            "reusability_signals": reuse["signals"],
            "documentation_signals": docs["signals"],
            "code_quality_signals": quality["signals"],
        },
    }


# ---------------------------------------------------------------------------
# 風險彙總（§11.3、§12.3、§14 avoid_due_to_risk）
# ---------------------------------------------------------------------------

def compute_risks(license_info: Dict[str, Any], dependency_risk_list: List[Dict[str, str]],
                  metadata: Dict[str, Any], config: Optional[Dict[str, Any]] = None
                  ) -> List[Dict[str, str]]:
    cfg = config or load_config()
    risks: List[Dict[str, str]] = []

    if license_info["category"] == "unknown":
        risks.append({
            "type": "license_risk",
            "level": "high",
            "detail": "無法識別授權條款，僅能參考，不得直接重用程式碼。",
        })
    elif license_info["category"] == "high_risk":
        risks.append({
            "type": "license_risk",
            "level": "high",
            "detail": f"授權 {license_info['spdx_id']} 屬高風險類別，避免直接重用。",
        })
    elif license_info["category"] == "review_required":
        risks.append({
            "type": "license_risk",
            "level": "medium",
            "detail": f"授權 {license_info['spdx_id']} 需人工法律審查。",
        })

    risks.extend(dependency_risk_list)

    if metadata.get("archived") is True:
        risks.append({"type": "maintenance_risk", "level": "high",
                      "detail": "專案已封存。"})

    days = days_since(metadata.get("pushed_at", ""))
    if days is not None and days > int(cfg["defaults"]["last_commit_within_days"]):
        risks.append({
            "type": "maintenance_risk",
            "level": "medium",
            "detail": f"最後提交已超過 {days} 天。",
        })

    level_rank = {"low": 0, "medium": 1, "high": 2}
    risks.sort(key=lambda r: level_rank.get(r.get("level", "low"), 0), reverse=True)
    return risks


def overall_dependency_risk(risks: List[Dict[str, str]]) -> str:
    """取依賴類風險的最高等級；無風險視為 low。"""
    rank = {"low": 0, "medium": 1, "high": 2}
    worst = "low"
    for risk in risks:
        if risk.get("type") == "dependency_risk" and rank.get(risk.get("level"), 0) > rank[worst]:
            worst = risk["level"]
    return worst
