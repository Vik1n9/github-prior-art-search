#!/usr/bin/env python3
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from scripts import search_github as gh
from scripts.analyze import analyze_candidate
from scripts.build_recommendation import build_recommendation
from scripts.common import (ScriptFailure, get_github_token, load_config,
                            load_skill_metadata, output_dir, utc_now_iso)
from scripts.render_report import write_outputs

MINIMUM_PYTHON = (3, 9)
PARTIAL_WARNING_TYPES = ("rate_limit", "search_failed", "tree_fetch_failed",
                         "release_check_failed", "dependency_parsing_failed")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub 先行調研與重用檢查")
    parser.add_argument("--input", required=True, help="輸入 JSON 檔案路徑")
    parser.add_argument("--output-dir", default=None, help="覆寫 SKILL_OUTPUT_DIR")
    return parser.parse_args(argv)


def load_input(path: str) -> Dict[str, Any]:
    input_path = Path(path)
    if not input_path.exists():
        raise ScriptFailure(f"找不到輸入檔案：{input_path}", "invalid_input")
    try:
        return json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScriptFailure(f"輸入檔案不是合法 JSON：{exc}", "invalid_input")


def build_search_queries(input_data: Dict[str, Any]) -> List[str]:
    queries = gh.build_queries(input_data)
    if not queries:
        raise ScriptFailure(
            "無法產生任何搜尋查詢，請提供更具體的 project_goal/core_features。",
            "no_queries")
    return queries


def execute_searches(queries: List[str], token: str, min_stars: int
                     ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    items: List[Dict[str, Any]] = []
    warnings: List[Dict[str, str]] = []
    for query in queries:
        found, error = gh.search_repositories(query, token, min_stars)
        if not error:
            items.extend(found)
            continue
        warnings.append({
            "type": "rate_limit" if error["kind"] == "rate_limit" else "search_failed",
            "query": query,
            "detail": error["detail"],
        })
        if error["kind"] == "rate_limit":
            break
    return items, warnings


def shortlist_candidates(items: List[Dict[str, Any]], input_data: Dict[str, Any],
                         max_age_days: int, now_ts: float, max_candidates: int
                         ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    exclude_repos = [str(x) for x in input_data.get("exclude_repos", [])]
    kept, discarded = gh.filter_repositories(items, exclude_repos, max_age_days, now_ts)
    ranked = gh.sort_initial(gh.deduplicate(kept))
    return ranked[:max_candidates], discarded


def analyze_all(shortlist: List[Dict[str, Any]], input_data: Dict[str, Any],
                token: str, now_ts: float, max_age_days: int, config: Dict[str, Any]
                ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    candidates: List[Dict[str, Any]] = []
    warnings: List[Dict[str, str]] = []
    for repo in shortlist:
        outcome = analyze_candidate(repo, input_data, token, now_ts,
                                    max_age_days, config)
        candidates.append(outcome["candidate"])
        warnings.extend(outcome["warnings"])
    candidates.sort(key=lambda c: c["scores"]["total"], reverse=True)
    return candidates, warnings


def run(input_data: Dict[str, Any], token: str, config: Dict[str, Any],
        started_at: str) -> Dict[str, Any]:
    min_stars = gh.effective_min_stars(input_data)
    max_age_days = gh.effective_max_age_days(input_data)
    max_candidates = int(input_data.get("max_candidates")
                         or config["defaults"]["max_candidates"])
    now_ts = time.time()

    queries = build_search_queries(input_data)
    raw_items, warnings = execute_searches(queries, token, min_stars)
    shortlist, discarded = shortlist_candidates(raw_items, input_data, max_age_days,
                                                now_ts, max_candidates)
    candidates, analysis_warnings = analyze_all(shortlist, input_data, token,
                                                now_ts, max_age_days, config)
    warnings.extend(analysis_warnings)

    recommendation = build_recommendation(candidates, config)
    if not candidates:
        warnings.append({"type": "no_candidates",
                         "detail": "無候選專案，輸出 build_in_house 建議。"})

    skill = load_skill_metadata()
    kept_count = len(raw_items) - len(discarded)
    return {
        "skill": skill["name"],
        "status": "partial" if any(w["type"] in PARTIAL_WARNING_TYPES
                                   for w in warnings) else "completed",
        "execution": {
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "script_version": skill["version"],
        },
        "project": {
            "goal": input_data.get("project_goal", ""),
            "core_features": input_data.get("core_features", []),
            "tech_stack": input_data.get("tech_stack", []),
            "domain": input_data.get("domain"),
        },
        "search": {
            "queries": queries,
            "effective_min_stars": min_stars,
            "filters": {
                "archived": False,
                "disabled": False,
                "last_commit_within_days": max_age_days,
            },
            "raw_results": len(raw_items),
            "after_filter": kept_count,
            "discarded_sample": discarded[:20],
            "deep_analyzed": len(candidates),
        },
        "candidates": candidates,
        "recommendation": recommendation,
        "warnings": warnings,
    }


def print_summary(result: Dict[str, Any], out_dir: Path) -> None:
    search = result["search"]
    recommendation = result["recommendation"]
    print(f"狀態: {result['status']}")
    print(f"查詢數: {len(search['queries'])}，原始結果: {search['raw_results']}，"
          f"過濾後: {search['after_filter']}，深度分析: {search['deep_analyzed']}")
    if result["candidates"]:
        top = result["candidates"][0]
        print(f"最高分候選: {top['repository']}（總分 {top['scores']['total']}，"
              f"決策 {top['reuse_decision']}）")
    primary_repo = recommendation["primary_repository"]
    print(f"主要建議: {recommendation['primary_action']}"
          + (f" → {primary_repo}" if primary_repo else ""))
    print(f"輸出目錄: {out_dir}")
    if result["warnings"]:
        print(f"警告數: {len(result['warnings'])}（詳見 result.json 的 warnings）")


def main(argv: List[str]) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        raise ScriptFailure(
            f"需要 Python {'.'.join(map(str, MINIMUM_PYTHON))} 以上"
            f"（目前 {sys.version.split()[0]}）", "unsupported_python")

    args = parse_args(argv)
    started_at = utc_now_iso()
    config = load_config()
    token = get_github_token()
    input_data = gh.validate_input(load_input(args.input))

    result = run(input_data, token, config, started_at)

    out_dir = Path(args.output_dir) if args.output_dir else output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    write_outputs(out_dir, result)
    print_summary(result, out_dir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ScriptFailure as failure:
        print(f"[FAILED] {failure}（reason={failure.reason_code}）", file=sys.stderr)
        sys.exit(1)
