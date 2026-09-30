# github-prior-art-search

[English](README.md) ｜ [繁體中文](README.zh-TW.md)

GitHub 先行調研與重用檢查 Agent Skill，遵循 [Agent Skills](https://agentskills.io)
標準（`SKILL.md`）。僅需 Python 3.9+ 標準庫。

## 運作方式

| 階段 | 負責 | 產物 |
|---|---|---|
| 1. 把需求拆成功能組件 | 模型 | `input.json` 的 `components` |
| 2. 為每個組件設計比對詞與查詢 | 模型 | `match_terms`、`search_queries` |
| 3. 搜尋、硬性過濾、收集事實、設定每個倉庫的可採用上限 | 腳本（`search`） | `result.json`、`result.md` |
| 4. 回到原需求逐組件判斷適配 | 模型 | `assessment.json` |
| 5. 驗證判斷並產出最終報告 | 腳本（`finalize`） | `final.json`、`final.md` |

硬性規則由腳本強制：星數 ≥ 100、排除 archived／disabled，並依授權、維護活躍度、
依賴風險為每個倉庫設定 `cap`。模型的判斷若選了組件候選以外的倉庫、超過上限，
或沒有交代每一條 `must_have`，`finalize` 會拒絕。

## 安裝

以 OpenCode 指令調用：

```bash
cp command/github-search.md ~/.config/opencode/command/
```

技能本體需安裝於 `~/.config/opencode/skills/github-prior-art-search/`，
之後以 `/github-search <需求描述>` 調用。

## 執行

```bash
export GITHUB_TOKEN=ghp_xxx
python3 main.py search --input input.example.json --dry-run
python3 main.py search --input input.example.json --output-dir out
python3 main.py search --input input.example.json --output-dir out --only redis-store
python3 main.py finalize --assessment assessment.json --output-dir out
```

格式見 `input.example.json` 與 `assessment.example.json`，完整欄位規則見 `SKILL.md`。

## 測試

```bash
python3 -m pytest tests/ -v
```

測試以假的 GitHub 離線執行。

## 授權

[MIT](LICENSE)
