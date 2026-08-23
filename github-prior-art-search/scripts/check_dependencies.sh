#!/usr/bin/env bash
# 技能依賴檢查（§4、§8 步驟 1）。
# 本技能零第三方套件：僅需 Python 3.9+ 與 bash，無需 pip 安裝。
# 缺少必要依賴時，技能不得執行；本腳本以非零結束並印出原因。
set -uo pipefail

missing=()

have() { command -v "$1" >/dev/null 2>&1; }

echo "== github-prior-art-search 依賴檢查 =="
echo "python 解譯器: $(command -v python3 || echo 未找到)"

# --- 系統依賴（§4.1）---
if have python3; then
  echo "[OK]   python3"
else
  echo "[MISS] python3"
  missing+=("python3")
fi

if have bash; then
  echo "[OK]   bash"
else
  echo "[MISS] bash"
  missing+=("bash")
fi

# --- Python 版本 >= 3.9（§4.2）---
if have python3 && ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
  echo "[MISS] python3 版本需 >= 3.9（目前：$(python3 -V 2>&1)）"
  missing+=("python3>=3.9")
fi

# --- 網路連線（api.github.com 於執行時仍可能失敗，此處僅提示）---
if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "[WARN] 環境變數 GITHUB_TOKEN 未設定（步驟 2 將強制檢查）"
else
  echo "[OK]   GITHUB_TOKEN 已設定"
fi

if [ ${#missing[@]} -eq 0 ]; then
  echo "== 所有必要依賴齊備（僅標準庫，無需 pip 安裝）=="
  exit 0
fi

echo ""
echo "缺少以下依賴：${missing[*]}"
echo "本技能僅使用 Python 標準庫，安裝 Python 3.9+ 後即可執行。"
exit 1
