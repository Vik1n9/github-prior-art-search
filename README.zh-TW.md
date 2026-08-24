# github-prior-art-search

[English](README.md) ｜ [繁體中文](README.zh-TW.md)

GitHub 先行調研與重用檢查 Agent Skill，遵循 [Agent Skills](https://agentskills.io)
標準（`SKILL.md`）。僅需 Python 3.9+ 標準庫。

## 安裝

以 OpenCode 指令調用：

```bash
cp command/github-search.md ~/.config/opencode/command/
```

技能本體需安裝於 `~/.config/opencode/skills/github-prior-art-search/`，
之後以 `/github-search <專案目標 + 核心功能 + 技術堆疊>` 調用。

## 執行

```bash
export GITHUB_TOKEN=ghp_xxx
python3 main.py --input input.example.json --output-dir output/github-prior-art-search
```

## 輸入

| 欄位 | 必填 | 用途 |
|---|---|---|
| `search_queries` | 是 | 送去 GitHub 的查詢，由呼叫端 agent 設計，腳本原樣執行並附加星數過濾 |
| `project_goal`、`core_features` | 是 | 評分依據 |
| `tech_stack`、`domain`、`architecture_style` | 否 | 評分依據 |
| `exclude_repos`、`max_candidates`、`last_commit_within_days` | 否 | 過濾條件 |
| `min_stars` | 否 | 低於 100 一律強制回升為 100 |

## 輸出

| 檔案 | 內容 |
|---|---|
| `result.json` | 狀態、查詢、候選（含評分／授權／依賴／風險）、建議、警告 |
| `result.md` | 人類可讀報告 |

必要輸入缺失或執行失敗時以非零結束；部分失敗則 `status = "partial"`，
細節記於 `warnings`。

## 測試

```bash
python3 -m pytest tests/ -v
```

## 授權

[MIT](LICENSE)
