#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""github-prior-art-search 主入口（§8 腳本執行流程）。

用法：
    python3 main.py --input input.json [--output-dir OUTPUT_DIR]

缺少 GITHUB_TOKEN、依賴或輸入不合法時以非零結束並回報原因（§22.1）。
"""
import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from common import (ScriptFailure, get_github_token, load_config,
                    output_dir, utc_now_iso, write_json)  # noqa: E402
from build_recommendation import (build_recommendation, candidate_summary,  # noqa: E402
                                  decide_reuse)
from parse_dependencies import analyze_dependencies  # noqa: E402
from parse_license import analyze_license  # noqa: E402
from score_candidates import calculate_scores, compute_risks  # noqa: E402
import search_github as sg  # noqa: E402


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub 先行調研與重用檢查（script-first）")
    parser.add_argument("--input", required=True, help="輸入 JSON 檔案路徑（§6 格式）")
    parser.add_argument("--output-dir", default=None, help="覆寫 SKILL_OUTPUT_DIR")
    return parser.parse_args(argv)


def load_input(path: str) -> Dict[str, Any]:
    import json
    input_path = Path(path)
    if not input_path.exists():
        raise ScriptFailure(f"找不到輸入檔案：{input_path}", "invalid_input")
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ScriptFailure(f"輸入檔案不是合法 JSON：{exc}", "invalid_input")


# ---------------------------------------------------------------------------
# 單一候選深度分析
# ---------------------------------------------------------------------------

def analyze_candidate(repo: Dict[str, Any], input_data: Dict[str, Any],
                      token: str, now_ts: float,
                      config: Dict[str, Any]) -> Dict[str, Any]:
    full_name = repo["full_name"]
    branch = repo.get("default_branch") or "HEAD"

    paths, truncated, tree_err = sg.fetch_file_tree(full_name, branch, token)
    if tree_err:
        paths, truncated = [], False

    readme_text = None
    readme_path = sg.find_readme_path(paths)
    if readme_path and readme_path.lower() != "readme.md":
        text, _err = sg.fetch_raw_file(full_name, branch, readme_path, token)
        readme_text = text
    elif not truncated or paths:
        text, _err = sg.fetch_readme(full_name, branch, token)
        readme_text = text

    license_info = analyze_license(repo, paths, config)

    def fetch_dep_content(rel_path: str):
        text, _err = sg.fetch_raw_file(full_name, branch, rel_path, token)
        return text

    dependency_summary, dep_warnings = analyze_dependencies(paths, fetch_dep_content)

    has_release, release_err = sg.fetch_has_release(full_name, token)

    scores = calculate_scores(input_data, repo, license_info, dependency_summary,
                              readme_text, paths, bool(has_release),
                              now_ts=now_ts, config=config)

    dep_risks = []
    from parse_dependencies import dependency_risks as dep_risk_rules
    if dependency_summary:
        dep_risks = dep_risk_rules(dependency_summary, config)
    risks = compute_risks(license_info, dep_risks, repo, config)

    decision = decide_reuse(scores, risks, repo, config)

    candidate = {
        "repository": full_name,
        "url": repo.get("html_url"),
        "description": repo.get("description") or "",
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "language": repo.get("language"),
        "license": {
            "spdx_id": license_info["spdx_id"],
            "category": license_info["category"],
            "source": license_info["source"],
            "action": license_info["action"],
            "risk_level": license_info["risk_level"],
        },
        "pushed_at": repo.get("pushed_at"),
        "archived": repo.get("archived", False),
        "topics": repo.get("topics") or [],
        "scores": {k: v for k, v in scores.items() if k != "_detail"},
        "score_detail": scores["_detail"],
        "reuse_decision": decision,
        "dependencies": dependency_summary or {
            "manifests_found": [], "lockfile_present": False,
            "runtime_count": 0, "dev_count": 0, "total_count": 0,
            "unpinned_count": 0, "details": [],
            "parsing_failed": True,
        },
        "risks": risks,
    }
    candidate["summary"] = candidate_summary(candidate)

    warnings: List[Dict[str, str]] = list(dep_warnings)
    if tree_err:
        warnings.append({"type": "tree_fetch_failed",
                         "detail": f"{full_name}: {tree_err['detail']}"})
    if truncated:
        warnings.append({"type": "tree_truncated",
                         "detail": f"{full_name}: 檔案樹過大被截斷，訊號可能不完整。"})
    if release_err:
        warnings.append({"type": "release_check_failed",
                         "detail": f"{full_name}: {release_err['detail']}"})
    if license_info["source"] == "license_file_unparsed":
        warnings.append({"type": "license_unparsed",
                         "detail": f"{full_name}: 存在授權檔但無法識別 SPDX，標記 unknown。"})
    return {"candidate": candidate, "warnings": warnings}


# ---------------------------------------------------------------------------
# 輸出
# ---------------------------------------------------------------------------

def render_report(context: Dict[str, Any], out_dir: Path) -> None:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    template_dir = Path(__file__).resolve().parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)),
                      undefined=StrictUndefined, autoescape=False)
    template = env.get_template("report.md.jinja2")
    rendered = template.render(**context)
    (out_dir / "result.md").write_text(rendered, encoding="utf-8")


def write_outputs(out_dir: Path, result: Dict[str, Any],
                  analyzed: List[Dict[str, Any]]) -> None:
    write_json(out_dir / "result.json", result)

    candidates_payload = [
        {k: v for k, v in c.items() if k != "metadata"} for c in analyzed
    ]
    write_json(out_dir / "candidates.json", {"count": len(analyzed),
                                             "candidates": candidates_payload})

    write_json(out_dir / "dependencies.json", {
        c["repository"]: c.get("dependencies") for c in analyzed})

    recommendation = result["recommendation"]
    write_json(out_dir / "decision.json", {
        "skill": result["skill"],
        "status": result["status"],
        "recommendation": recommendation,
        "per_candidate": [
            {"repository": c["repository"],
             "total_score": c["scores"]["total"],
             "reuse_decision": c["reuse_decision"]}
            for c in sorted(analyzed, key=lambda x: x["scores"]["total"], reverse=True)
        ],
    })

    render_report({
        "input": result["project"],
        "search": result["search"],
        "candidates": analyzed,
        "recommendation": recommendation,
        "warnings": result["warnings"],
        "generated_at": result["execution"]["finished_at"],
    }, out_dir)


# ---------------------------------------------------------------------------
# 主流程（§8）
# ---------------------------------------------------------------------------

def main(argv: List[str]) -> int:
    args = parse_args(argv)
    started_at = utc_now_iso()
    config = load_config()

    # 步驟 1：依賴已由 check_dependencies.sh 驗證；此處驗證必要環境
    token = get_github_token()  # §22.1：缺 GITHUB_TOKEN 必須失敗並回報原因

    # 步驟 2-3：讀取並校验輸入
    raw_input = load_input(args.input)
    input_data = sg.validate_input(raw_input)

    min_stars = sg.effective_min_stars(input_data)          # 強制 >=100
    max_candidates = int(input_data.get("max_candidates")
                         or config["defaults"]["max_candidates"])
    exclude_repos = [str(x) for x in input_data.get("exclude_repos", [])]

    warnings: List[Dict[str, str]] = []
    state = sg.SearchState()

    # 步驟 4：產生搜尋查詢
    queries = sg.build_queries(input_data)
    if not queries:
        raise ScriptFailure("無法產生任何搜尋查詢，請提供更具體的 project_goal/core_features。",
                            "no_queries")

    # 步驟 5：呼叫 GitHub API
    delay = float(config["search"].get("request_delay_seconds", 2.5))
    raw_items: List[Dict[str, Any]] = []
    for index, query in enumerate(queries):
        if state.rate_limited:
            break
        if index > 0:
            time.sleep(delay)
        items, error = sg.search_repositories(query, token, min_stars, state)
        if error:
            warnings.append({"type": "search_failed" if error["kind"] != "rate_limit"
                             else "rate_limit",
                             "query": query, "detail": error["detail"]})
            continue
        raw_items.extend(items)

    # 步驟 6-9：本地二次過濾、黑名單、去重
    kept, discarded = sg.filter_repositories(raw_items, exclude_repos)
    unique = sg.deduplicate(kept)
    ranked = sg.sort_initial(unique)
    shortlist = ranked[:max_candidates]

    # 步驟 10-15：元資料、授權、依賴、評分、決策
    now_ts = time.time()
    analyzed: List[Dict[str, Any]] = []
    for repo in shortlist:
        outcome = analyze_candidate(repo, input_data, token, now_ts, config)
        analyzed.append({**outcome["candidate"], "metadata": {
            "default_branch": repo.get("default_branch"),
            "open_issues_count": repo.get("open_issues_count"),
            "watchers_count": repo.get("watchers_count"),
            "created_at": repo.get("created_at"),
            "size_kb": repo.get("size"),
        }})
        warnings.extend(outcome["warnings"])

    # 排序與建議
    analyzed.sort(key=lambda c: c["scores"]["total"], reverse=True)
    recommendation = build_recommendation(
        [{k: v for k, v in c.items()} for c in analyzed], config)

    # 步驟 16：輸出
    finished_at = utc_now_iso()
    had_search_failure = any(w.get("type") in ("rate_limit", "search_failed",
                                               "tree_fetch_failed", "release_check_failed",
                                               "dependency_parsing_failed") for w in warnings)
    status = "partial" if had_search_failure else "completed"
    if recommendation["primary_action"] == "build_in_house" and not analyzed:
        warnings.append({"type": "no_candidates",
                         "detail": "無候選專案，輸出 build_in_house 建議。"})

    result = {
        "skill": config["skill"]["name"],
        "status": status,
        "execution": {
            "started_at": started_at,
            "finished_at": finished_at,
            "script_version": str(config["skill"]["version"]),
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
                "last_commit_within_days": int(config["defaults"]["last_commit_within_days"]),
            },
            "raw_results": len(raw_items),
            "after_filter": len(kept),
            "discarded_sample": discarded[:20],
            "deep_analyzed": len(analyzed),
        },
        "candidates": [{k: v for k, v in c.items() if k != "metadata"} for c in analyzed],
        "recommendation": recommendation,
        "warnings": warnings,
    }

    out_dir = output_dir()
    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    write_outputs(out_dir, result, analyzed)

    print(f"狀態: {status}")
    print(f"查詢數: {len(queries)}，原始結果: {len(raw_items)}，"
          f"過濾後: {len(kept)}，深度分析: {len(analyzed)}")
    if analyzed:
        top = analyzed[0]
        print(f"最高分候選: {top['repository']}（總分 {top['scores']['total']}，"
              f"決策 {top['reuse_decision']}）")
    print(f"主要建議: {recommendation['primary_action']}"
          + (f" → {recommendation['primary_repository']}" if recommendation["primary_repository"] else ""))
    print(f"輸出目錄: {out_dir}")
    if warnings:
        print(f"警告數: {len(warnings)}（詳見 result.json 的 warnings）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ScriptFailure as failure:
        print(f"[FAILED] {failure}（reason={failure.reason_code}）", file=sys.stderr)
        sys.exit(1)
