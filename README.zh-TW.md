# github-prior-art-search

[English](README.md) ｜ [繁體中文](README.zh-TW.md)

GitHub **先行調研與重用檢查** Agent Skill。動手開發之前，先找出 GitHub 上
值得直接採用為依賴、fork 改造、或作為架構參考的既有專案——不要重造輪子。

本技能遵循 [Agent Skills](https://agentskills.io) 標準（`SKILL.md`），
可安裝於 OpenCode、Claude Code 等支援技能的 coding agent。

## 為什麼是 script-first

以 LLM 主導的研究對硬性條件不可靠。本技能將所有決策放進確定性的腳本；
模型只能在受限 schema 下產生文字摘要：

| 硬性規則 | 執行方式 |
|---|---|
| 忽略星數 < 100 的倉庫 | 腳本強制過濾，模型不得調降門檻 |
| 忽略 archived / disabled 倉庫 | 腳本強制過濾 |
| 無授權的倉庫不得「直接採用」 | 降級為 reference-only，風險等級 high |
| Copyleft 授權須人工複審 | 腳本標記 |
| 評分與重用決策 | 六維度加權評分由程式碼計算 |
| 模型輸出 | 僅文字摘要；不得新增/刪除候選、更改排序或覆寫決策 |

評分權重、授權政策、依賴風險門檻與決策閘門都放在 `config.json`，不改程式碼
即可稽核與調整；星數門檻與 archived/disabled 過濾則刻意寫死在
`scripts/search_github.py`，不開放設定。

**零第三方依賴**：僅需 Python 3.9+ 標準庫——無需 pip / venv。

## 快速開始

### 以 OpenCode 指令調用（建議）

將指令檔複製到全域指令目錄：

```bash
cp command/github-search.md ~/.config/opencode/command/
```

之後在任何專案輸入 `/github-search <專案目標 + 核心功能 + 技術堆疊>` 即可，
例如：`/github-search 遊戲活動配置後台，活動配置／獎勵發放，TypeScript Node.js`。

技能本體也需安裝於全域（`~/.config/opencode/skills/github-prior-art-search/`）。

### 手動執行

```bash
export GITHUB_TOKEN=ghp_xxx
python3 main.py --input input.example.json --output-dir output/github-prior-art-search
```

腳本會自行檢查 Python 版本與 `GITHUB_TOKEN`，任一缺失即以非零結束並印出原因。

輸入必填 `project_goal` 與 `core_features`；選填欄位包括 `tech_stack`、
`domain`、`architecture_style`、`exclude_repos`、`extra_keywords`、
`max_candidates`、`last_commit_within_days`、`min_stars`（低於 100 一律強制
回升為 100）。

輸出目錄會產生兩個檔案：

| 檔案 | 內容 |
|---|---|
| `result.json` | 完整結果：狀態、查詢、候選（含評分／授權／依賴／風險）、建議、警告 |
| `result.md` | 人類可讀報告 |

必要輸入缺失或執行失敗時以非零結束；部分失敗則 `status = "partial"`，
細節記於 `warnings`。

## 運作方式

1. 校驗輸入並套用硬性規則（星數門檻 ≥ 100）。
2. 依模板（`templates/queries.json`）產生查詢，展開目標／領域／功能／技術堆疊
   佔位符（多值採笛卡兒積）。
3. 呼叫 GitHub Search API（處理 rate limit，額度耗盡即提早停止）。
4. 本地二次過濾：星數、archived/disabled、黑名單、最後提交時間。
5. 對前 N 名候選深度分析：檔案樹、README、授權辨識、依賴清單與 lockfile、release。
6. 六維度評分（相關度、重用性、維護活躍度、程式碼品質、文件、授權契合）後
   決策：adopt／fork／use-as-template／reference-only／build-in-house。

評分訊號與決策門檻的細節見 [references/RULES.md](references/RULES.md)。

## 測試

```bash
python3 -m pytest tests/ -v   # pytest 僅為開發／測試依賴
```

所有測試離線執行，對 GitHub 回應使用 mock。

## 專案結構

```
├── SKILL.md              # Agent Skills 標準定義
├── main.py               # 進入點與流程編排
├── config.json           # 權重、授權政策、依賴風險、決策門檻
├── templates/
│   └── queries.json      # 查詢模板
├── scripts/
│   ├── common.py               # 設定、HTTP 客戶端（urllib）、文字比對
│   ├── search_github.py        # 輸入校驗、查詢生成、搜尋與過濾
│   ├── analyze.py              # 單一候選深度分析
│   ├── parse_license.py        # 授權解析與分類
│   ├── parse_dependencies.py   # 依賴清單解析
│   ├── score_candidates.py     # 評分模型
│   ├── build_recommendation.py # 決策規則
│   └── render_report.py        # result.json / result.md 輸出
├── tests/                # pytest（離線）
└── references/RULES.md   # 規則細節與設計決定
```

## 授權

[MIT](LICENSE)
