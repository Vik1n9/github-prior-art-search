#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

MINIMUM_PYTHON = (3, 9)

if sys.version_info < MINIMUM_PYTHON:
    sys.stderr.write(f"[FAILED] 需要 Python {'.'.join(map(str, MINIMUM_PYTHON))} 以上"
                     f"（目前 {sys.version.split()[0]}）（reason=unsupported_python）\n")
    sys.exit(1)

from scripts.common import (ScriptFailure, get_github_token, load_config,  # noqa: E402
                            output_dir, read_json, sha256_file, write_json)
from scripts.contract import normalize_query, validate_input  # noqa: E402
from scripts.finalize import build_final  # noqa: E402
from scripts.pipeline import run_search  # noqa: E402
from scripts.render_report import (render_final_report,  # noqa: E402
                                   render_search_report)

RESULT_JSON = "result.json"
RESULT_MD = "result.md"
FINAL_JSON = "final.json"
FINAL_MD = "final.md"


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub 先行調研與重用檢查")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="依組件搜尋、過濾並收集倉庫事實")
    search.add_argument("--input", required=True, help="輸入 JSON 檔案路徑")
    search.add_argument("--output-dir", default=None, help="覆寫 SKILL_OUTPUT_DIR")
    search.add_argument("--only", default=None,
                        help="只重跑指定組件（逗號分隔 id），其餘沿用既有 result.json")
    search.add_argument("--dry-run", action="store_true",
                        help="只校驗輸入並列出將執行的查詢，不連網")

    finalize = sub.add_parser("finalize", help="校驗模型適配判斷並產出最終報告")
    finalize.add_argument("--assessment", required=True, help="assessment JSON 檔案路徑")
    finalize.add_argument("--output-dir", default=None, help="覆寫 SKILL_OUTPUT_DIR")
    return parser.parse_args(argv)


def print_search_summary(result: Dict[str, Any], out_dir: Path) -> None:
    print(f"狀態: {result['status']}")
    for component in result["components"]:
        stats = component["stats"]
        top = component["candidates"][0]["repository"] if component["candidates"] else "—"
        print(f"- {component['id']}（第 {component['round']} 輪）：過濾後 "
              f"{stats['unique_after_filter']}，深度分析 {stats['shortlisted']}，首位 {top}")
    empty = [c["id"] for c in result["components"] if not c["candidates"]]
    if empty:
        print(f"無候選組件: {', '.join(empty)}")
    print(f"輸出: {out_dir / RESULT_JSON}")
    print("下一步: 讀取 result.json，逐組件撰寫 assessment.json 後執行 finalize。")


def command_search(args: argparse.Namespace) -> int:
    input_data = validate_input(read_json(Path(args.input)))
    only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else []

    if args.dry_run:
        for component in input_data["components"]:
            if only and component["id"] not in only:
                continue
            print(f"[{component['id']}] {component['name']}")
            for query in component["search_queries"]:
                print(f"  - {normalize_query(query)}")
        print("輸入校驗通過（dry run，未連網）。")
        return 0

    token = get_github_token()
    out_dir = output_dir(args.output_dir)
    previous = read_json(out_dir / RESULT_JSON, "invalid_previous") if only else None
    result = run_search(input_data, token, load_config(), previous, only)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / RESULT_JSON, result)
    (out_dir / RESULT_MD).write_text(render_search_report(result), encoding="utf-8")
    for stale in (FINAL_JSON, FINAL_MD):
        (out_dir / stale).unlink(missing_ok=True)
    print_search_summary(result, out_dir)
    return 0


def command_finalize(args: argparse.Namespace) -> int:
    out_dir = output_dir(args.output_dir)
    result_path = out_dir / RESULT_JSON
    result = read_json(result_path, "missing_result")
    assessment = read_json(Path(args.assessment), "invalid_assessment")
    final = build_final(result, assessment, sha256_file(result_path))

    write_json(out_dir / FINAL_JSON, final)
    (out_dir / FINAL_MD).write_text(render_final_report(final), encoding="utf-8")
    print(f"狀態: {final['status']}")
    for item in final["plan"]:
        target = f"{item['decision']} → {item['repository']}" \
            if item["verdict"] == "reuse" else "build_in_house"
        print(f"- {item['component']}: {target}")
    print(f"輸出: {out_dir / FINAL_MD}")
    return 0


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    if args.command == "search":
        return command_search(args)
    return command_finalize(args)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ScriptFailure as failure:
        print(f"[FAILED] {failure}（reason={failure.reason_code}）", file=sys.stderr)
        sys.exit(1)
