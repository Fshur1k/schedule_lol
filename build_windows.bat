@echo off
REM Rift Slate — збірка Windows-версії (RiftSlateUpdater.exe)
REM
REM Що робити:
REM   1. Встанови Python з https://python.org (галочка "Add to PATH" при
REM      встановленні), якщо ще не встановлений.
REM   2. Постав усі файли проєкту (parser.py, run_app.py, rift-slate.html,
REM      requirements.txt, і цей .bat) в одну теку.
REM   3. Двічі клацни цей файл (build_windows.bat) АБО запусти з командного
REM      рядка: build_windows.bat
REM   4. Готовий файл з'явиться в теці dist\RiftSlateUpdater.exe —
REM      його вже можна віддавати людям без Python: просто подвійний клік.

echo ============================================================
echo Rift Slate -- збірка Windows .exe
echo ============================================================

python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [!] Не вдалось встановити залежності. Перевір, що Python встановлено і доданий у PATH.
    pause
    exit /b 1
)

python -m PyInstaller --onefile --name RiftSlateUpdater ^
    --add-data "rift-slate.html;." ^
    run_app.py

if errorlevel 1 (
    echo [!] Збірка не вдалась, дивись повідомлення вище.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Готово! Файл лежить тут: dist\RiftSlateUpdater.exe
echo Можна копіювати цей .exe будь-куди й давати іншим людям --
echo Python їм для запуску не потрібен.
echo ============================================================
pause
