# github-prior-art-search

GitHub 先行調研與重用檢查技能（script-first）。設計規格見上層目錄
《Agent Skill 設計：GitHub Prior Art Search, Script-First Version.md》。

## 快速開始

```bash
# 1. 建立虛擬環境並安裝依賴（首次）
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt

# 2. 依賴檢查（缺任何必要依賴會拒絕並印出安裝指令）
bash scripts/check_dependencies.sh

# 3. 設定 token
export GITHUB_TOKEN=ghp_xxx

# 4. 準備輸入 JSON（格式見 SKILL.md 步驟 3）後執行
.venv/bin/python3 main.py --input input.example.json --output-dir output/github-prior-art-search
```

## 測試

```bash
.venv/bin/python3 -m pytest tests/ -v
```

測試全部離線執行（mock GitHub 回應）；標記 `integration` 的冒煙測試需要
`GITHUB_TOKEN` 且以 `--integration` 啟用。

## 目錄結構

```
github-prior-art-search/
├── SKILL.md              # Agent Skills 標準技能定義
├── main.py               # 主入口（§8 執行流程）
├── config.yaml           # 所有規則資料化：硬性規則／評分權重／授權政策／決策門檻
├── templates/
│   ├── queries.yaml      # §9 查詢模板（由 build_queries() 載入，單一事實來源）
│   └── report.md.jinja2  # §20 報告模板
├── scripts/
│   ├── check_dependencies.sh   # §4 依賴檢查
│   ├── common.py               # 設定、快取 HTTP 客戶端、文字比對
│   ├── search_github.py        # §6 輸入校驗、§9 查詢生成、§10 搜尋過濾
│   ├── parse_license.py        # §11 授權解析
│   ├── parse_dependencies.py   # §12 依賴解析
│   ├── score_candidates.py     # §13 評分模型
│   └── build_recommendation.py # §14 決策規則
├── tests/                # pytest（離線）
└── references/RULES.md   # 規則細節與設計決定
```
