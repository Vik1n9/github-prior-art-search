import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .common import load_config, term_matches, tokenize, truncate_text

STOPWORDS = {"for", "and", "the", "with", "from", "into", "that", "this",
             "system", "based", "using"}

INSTALL_RE = re.compile(
    r"install|安裝|getting[ _-]?started|quick[ _-]?start|pip install|npm install|yarn add")
USAGE_RE = re.compile(r"usage|使用|example|範例|demo|getting[ _-]?started|how to use")

TEST_SEGMENTS = {"test", "tests", "spec", "__tests__"}
TEST_FILE_PREFIXES = ("test_", "spec_")
TEST_FILE_SUFFIXES = ("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts")
CI_PATHS = (".github/workflows", ".gitlab-ci.yml", ".circleci", "jenkinsfile",
            "azure-pipelines.yml", ".travis.yml")
LINT_FILES = {".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
              "eslint.config.js", "eslint.config.mjs", ".flake8", "ruff.toml",
              ".ruff.toml", ".pylintrc", ".pre-commit-config.yaml", ".stylelintrc",
              ".rubocop.yml", "biome.json", ".golangci.yml"}
SRC_DIRS = {"src", "lib", "app", "pkg", "cmd", "source", "packages"}
EXAMPLE_DIRS = {"examples", "example", "samples", "sample"}
DOC_DIRS = {"docs", "doc", "documentation"}
PACKAGED_FILES = {"dockerfile", "package.json", "setup.py", "pyproject.toml",
                  "cargo.toml", "go.mod", "pom.xml"}

RISK_RANK = {"low": 0, "medium": 1, "high": 2}


def _feature_words(feature: str) -> List[str]:
    words = [w for w in tokenize(feature) if w not in STOPWORDS and len(w) > 1]
    return words or [feature.strip().lower()]


def _input_term_sets(input_data: Dict[str, Any]) -> Dict[str, List[str]]:
    def clean_list(value: Any) -> List[str]:
        return [str(v).strip().lower() for v in (value or []) if str(v).strip()]

    features = clean_list(input_data.get("core_features"))
    return {
        "goal": [w for w in tokenize(input_data.get("project_goal") or "")
                 if w not in STOPWORDS],
        "features": features,
        "feature_words": [w for f in features for w in _feature_words(f)],
        "domain": [w for w in tokenize(
            str(input_data.get("domain") or "").replace("_", " "))
            if w not in STOPWORDS],
        "architecture": clean_list(input_data.get("architecture_style")),
        "stacks": clean_list(input_data.get("tech_stack")),
    }


def _ratio(matches: int, total: int) -> float:
    return 0.0 if total == 0 else min(matches / total, 1.0)


def _weighted(matches: int, total: int, weight: float) -> float:
    return round(_ratio(matches, max(total, 1)) * weight, 1)


def relevance_score(input_data: Dict[str, Any], repo: Dict[str, Any],
                    readme_text: Optional[str],
                    config: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    weights = (config or load_config())["relevance_signals"]
    terms = _input_term_sets(input_data)

    name = f"{repo.get('name', '')} {repo.get('full_name', '')}".strip()
    description = repo.get("description") or ""
    topics = [str(t) for t in (repo.get("topics") or [])]
    topics_text = " ".join(topics)
    readme = truncate_text(readme_text)

    name_terms = (terms["goal"][:3] + terms["domain"])[:5]
    description_terms = (terms["goal"][:5] + terms["domain"]
                         + terms["feature_words"])[:10]
    topic_terms = terms["domain"] + terms["architecture"]

    readme_hits = 0
    if weights.get("enable_readme_match", True) and readme:
        readme_hits = sum(1 for t in description_terms if term_matches(t, readme))

    haystacks = [name, description, topics_text, readme]
    feature_hits = sum(1 for feature in terms["features"]
                       if any(term_matches(word, haystack)
                              for word in _feature_words(feature)
                              for haystack in haystacks))

    stack_haystack = f"{repo.get('language') or ''} {topics_text} {description}"

    return {
        "name_match": _weighted(
            sum(1 for t in name_terms if term_matches(t, name)),
            len(name_terms), weights["name_match"]),
        "description_match": _weighted(
            sum(1 for t in description_terms if term_matches(t, description)),
            len(description_terms), weights["description_match"]),
        "topics_match": _weighted(
            sum(1 for t in topic_terms
                if any(term_matches(t, topic) for topic in topics)),
            len(topic_terms), weights["topics_match"]),
        "readme_match": _weighted(readme_hits, len(description_terms),
                                  weights["readme_match"]),
        "feature_match": _weighted(feature_hits, len(terms["features"]),
                                   weights["feature_match"]),
        "tech_stack_match": _weighted(
            sum(1 for s in terms["stacks"] if term_matches(s, stack_haystack)),
            len(terms["stacks"]), weights["tech_stack_match"]),
    }


def _parse_github_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def days_since(pushed_at: str, now_ts: Optional[float] = None) -> Optional[int]:
    pushed = _parse_github_timestamp(pushed_at)
    if pushed is None:
        return None
    now = datetime.fromtimestamp(now_ts, tz=timezone.utc) if now_ts \
        else datetime.now(timezone.utc)
    return max((now - pushed).days, 0)


def maintenance_score(pushed_at: str, now_ts: Optional[float] = None,
                      config: Optional[Dict[str, Any]] = None) -> int:
    buckets = (config or load_config())["maintenance_buckets"]
    days = days_since(pushed_at, now_ts)
    if days is None:
        return 0
    for bucket in buckets:
        if "max_days" in bucket and days <= bucket["max_days"]:
            return int(bucket["score"])
    return int(buckets[-1]["score"])


def _top_level_dirs(paths: List[str]) -> set:
    return {path.split("/")[0].lower() for path in paths if "/" in path}


def _top_level_files(paths: List[str]) -> set:
    return {path.lower() for path in paths if "/" not in path}


def _scored_signals(signals: Dict[str, bool], weights: Dict[str, Any]) -> int:
    return sum(weights[key] for key, hit in signals.items() if hit)


def documentation_score(readme_text: Optional[str], paths: List[str],
                        config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    weights = (config or load_config())["documentation_signals"]
    top_dirs = _top_level_dirs(paths)
    readme = truncate_text((readme_text or "").lower())

    signals = {
        "has_readme": bool(readme),
        "readme_has_install": bool(readme and INSTALL_RE.search(readme)),
        "readme_has_usage": bool(readme and USAGE_RE.search(readme)),
        "has_docs_folder": bool(top_dirs & DOC_DIRS),
        "has_examples_folder": bool(top_dirs & (EXAMPLE_DIRS | {"demos"})),
    }
    return {"score": _scored_signals(signals, weights), "signals": signals}


def _has_tests(paths: List[str]) -> bool:
    segments = {segment.lower() for path in paths
                for segment in path.split("/") if segment}
    if segments & TEST_SEGMENTS:
        return True
    return any(segment.startswith(TEST_FILE_PREFIXES)
               or segment.endswith(TEST_FILE_SUFFIXES) for segment in segments)


def code_quality_score(paths: List[str], has_release: bool,
                       config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    weights = (config or load_config())["code_quality_signals"]
    lowered = [path.lower() for path in paths]

    signals = {
        "has_tests": _has_tests(paths),
        "has_ci": any(path.startswith(CI_PATHS) for path in lowered),
        "has_lint_config": bool(_top_level_files(paths) & LINT_FILES),
        "has_release": bool(has_release),
        "has_src_structure": bool(
            {path.split("/")[0].lower() for path in paths} & SRC_DIRS),
    }
    return {"score": _scored_signals(signals, weights), "signals": signals}


def _moderate_dependency_points(total_deps: int, full_points: float) -> float:
    if total_deps <= 100:
        return full_points
    if total_deps >= 200:
        return 0
    return round(full_points * (200 - total_deps) / 100.0, 1)


def reusability_score(paths: List[str], dependency_summary: Optional[Dict[str, Any]],
                      has_release: bool, config: Optional[Dict[str, Any]] = None
                      ) -> Dict[str, Any]:
    weights = (config or load_config())["reusability_signals"]
    summary = dependency_summary or {}
    moderate = _moderate_dependency_points(int(summary.get("total_count", 0)),
                                           weights["moderate_dependency_count"])

    signals = {
        "lockfile_present": bool(summary.get("lockfile_present")),
        "has_release_or_tags": bool(has_release),
        "moderate_dependency_count": moderate,
        "has_examples": bool(_top_level_dirs(paths) & EXAMPLE_DIRS),
        "packaged_project": bool(_top_level_files(paths) & PACKAGED_FILES),
    }
    score = moderate + sum(
        weights[key] for key in ("lockfile_present", "has_release_or_tags",
                                 "has_examples", "packaged_project")
        if signals[key])
    return {"score": score, "signals": signals}


def calculate_scores(input_data: Dict[str, Any], repo: Dict[str, Any],
                     license_info: Dict[str, Any],
                     dependency_summary: Optional[Dict[str, Any]],
                     readme_text: Optional[str], paths: List[str], has_release: bool,
                     now_ts: Optional[float] = None,
                     config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = config or load_config()
    weights = config["scoring_weights"]

    relevance_signals = relevance_score(input_data, repo, readme_text, config)
    relevance = min(round(sum(relevance_signals.values()), 1), 100)
    reusability = reusability_score(paths, dependency_summary, has_release, config)
    maintenance = maintenance_score(repo.get("pushed_at", ""), now_ts, config)
    quality = code_quality_score(paths, has_release, config)
    documentation = documentation_score(readme_text, paths, config)
    license_fit = int(license_info["license_fit_score"])

    total = round((relevance * weights["relevance"]
                   + reusability["score"] * weights["reusability"]
                   + maintenance * weights["maintenance_activity"]
                   + quality["score"] * weights["code_quality"]
                   + documentation["score"] * weights["documentation"]
                   + license_fit * weights["license_fit"]) / 100.0, 1)

    return {
        "relevance": relevance,
        "reusability": reusability["score"],
        "maintenance_activity": maintenance,
        "code_quality": quality["score"],
        "documentation": documentation["score"],
        "license_fit": license_fit,
        "total": min(total, 100.0),
        "_detail": {
            "relevance_signals": relevance_signals,
            "reusability_signals": reusability["signals"],
            "documentation_signals": documentation["signals"],
            "code_quality_signals": quality["signals"],
        },
    }


def _license_risk(license_info: Dict[str, Any]) -> Optional[Dict[str, str]]:
    category = license_info["category"]
    if category == "unknown":
        return {"type": "license_risk", "level": "high",
                "detail": "無法識別授權條款，僅能參考，不得直接重用程式碼。"}
    if category == "high_risk":
        return {"type": "license_risk", "level": "high",
                "detail": f"授權 {license_info['spdx_id']} 屬高風險類別，避免直接重用。"}
    if category == "review_required":
        return {"type": "license_risk", "level": "medium",
                "detail": f"授權 {license_info['spdx_id']} 需人工法律審查。"}
    return None


def compute_risks(license_info: Dict[str, Any],
                  dependency_risk_list: List[Dict[str, str]],
                  metadata: Dict[str, Any], max_age_days: int,
                  now_ts: Optional[float] = None) -> List[Dict[str, str]]:
    risks: List[Dict[str, str]] = []

    license_risk = _license_risk(license_info)
    if license_risk:
        risks.append(license_risk)

    risks.extend(dependency_risk_list)

    if metadata.get("archived") is True:
        risks.append({"type": "maintenance_risk", "level": "high",
                      "detail": "專案已封存。"})

    days = days_since(metadata.get("pushed_at", ""), now_ts)
    if days is not None and days > max_age_days:
        risks.append({"type": "maintenance_risk", "level": "medium",
                      "detail": f"最後提交已超過 {days} 天。"})

    risks.sort(key=lambda r: RISK_RANK.get(r.get("level", "low"), 0), reverse=True)
    return risks


def overall_dependency_risk(risks: List[Dict[str, str]]) -> str:
    worst = "low"
    for risk in risks:
        if risk.get("type") == "dependency_risk" and \
                RISK_RANK.get(risk.get("level"), 0) > RISK_RANK[worst]:
            worst = risk["level"]
    return worst
