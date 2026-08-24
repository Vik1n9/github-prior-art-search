from pathlib import Path
from typing import Any, Dict, List

from .common import write_json


def _join(items: List[Any], separator: str = "、") -> str:
    return separator.join(str(item) for item in items)


def _project_section(project: Dict[str, Any]) -> List[str]:
    tech_stack = project.get("tech_stack") or []
    lines = [
        "## 專案輸入",
        "",
        f"- 專案目標：{project.get('goal', '')}",
        f"- 核心功能：{_join(project.get('core_features', []))}",
        f"- 技術堆疊：{_join(tech_stack) if tech_stack else '（未提供）'}",
    ]
    if project.get("domain"):
        lines.append(f"- 領域：{project['domain']}")
    lines.append("")
    return lines


def _search_section(search: Dict[str, Any]) -> List[str]:
    queries = search.get("queries", [])
    lines = [
        "## 搜尋條件",
        "",
        f"- 最低星數：{search.get('effective_min_stars')}（腳本強制）",
        "- 忽略封存專案：是",
        "- 忽略禁用專案：是",
        f"- 最後提交限制：{search['filters']['last_commit_within_days']} 天",
        f"- 執行查詢數：{len(queries)}",
        f"- 原始結果：{search.get('raw_results')} → 過濾後 "
        f"{search.get('after_filter')} → 深度分析 {search.get('deep_analyzed')}",
        "",
        "<details>",
        "<summary>搜尋查詢清單</summary>",
        "",
        "```text",
    ]
    lines.extend(queries)
    lines.extend(["```", "</details>", ""])
    return lines


def _candidate_table(candidates: List[Dict[str, Any]]) -> List[str]:
    lines = ["| 專案 | 星數 | 授權 | 最後更新 | 總分 | 決策 |",
             "|---|---:|---|---|---:|---|"]
    for candidate in candidates:
        spdx = (candidate.get("license") or {}).get("spdx_id") or "unknown"
        pushed = (candidate.get("pushed_at") or "")[:10]
        lines.append(
            f"| [{candidate['repository']}]({candidate.get('url')}) | "
            f"{candidate.get('stars', 0)} | {spdx} | {pushed} | "
            f"{candidate['scores']['total']} | {candidate['reuse_decision']} |")
    lines.append("")
    return lines


def _candidate_detail(index: int, candidate: Dict[str, Any]) -> List[str]:
    license_info = candidate.get("license") or {}
    dependencies = candidate.get("dependencies") or {}
    manifests = dependencies.get("manifests_found") or []
    scores = candidate["scores"]

    lines = [
        f"#### {index}. {candidate['repository']} — 決策：{candidate['reuse_decision']}",
        "",
        f"- 說明：{candidate.get('description') or '（無說明）'}",
        f"- 星數：{candidate.get('stars', 0)}｜Forks：{candidate.get('forks', 0)}"
        f"｜語言：{candidate.get('language') or '未知'}",
        f"- 授權：{license_info.get('spdx_id') or 'unknown'}"
        f"（分類：{license_info.get('category')}、來源：{license_info.get('source')}）",
        f"- 分數：相關度 {scores['relevance']}｜重用性 {scores['reusability']}"
        f"｜維護活躍度 {scores['maintenance_activity']}｜程式碼品質 "
        f"{scores['code_quality']}｜文件 {scores['documentation']}｜授權契合 "
        f"{scores['license_fit']}｜**總分 {scores['total']}**",
        f"- 依賴：{dependencies.get('total_count', 0)} 筆"
        f"（runtime {dependencies.get('runtime_count', 0)}／dev "
        f"{dependencies.get('dev_count', 0)}），未固定版本 "
        f"{dependencies.get('unpinned_count', 0)} 筆，lockfile："
        f"{'有' if dependencies.get('lockfile_present') else '無'}，"
        f"清單檔：{', '.join(manifests) if manifests else '未偵測到'}",
    ]

    risks = candidate.get("risks") or []
    if risks:
        lines.extend(["", "- 風險標記："])
        lines.extend(f"  - [{r['level']}] {r['type']}：{r['detail']}" for r in risks)
    else:
        lines.append("- 風險標記：（無）")

    lines.extend(["", f"> {candidate.get('summary', '')}", ""])
    return lines


def _candidates_section(candidates: List[Dict[str, Any]]) -> List[str]:
    lines = ["## 候選專案", ""]
    if not candidates:
        lines.extend(["（無候選專案。所有輸入條件過濾後沒有符合的倉庫。）", ""])
        return lines

    lines.extend(_candidate_table(candidates))
    lines.extend(["### 各候選詳情", ""])
    for index, candidate in enumerate(candidates, start=1):
        lines.extend(_candidate_detail(index, candidate))
    return lines


def _recommendation_section(recommendation: Dict[str, Any]) -> List[str]:
    primary_repo = recommendation.get("primary_repository")
    parts = recommendation.get("build_in_house_parts") or []
    lines = [
        "## 建議",
        "",
        f"- 主要動作：**{recommendation['primary_action']}**"
        f"{f'（{primary_repo}）' if primary_repo else ''}",
        f"- 主要原因：{recommendation['reason']}",
        f"- 需自行開發部分：{_join(parts) if parts else '（無）'}",
        "",
        "### 後續步驟",
        "",
    ]
    lines.extend(f"{i}. {step}"
                 for i, step in enumerate(recommendation.get("next_steps", []), start=1))
    lines.append("")
    return lines


def _warnings_section(warnings: List[Dict[str, str]]) -> List[str]:
    if not warnings:
        return []
    lines = ["## 警告", ""]
    for warning in warnings:
        prefix = f"[{warning['query']}] " if warning.get("query") else ""
        lines.append(f"- {prefix}{warning['type']}：{warning['detail']}")
    lines.append("")
    return lines


def render_report_text(result: Dict[str, Any]) -> str:
    lines = [
        "# GitHub 先行調研報告",
        "",
        f"> 由 `github-prior-art-search` 腳本產生（script-first）。"
        f"生成時間：{result['execution']['finished_at']}",
        "",
    ]
    lines.extend(_project_section(result["project"]))
    lines.extend(_search_section(result["search"]))
    lines.extend(_candidates_section(result["candidates"]))
    lines.extend(_recommendation_section(result["recommendation"]))
    lines.extend(_warnings_section(result["warnings"]))
    return "\n".join(lines)


def write_outputs(out_dir: Path, result: Dict[str, Any]) -> None:
    write_json(out_dir / "result.json", result)
    (out_dir / "result.md").write_text(render_report_text(result), encoding="utf-8")
