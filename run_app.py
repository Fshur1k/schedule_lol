#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rift Slate — простий запускач для людей без досвіду програмування.

Один запуск (подвійний клік по .exe на Windows або по програмі на Mac):
  1. Якщо поруч ще немає rift-slate.html — створює його з вбудованого шаблону
     (перший запуск "розпаковує" сторінку).
  2. Якщо поруч лежить liquipedia_manual.html і/або leaguepedia_manual.html
     (вручну збережена сторінка через Ctrl+S у браузері) — використовує
     ЇХ замість живого запиту до відповідного сайту. Немає такого файлу —
     тягне з мережі як завжди. Це рятує, коли Liquipedia/Leaguepedia
     блокують запити (403 тощо).
  3. Оновлює дані в rift-slate.html — той самий Riot + Liquipedia +
     Leaguepedia парсинг, що й у parser.py, викликаний напряму.
  4. Відкриває оновлену сторінку в браузері за замовчуванням.
  5. Чекає Enter перед закриттям — інакше на Windows консольне вікно
     закривається одразу і людина не встигає прочитати, що сталось.

Це той самий файл, з якого PyInstaller збирає RiftSlateUpdater.exe /
RiftSlateUpdater (Mac) — див. build_windows.bat / build_mac.sh поруч.
Його так само можна запускати і напряму через `python run_app.py`.
"""

import sys
import traceback
import webbrowser
from pathlib import Path

import parser as rift_parser  # той самий parser.py, що лежить поруч цього файлу

# Назви файлів, які людина може вручну покласти поруч із програмою, щоб
# підсунути власний знімок сторінки замість живого запиту до сайту.
LIQUIPEDIA_MANUAL_FILE = "liquipedia_manual.html"
LEAGUEPEDIA_MANUAL_FILE = "leaguepedia_manual.html"


def app_dir() -> Path:
    """Тека, де лежить сама програма — саме сюди пишемо rift-slate.html і
    кеш сторінок, а НЕ у тимчасову теку розпакування PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundle_dir() -> Path:
    """Тека, звідки PyInstaller дає доступ до вбудованих файлів-шаблонів
    (--add-data). У звичайному запуску python run_app.py — це та сама
    тека, що й app_dir()."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def ensure_html_copy(target_dir: Path) -> Path:
    target = target_dir / "rift-slate.html"
    if not target.exists():
        template = bundle_dir() / "rift-slate.html"
        target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Створив {target.name} поруч із програмою (перший запуск).")
    return target


def find_manual_file(target_dir: Path, filename: str):
    """Повертає шлях до вручну покладеного файлу поруч із програмою, якщо
    він там є, інакше None (тоді функції parser.py самі підуть у мережу)."""
    p = target_dir / filename
    if p.exists():
        print(f"  (знайдено {filename} поруч із програмою — використовую його замість живого запиту)")
        return str(p)
    return None


def main():
    d = app_dir()
    html_path = ensure_html_copy(d)

    # Кеш сторінок (для автопідхоплення при 403/блокуваннях) має жити
    # поруч із програмою, а не в тимчасовій теці PyInstaller, яка щоразу
    # видаляється після закриття .exe — інакше кеш був би марним.
    rift_parser.CACHE_DIR = d / "cache"

    print("=" * 60)
    print("Rift Slate — оновлення календаря матчів LoL Esports")
    print("=" * 60)

    matches, upcoming = [], []
    try:
        print("\n→ Отримую розклад матчів з Riot esports feed…")
        matches = rift_parser.collect_riot_matches()
        print(f"  знайдено {len(matches)} запланованих матчів")

        print("\n→ Отримую дати турнірів з Liquipedia…")
        liq_manual = find_manual_file(d, LIQUIPEDIA_MANUAL_FILE)
        from_liq_pages = rift_parser.fetch_liquipedia_upcoming(
            ["World_Championship/2026", "Mid-Season_Invitational/2026"]
        )
        from_liq_panel = rift_parser.fetch_liquipedia_tournament_panel(html_file=liq_manual)

        print("\n→ Перевіряю Leaguepedia (lol.fandom)…")
        lpd_manual = find_manual_file(d, LEAGUEPEDIA_MANUAL_FILE)
        from_lpd_panel = rift_parser.fetch_leaguepedia_tournament_panel(html_file=lpd_manual)

        upcoming = rift_parser.merge_upcoming(from_liq_pages, from_liq_panel, from_lpd_panel)
        upcoming = rift_parser.drop_upcoming_already_scheduled(upcoming, matches)

        rift_parser.inject_into_html(str(html_path), matches, upcoming)
        print(f"\n✓ Готово! Записано {len(matches)} матчів і {len(upcoming)} турнірів у {html_path.name}")

    except Exception:
        print("\n[!] Під час оновлення сталася помилка:")
        traceback.print_exc()
        print("\nВідкрию сторінку з тими даними, що вже є (можуть бути старі).")

    webbrowser.open(html_path.as_uri())
    input("\nНатисни Enter, щоб закрити це вікно…")


if __name__ == "__main__":
    main()
