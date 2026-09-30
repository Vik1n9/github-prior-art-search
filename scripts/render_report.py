from typing import Any, Dict, List

DECISION_LABELS = {
    "adopt_as_dependency": "直接作為依賴",
    "fork_and_modify": "Fork 後修改",
    "use_as_template": "作為模板",
    "reference_architecture_only": "僅參考架構",
    "build_in_house": "自行開發",
}


def _label(decision: str) -> str:
    return f"{DECISION_LABELS.get(decision, decision)}（`{decision}`）"


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _warnings_section(warnings: List[Dict[str, str]]) -> List[str]:
    if not warnings:
        return []
    lines = ["## 警告", ""]
    for w in warnings:
        scope = w.get("component") or w.get("repository") or ""
        query = f"「{w['query']}」" if w.get("query") else ""
        prefix = f"[{scope}{query}] " if scope or query else ""
        lines.append(f"- {prefix}`{w['type']}`：{w['detail']}")
    lines.append("")
    return lines


def _repo_warnings(result: Dict[str, Any]) -> List[Dict[str, str]]:
    return [w for facts in result["repositories"].values() for w in facts["warnings"]]


def _candidate_table(component: Dict[str, Any], repos: Dict[str, Any]) -> List[str]:
    lines = ["| 倉庫 | 排序分 | 相關度 | 健康度 | 星數 | 授權 | 可採用上限 | 未命中詞 |",
             "|---|---:|---:|---:|---:|---|---|---|"]
    for c in component["candidates"]:
        facts = repos[c["repository"]]
        missing = "、".join(c["relevance"]["missing_terms"]) or "—"
        lines.append(
            f"| [{c['repository']}]({facts['url']}) | {c['rank_score']} | "
            f"{c['relevance']['score']} | {facts['scores']['health']} | {facts['stars']} | "
            f"{facts['license']['spdx_id'] or 'unknown'} | `{facts['cap']}` | "
            f"{_cell(missing)} |")
    lines.append("")
    return lines


def _component_search_section(component: Dict[str, Any],
                              repos: Dict[str, Any]) -> List[str]:
    stats = component["stats"]
    lines = [
        f"### {component['name']}（`{component['id']}`，第 {component['round']} 輪）",
        "",
        f"- must_have：{'、'.join(component['must_have'])}",
        f"- match_terms：{', '.join(component['match_terms'])}",
        f"- 查詢：{' ／ '.join(f'`{q}`' for q in component['search_queries'])}",
        f"- 結果：原始 {stats['raw_results']} 筆 → 過濾後不重複 "
        f"{stats['unique_after_filter']} 個 → 深度分析 {stats['shortlisted']} 個",
        "",
    ]
    if not component["candidates"]:
        lines.extend(["（無候選。可重新設計此組件的查詢並以 `--only` 重跑，"
                      "或判定 build_in_house。）", ""])
        return lines
    lines.extend(_candidate_table(component, repos))
    return lines


def _repository_section(name: str, facts: Dict[str, Any]) -> List[str]:
    deps = facts["dependencies"]
    lines = [
        f"### {name}",
        "",
        f"- {facts['description'] or '（無說明）'}",
        f"- 星數 {facts['stars']}｜語言 {facts['language'] or '未知'}｜"
        f"最後推送 {(facts['pushed_at'] or '')[:10]}（{facts['days_since_push']} 天前）",
        f"- 授權：{facts['license']['spdx_id'] or 'unknown'}"
        f"（{facts['license']['category']}，來源 {facts['license']['source']}）",
        f"- 健康度 {facts['scores']['health']}：維護 {facts['scores']['maintenance']}｜"
        f"品質 {facts['scores']['code_quality']}｜文件 {facts['scores']['documentation']}｜"
        f"重用性 {facts['scores']['reusability']}",
        f"- 依賴（{deps['status']}）：{deps['total_count']} 筆"
        f"（runtime {deps['runtime_count']}／dev {deps['dev_count']}），"
        f"未固定 {deps['unpinned_count']}，lockfile {'有' if deps['lockfile_present'] else '無'}",
        f"- 可採用上限：`{facts['cap']}`"
        + (f"（{'；'.join(facts['cap_reasons'])}）" if facts["cap_reasons"] else ""),
    ]
    if facts["risks"]:
        lines.extend(f"- 風險 [{r['level']}] {r['type']}：{r['detail']}"
                     for r in facts["risks"])
    if facts["data_gaps"]:
        lines.append(f"- 資料缺口：{', '.join(facts['data_gaps'])}")
    lines.append("")
    return lines


def render_search_report(result: Dict[str, Any]) -> str:
    filters = result["filters"]
    lines = [
        "# GitHub 先行調研：搜尋結果（待評估）",
        "",
        f"> 狀態 `{result['status']}`｜產生於 {result['execution']['finished_at']}｜"
        "此報告僅含腳本事實，尚未經模型適配判斷。",
        "",
        "## 需求",
        "",
        result["requirement"],
        "",
        f"- 過濾：星數 ≥ {filters['min_stars']}、最後推送 ≤ "
        f"{filters['last_push_within_days']} 天、排除 archived／disabled",
        "",
        "## 各組件候選",
        "",
    ]
    for component in result["components"]:
        lines.extend(_component_search_section(component, result["repositories"]))
    if result["repositories"]:
        lines.extend(["## 倉庫事實", ""])
        for name, facts in result["repositories"].items():
            lines.extend(_repository_section(name, facts))
    lines.extend(_warnings_section(result["warnings"] + _repo_warnings(result)))
    return "\n".join(lines)


def _plan_table(plan: List[Dict[str, Any]]) -> List[str]:
    lines = ["| 組件 | 結論 | 倉庫 | 決策 | 適配 |", "|---|---|---|---|---|"]
    for item in plan:
        if item["verdict"] == "build_in_house":
            lines.append(f"| {_cell(item['name'])} | 自行開發 | — | — | — |")
        else:
            lines.append(
                f"| {_cell(item['name'])} | 重用 | [{item['repository']}]({item['url']}) | "
                f"{_label(item['decision'])} | {item['fit']} |")
    lines.append("")
    return lines


def _plan_detail(item: Dict[str, Any]) -> List[str]:
    lines = [f"### {item['name']}（`{item['component']}`）", ""]
    if item["verdict"] == "build_in_house":
        lines.extend([f"- 結論：自行開發（搜尋 {item['search_rounds']} 輪）",
                      f"- 理由：{item['rationale']}"])
    else:
        lines.extend([
            f"- 結論：{_label(item['decision'])} → "
            f"[{item['repository']}]({item['url']})",
            f"- 腳本上限：`{item['cap']}`"
            + (f"（{'；'.join(item['cap_reasons'])}）" if item["cap_reasons"] else ""),
            f"- 授權：{item['license'] or 'unknown'}",
            f"- 已涵蓋：{'、'.join(item['covered'])}",
            f"- 缺口：{'、'.join(item['gaps']) or '（無）'}",
            f"- 理由：{item['rationale']}",
            "- 證據：",
        ])
        lines.extend(f"  - {e}" for e in item["evidence"])
        lines.extend(f"- 風險 [{r['level']}] {r['type']}：{r['detail']}"
                     for r in item["risks"])
    for alt in item["alternatives"]:
        lines.append(f"- 備選：[{alt['repository']}]({alt['url']}) "
                     f"{_label(alt['decision'])}：{alt['note']}")
    lines.append("- 後續步驟：")
    lines.extend(f"  {i}. {step}" for i, step in enumerate(item["next_steps"], start=1))
    lines.append("")
    return lines


def render_final_report(final: Dict[str, Any]) -> str:
    summary = final["summary"]
    lines = [
        "# GitHub 先行調研報告",
        "",
        f"> 狀態 `{final['status']}`｜定稿於 {final['finalized_at']}｜"
        f"result.json sha256 `{final['result_sha256'][:12]}`",
        "",
        "## 需求",
        "",
        final["requirement"],
        "",
        "## 摘要",
        "",
        summary["executive_summary"],
        "",
    ]
    if summary["notable_observations"]:
        lines.extend(f"- {o}" for o in summary["notable_observations"])
        lines.append("")
    lines.extend(["## 組件方案", ""])
    lines.extend(_plan_table(final["plan"]))
    for item in final["plan"]:
        lines.extend(_plan_detail(item))
    lines.extend(["## 需自行開發部分", ""])
    if final["build_in_house_parts"]:
        for part in final["build_in_house_parts"]:
            lines.append(f"- {part['name']}（{part['reason']}）：{'、'.join(part['items'])}")
    else:
        lines.append("（無）")
    lines.append("")
    lines.extend(_warnings_section(final["warnings"]))
    return "\n".join(lines)
