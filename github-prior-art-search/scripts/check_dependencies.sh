#!/usr/bin/env bash
# 技能依賴檢查（§4、§8 步驟 1）。
# 缺少必要依賴時，技能不得執行；本腳本以非零結束並印出安裝指令。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

missing_system=()
missing_python=()

have() { command -v "$1" >/dev/null 2>&1; }

# 優先使用技能目錄內建 venv，其次系統 python3
if [ -x "$SKILL_DIR/.venv/bin/python3" ]; then
  PYTHON="$SKILL_DIR/.venv/bin/python3"
else
  PYTHON="python3"
fi

echo "== github-prior-art-search 依賴檢查 =="
echo "python 解譯器: $PYTHON"

# --- 系統依賴（§4.1）---
for bin in bash git curl jq python3; do
  if have "$bin"; then
    echo "[OK]   $bin"
  else
    echo "[MISS] $bin"
    missing_system+=("$bin")
  fi
done

# --- Python 依賴（§4.2）；spdx-tools 可選 ---
if have "${PYTHON}"; then
  while IFS= read -r mod; do
    mod_name="${mod%%:*}"
    required="${mod##*:}"
    if "$PYTHON" -c "import ${mod_name}" >/dev/null 2>&1; then
      echo "[OK]   python:${mod_name}"
    elif [ "$required" = "optional" ]; then
      echo "[WARN] python:${mod_name} 未安裝（可選，將自動降級）"
    else
      echo "[MISS] python:${mod_name}"
      missing_python+=("$mod_name")
    fi
  done <<'EOF'
requests:required
dateutil:required
packaging:required
yaml:required
jinja2:required
spdx_tools:optional
EOF
fi

if [ ${#missing_system[@]} -eq 0 ] && [ ${#missing_python[@]} -eq 0 ]; then
  echo "== 所有必要依賴齊備 =="
  exit 0
fi

echo ""
echo "缺少以下依賴："
[ ${#missing_system[@]} -gt 0 ] && printf '  系統: %s\n' "${missing_system[*]}"
[ ${#missing_python[@]} -gt 0 ] && printf '  Python: %s\n' "${missing_python[*]}"
echo ""
echo "安裝指令："
if [ ! -x "$SKILL_DIR/.venv/bin/python3" ]; then
  echo "  python3 -m venv \"$SKILL_DIR/.venv\""
  PIP="$SKILL_DIR/.venv/bin/python3 -m pip"
else
  PIP="$PYTHON -m pip"
fi
echo "  $PIP install -r \"$SKILL_DIR/requirements.txt\""
exit 1
