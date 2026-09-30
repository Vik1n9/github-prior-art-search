import re
from typing import Any, Dict, List, Optional

from .common import load_config, term_matches

INSTALL_RE = re.compile(
    r"install|安裝|getting[ _-]?started|quick[ _-]?start|go get|cargo add")
USAGE_RE = re.compile(r"usage|使用|example|範例|demo|how to use")

TEST_SEGMENTS = {"test", "tests", "spec", "specs", "__tests__", "testing"}
TEST_FILE_PREFIXES = ("test_",)
TEST_FILE_SUFFIXES = ("_test.py", "_test.go", "_test.rs", "_spec.rb", "test.java",
                      "tests.cs", ".test.js", ".test.ts", ".test.jsx", ".test.tsx",
                      ".spec.js", ".spec.ts", ".spec.jsx", ".spec.tsx")
CI_PATHS = (".github/workflows/", ".gitlab-ci.yml", ".circleci/", "jenkinsfile",
            "azure-pipelines.yml", ".travis.yml", ".buildkite/", ".drone.yml")
LINT_FILES = {".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json",
              ".eslintrc.yml", "eslint.config.js", "eslint.config.mjs",
              "eslint.config.ts", ".flake8", "ruff.toml", ".ruff.toml", ".pylintrc",
              ".pre-commit-config.yaml", ".stylelintrc", ".rubocop.yml", "biome.json",
              ".golangci.yml", ".golangci.yaml", "rustfmt.toml", ".rustfmt.toml",
              "clippy.toml", ".prettierrc", "checkstyle.xml", ".editorconfig"}
EXAMPLE_DIRS = {"examples", "example", "samples", "sample", "demo", "demos"}
DOC_DIRS = {"docs", "doc", "documentation", "website"}
PACKAGED_FILES = {"package.json", "setup.py", "pyproject.toml", "cargo.toml",
                  "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
                  "dockerfile"}


def _weighted_ratio(hits: int, total: int, weight: float) -> float:
    return 0.0 if total == 0 else weight * min(hits / total, 1.0)


def relevance_score(match_terms: List[str], tech_stack: List[str],
                    repo: Dict[str, Any], readme_text: Optional[str],
                    query_hits: int, total_queries: int,
                    config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = config or load_config()
    weights = config["relevance_weights"]
    readme = (readme_text or "")[:int(config["analysis"]["readme_match_chars"])]
    topics = " ".join(str(t) for t in (repo.get("topics") or []))
    metadata = " ".join([repo.get("full_name") or "", repo.get("description") or "",
                         topics])

    in_metadata = [t for t in match_terms if term_matches(t, metadata)]
    in_readme = [t for t in match_terms
                 if t not in in_metadata and term_matches(t, readme)]
    missing = [t for t in match_terms if t not in in_metadata and t not in in_readme]

    stack_haystack = " ".join([repo.get("language") or "", topics,
                               repo.get("description") or ""])
    stack_hits = [s for s in tech_stack if term_matches(s, stack_haystack)]

    points = {
        "term_coverage": _weighted_ratio(len(in_metadata) + len(in_readme),
                                         len(match_terms), weights["term_coverage"]),
        "metadata_coverage": _weighted_ratio(len(in_metadata), len(match_terms),
                                             weights["metadata_coverage"]),
        "query_hits": _weighted_ratio(query_hits, min(total_queries, 3),
                                      weights["query_hits"]),
    }
    applicable = weights["term_coverage"] + weights["metadata_coverage"] \
        + weights["query_hits"]
    if tech_stack:
        points["tech_stack"] = _weighted_ratio(len(stack_hits), len(tech_stack),
                                               weights["tech_stack"])
        applicable += weights["tech_stack"]

    return {
        "score": round(sum(points.values()) * 100.0 / applicable, 1),
        "readme_considered": readme_text is not None,
        "matched_in_metadata": in_metadata,
        "matched_in_readme": in_readme,
        "missing_terms": missing,
        "tech_stack_matched": stack_hits,
        "query_hits": query_hits,
    }


def maintenance_score(days: Optional[int],
                      config: Optional[Dict[str, Any]] = None) -> int:
    buckets = (config or load_config())["maintenance_buckets"]
    if days is None:
        return 0
    for bucket in buckets:
        if "max_days" not in bucket or days <= bucket["max_days"]:
            return int(bucket["score"])
    return 0


def top_level_dirs(paths: List[str]) -> set:
    return {path.split("/")[0].lower() for path in paths if "/" in path}


def top_level_files(paths: List[str]) -> set:
    return {path.lower() for path in paths if "/" not in path}


def _scored(signals: Dict[str, Any], weights: Dict[str, Any]) -> Dict[str, Any]:
    score = sum(weights[key] * float(hit) for key, hit in signals.items())
    return {"score": round(score, 1), "signals": signals}


def documentation_score(readme_text: Optional[str], paths: List[str],
                        config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = config or load_config()
    readme = (readme_text or "")[:int(config["analysis"]["readme_match_chars"])].lower()
    dirs = top_level_dirs(paths)
    return _scored({
        "has_readme": bool(readme),
        "readme_has_install": bool(INSTALL_RE.search(readme)),
        "readme_has_usage": bool(USAGE_RE.search(readme)),
        "has_docs_folder": bool(dirs & DOC_DIRS),
        "has_examples_folder": bool(dirs & EXAMPLE_DIRS),
    }, config["documentation_signals"])


def has_tests(paths: List[str]) -> bool:
    for path in paths:
        segments = path.lower().split("/")
        if set(segments[:-1]) & TEST_SEGMENTS:
            return True
        name = segments[-1]
        if name.startswith(TEST_FILE_PREFIXES) or name.endswith(TEST_FILE_SUFFIXES):
            return True
    return False


def code_quality_score(paths: List[str],
                       config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = config or load_config()
    lowered = [path.lower() for path in paths]
    return _scored({
        "has_tests": has_tests(paths),
        "has_ci": any(path.startswith(CI_PATHS) for path in lowered),
        "has_lint_config": bool(top_level_files(paths) & LINT_FILES),
    }, config["code_quality_signals"])


def _moderate_dependency_ratio(summary: Dict[str, Any]) -> float:
    if summary.get("status") != "parsed":
        return 0.0
    total = int(summary.get("total_count", 0))
    if total <= 100:
        return 1.0
    if total >= 200:
        return 0.0
    return round((200 - total) / 100.0, 2)


def reusability_score(paths: List[str], dependency_summary: Dict[str, Any],
                      has_release_or_tags: Optional[bool],
                      config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = config or load_config()
    return _scored({
        "lockfile_present": bool(dependency_summary.get("lockfile_present")),
        "has_release_or_tags": bool(has_release_or_tags),
        "moderate_dependency_count": _moderate_dependency_ratio(dependency_summary),
        "has_examples": bool(top_level_dirs(paths) & EXAMPLE_DIRS),
        "packaged_project": bool(top_level_files(paths) & PACKAGED_FILES),
    }, config["reusability_signals"])


def health_score(parts: Dict[str, float],
                 config: Optional[Dict[str, Any]] = None) -> float:
    weights = (config or load_config())["health_weights"]
    total = sum(parts[key] * weights[key] for key in weights)
    return round(total / sum(weights.values()), 1)


def rank_score(relevance: float, health: float,
               config: Optional[Dict[str, Any]] = None) -> float:
    weights = (config or load_config())["rank_weights"]
    total = relevance * weights["relevance"] + health * weights["health"]
    return round(total / (weights["relevance"] + weights["health"]), 1)
