# github-prior-art-search

GitHub 先行調研與重用檢查技能（script-first）。

**零第三方依賴**：僅需 Python 3.9+ 與 bash，全部使用標準庫，
無需 pip / venv。

## 快速開始

```bash
# 1. 依賴檢查（缺任何必要依賴會拒絕並印出原因）
bash scripts/check_dependencies.sh

# 2. 設定 token
export GITHUB_TOKEN=ghp_xxx

# 3. 準備輸入 JSON（格式見 SKILL.md 步驟 3）後執行
python3 main.py --input input.example.json --output-dir output/github-prior-art-search
```

## 測試

```bash
python3 -m pytest tests/ -v   # pytest 僅為開發/測試用依賴
```

測試全部離線執行（mock GitHub 回應）；標記 `integration` 的冒煙測試需要
`GITHUB_TOKEN` 且以 `--integration` 啟用。

## 目錄結構

```
github-prior-art-search/
├── SKILL.md              # Agent Skills 標準技能定義
├── main.py               # 主入口（§8 執行流程）＋報告渲染（§20）
├── config.json           # 所有規則資料化：硬性規則／評分權重／授權政策／決策門檻
├── templates/
│   └── queries.json      # §9 查詢模板（由 build_queries() 載入，單一事實來源）
├── scripts/
│   ├── check_dependencies.sh   # §4 依賴檢查（僅 bash + Python 3.9+）
│   ├── common.py               # 設定、快取 HTTP 客戶端、文字比對（urllib）
│   ├── search_github.py        # §6 輸入校驗、§9 查詢生成、§10 搜尋過濾
│   ├── parse_license.py        # §11 授權解析
│   ├── parse_dependencies.py   # §12 依賴解析
│   ├── score_candidates.py     # §13 評分模型
│   └── build_recommendation.py # §14 決策規則
├── tests/                # pytest（離線）
└── references/RULES.md   # 規則細節與設計決定
```
