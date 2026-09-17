#!/bin/bash
# Rift Slate — збірка Mac-версії (RiftSlateUpdater)
#
# Що робити:
#   1. Встанови Python 3, якщо ще немає: https://python.org або `brew install python3`
#   2. Постав усі файли проєкту (parser.py, run_app.py, rift-slate.html,
#      requirements.txt, і цей .sh) в одну теку.
#   3. У терміналі: chmod +x build_mac.sh && ./build_mac.sh
#   4. Готовий файл з'явиться в теці dist/RiftSlateUpdater —
#      його вже можна віддавати іншим людям з Mac: подвійний клік
#      (перший раз, можливо, доведеться дозволити запуск через
#      Системні налаштування -> Конфіденційність і безпека, бо файл
#      без Apple-підпису — це нормально для власноруч зібраних програм).

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "============================================================"
echo "Rift Slate -- збірка Mac-версії"
echo "============================================================"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[!] Не знайдено $PYTHON_BIN. Встанови Python 3 з https://python.org" >&2
  exit 1
fi

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements.txt pyinstaller

"$PYTHON_BIN" -m PyInstaller --onefile --name RiftSlateUpdater \
  --add-data "rift-slate.html:." \
  run_app.py

echo ""
echo "============================================================"
echo "Готово! Файл лежить тут: dist/RiftSlateUpdater"
echo "Можна копіювати його будь-куди й давати іншим людям з Mac --"
echo "Python їм для запуску не потрібен."
echo "============================================================"
