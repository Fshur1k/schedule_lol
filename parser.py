#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rift Slate — парсер розкладу LoL Esports
=========================================

Окремий скрипт, який запускається з командного рядка (НЕ в браузері),
тому на нього не діють обмеження CORS, через які сторінка сама
не може достукатись до Liquipedia / lol.fandom.

Що він робить:
  1. Тягне точний розклад матчів (команди, час, формат Bo1/Bo3/Bo5)
     з публічного фіду Riot: esports-api.lolesports.com — тим самим,
     яким користується сам сайт lolesports.com.
  2. Перевіряє Liquipedia — для турнірів без розкладу від Riot тягне
     хоча б ДАТИ ПРОВЕДЕННЯ (двома незалежними методами, див. нижче).
  3. Перевіряє Leaguepedia (lol.fandom) і ДОПОВНЮЄ інформацію звідти:
     багато регіональних/аматорських турнірів (промоушени, кваліфаєри)
     є на lol.fandom, але їх немає у фіді Riot і немає на Liquipedia.
     За замовчуванням тягне дати з панелі "Current Tournaments"
     (надійний, перевірений метод); є ще опційний Cargo-запит, який
     може додати вже конкретні матчі з часом (--leaguepedia-cargo,
     експериментально — див. коментар біля функції).
  4. Записує все це як JSON прямо у rift-slate.html, у блок
     <script id="match-data" type="application/json">...</script>.
     Відкривши після цього html-файл — побачиш реальні дані,
     без будь-якого сервера чи fetch() у браузері.

Запуск:
    pip install requests
    python parser.py
    python parser.py --html rift-slate.html --liquipedia-pages "World_Championship/2026" "Mid-Season_Invitational/2026"

  Якщо живий запит до Liquipedia/Leaguepedia у твоєму середовищі
  блокується (капча, фаєрвол тощо) — збережи головну сторінку вручну
  в браузері (Ctrl+S → "Webpage, Complete") і згодуй офлайн:
    python parser.py --liquipedia-html-file "Liquipedia.html" --leaguepedia-html-file "Leaguepedia.html"

ВАЖЛИВО про Liquipedia і Leaguepedia:
  Liquipedia просить представлятись описовим User-Agent з контактом —
  заміни LIQUIPEDIA_CONTACT нижче на свій — і не довбати їхні сервери
  частими запитами (витримані затримки між запитами).
  Leaguepedia (Fandom), навпаки, часто БЛОКУЄ (403) саме такі
  "ідентифіковані" User-Agent через Cloudflare — тому там навмисно
  звичайний браузерний рядок (LEAGUEPEDIA_UA). Якщо 403 все одно
  трапляється — надійний обхід: зберегти сторінку вручну в браузері
  і передати через --leaguepedia-html-file.

  Джерела дат турнірів — регекс-парсинг html/вікітексту "як є" станом
  на вересень 2026, писались і перевірялись на збережених копіях
  сторінок, які показав користувач:
    Liquipedia:  метод 1 — точкова сторінка турніру (--liquipedia-pages);
                 метод 2 — панель "Tournaments" на головній.
    Leaguepedia: метод 1 — панель "Current Tournaments" на головній
                 (4 регіональні вкладки), перевірено на реальному знімку;
                 метод 2 — Cargo-запит точних матчів, ЕКСПЕРИМЕНТАЛЬНИЙ,
                 вимкнений за замовчуванням (--leaguepedia-cargo).
  Якщо сайти оновлять розмітку — регулярки доведеться підправити;
  функції повертають порожній список, а не падають, якщо структура
  не збіглась.
"""

import argparse
import calendar
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Потрібен пакет requests: pip install requests")

# ---------------------------------------------------------------------------
# Налаштування
# ---------------------------------------------------------------------------

RIOT_API_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"  # публічний ключ веб-клієнта lolesports.com
RIOT_SCHEDULE_URL = "https://esports-api.lolesports.com/persisted/gw/getSchedule"

LIQUIPEDIA_API = "https://liquipedia.net/leagueoflegends/api.php"
LIQUIPEDIA_CONTACT = "your-email@example.com"  # <-- заміни на свій контакт, цього вимагає ToS Liquipedia
LIQUIPEDIA_UA = f"RiftSlateCalendar/1.0 (contact: {LIQUIPEDIA_CONTACT})"
LIQUIPEDIA_DELAY_SEC = 2.0  # не частіше ніж раз на N секунд між запитами

LEAGUEPEDIA_API = "https://lol.fandom.com/api.php"
# На відміну від Liquipedia, Fandom не публікує вимоги до "описового"
# User-Agent — натомість їхній Cloudflare часто саме БЛОКУЄ (403) запити
# з нестандартним/бото-подібним UA. Тому тут навмисно звичайний
# браузерний рядок, а не власна ідентифікація скрипта.
LEAGUEPEDIA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
LEAGUEPEDIA_HEADERS = {
    "User-Agent": LEAGUEPEDIA_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
LEAGUEPEDIA_DELAY_SEC = 1.0

# ---------------------------------------------------------------------------
# Локальний кеш сторінок — автоматична заміна ручного "збережи через Ctrl+S".
# Щоразу, коли живий запит до Liquipedia/Leaguepedia вдається, сирий HTML
# зберігається сюди. Якщо наступного разу живий запит заблокують (403 тощо),
# скрипт САМ підхоплює останню збережену копію замість --*-html-file —
# і чесно каже, наскільки вона стара. Прапорці --*-html-file лишаються
# робочими для явного ручного перевизначення (напр. інший знімок для тесту).
# ---------------------------------------------------------------------------

CACHE_DIR = Path(__file__).resolve().parent / "cache"


def cache_path(name: str) -> Path:
    return CACHE_DIR / name


def save_to_cache(name: str, html: str):
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        cache_path(name).write_text(html, encoding="utf-8")
    except OSError as e:
        print(f"  [i] Не вдалось зберегти кеш {name}: {e}", file=sys.stderr)


def load_from_cache(name: str):
    """Повертає (html, вік_у_годинах) або (None, None), якщо кешу немає."""
    p = cache_path(name)
    if not p.exists():
        return None, None
    age_hours = (time.time() - p.stat().st_mtime) / 3600
    try:
        return p.read_text(encoding="utf-8", errors="ignore"), age_hours
    except OSError:
        return None, None


TIER_MAP = {
    "worlds": "S", "world championship": "S", "msi": "S", "mid-season invitational": "S",
    "lck": "A", "lpl": "A", "lec": "A", "lta north": "A", "lta south": "A", "lcs": "A", "lta": "A",
    "lco": "B", "ljl": "B", "cblol": "B", "vcs": "B", "tcl": "B", "pcs": "B", "lla": "B", "ljl-jp": "B",
}

# Окремі "іменні" турніри, які не прив'язані до жодної регулярної ліги
# (ексгібішени, міжсезонні кубки, спецпроєкти) — за назвою ліги їх годі
# вгадати через TIER_MAP вище, тож перевіряємо явно, ПЕРШИМИ, до
# основної таблиці. Якщо десь ще трапиться неправильно вгаданий tier —
# просто додай сюди ще один рядок "підрядок назви": "S"/"A"/"B".
TOURNAMENT_TIER_OVERRIDES = {
    "demacia cup": "S",  # великий міжсезонний ексгібішен від LPL, на Liquipedia S-Tier
}


def guess_tier(league_name: str) -> str:
    key = (league_name or "").lower().strip()
    for special, tier in TOURNAMENT_TIER_OVERRIDES.items():
        if special in key:
            return tier
    for k, v in TIER_MAP.items():
        if k in key:
            return v
    return "C"


# ---------------------------------------------------------------------------
# 1. Riot esports feed — точний розклад матчів
# ---------------------------------------------------------------------------

def fetch_riot_schedule(page_token=None):
    params = {"hl": "en-GB"}
    if page_token:
        params["pageToken"] = page_token
    r = requests.get(RIOT_SCHEDULE_URL, headers={"x-api-key": RIOT_API_KEY}, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def collect_riot_matches(max_pages: int = 3):
    """Проходить сторінки розкладу (getSchedule повертає пачками) і збирає матчі."""
    out = []
    token = None
    for page_num in range(max_pages):
        data = fetch_riot_schedule(token)
        events = (data.get("data") or {}).get("schedule", {}).get("events", [])
        for ev in events:
            match = ev.get("match") or {}
            teams = match.get("teams") or []
            strategy = match.get("strategy") or {}
            league_name = (ev.get("league") or {}).get("name", "Unknown League")
            out.append({
                "id": match.get("id") or ev.get("startTime") or f"riot-{len(out)}",
                "league": league_name,
                "tier": guess_tier(league_name),
                "teamA": teams[0]["name"] if len(teams) > 0 else "TBD",
                "teamB": teams[1]["name"] if len(teams) > 1 else "TBD",
                "time": ev.get("startTime"),
                "bestOf": strategy.get("count"),
                "stage": ev.get("blockName") or "",
            })
        token = (data.get("data") or {}).get("schedule", {}).get("pages", {}).get("newer")
        if not token:
            break
        time.sleep(1)
    return out


# ---------------------------------------------------------------------------
# 2a. Liquipedia, метод 1 — точковий запит по сторінці конкретного турніру
# ---------------------------------------------------------------------------

def fetch_liquipedia_upcoming(pages):
    """
    Для кожної переданої сторінки турніру (наприклад "World_Championship/2026")
    тягне вікітекст інфобоксу і намагається витягти дати початку/кінця.
    Матчі туди НЕ входять — тільки сам факт "турнір відбудеться такого-то
    числа", якщо Riot ще не видав по ньому точний розклад матчів.

    Назву сторінки треба знати заздалегідь і вона не завжди очевидна
    (наприклад, Worlds на Liquipedia називається "World_Championship/2026",
    а не "Worlds/2026") — якщо не певен назви, пропусти цей метод і
    покладайся на fetch_liquipedia_tournament_panel() нижче, який сам
    знаходить усі найближчі турніри.
    """
    upcoming = []
    for page in pages:
        params = {
            "action": "parse",
            "page": page,
            "prop": "wikitext",
            "format": "json",
            "redirects": 1,
        }
        headers = {"User-Agent": LIQUIPEDIA_UA}
        try:
            r = requests.get(LIQUIPEDIA_API, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [!] Не вдалось отримати сторінку '{page}': {e}", file=sys.stderr)
            time.sleep(LIQUIPEDIA_DELAY_SEC)
            continue

        if "error" in data:
            reason = data["error"].get("info", data["error"])
            print(f"  [!] Liquipedia: сторінка '{page}' — {reason} (перевір точну назву сторінки)", file=sys.stderr)
            time.sleep(LIQUIPEDIA_DELAY_SEC)
            continue

        wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
        sdate_m = re.search(r"\|\s*sdate\s*=\s*([\d\-]+)", wikitext)
        edate_m = re.search(r"\|\s*edate\s*=\s*([\d\-]+)", wikitext)
        tier_m = re.search(r"\|\s*liquipediatier\s*=\s*(\d+)", wikitext)
        name_m = re.search(r"\|\s*name\s*=\s*(.+)", wikitext)

        if sdate_m:
            upcoming.append({
                "id": "liq-" + page.replace("/", "-"),
                "league": name_m.group(1).strip() if name_m else page,
                "tier": {"1": "S", "2": "A", "3": "B"}.get(tier_m.group(1) if tier_m else "", "C"),
                "startDate": sdate_m.group(1),
                "endDate": edate_m.group(1) if edate_m else sdate_m.group(1),
                "note": "Розклад матчів ще не оголошено",
            })
            print(f"  [✓] {page}: {sdate_m.group(1)} — {edate_m.group(1) if edate_m else sdate_m.group(1)}")
        else:
            print(f"  [i] {page}: дати не знайдені в інфобоксі (можливо, шаблон відрізняється)")

        time.sleep(LIQUIPEDIA_DELAY_SEC)
    return upcoming


# ---------------------------------------------------------------------------
# Спільна утиліта — розбір коротких текстових дат ("Nov 10-13", "Sep", ...)
# Обидва джерела (Liquipedia і Leaguepedia) показують дати турнірів у
# такому самому стислому форматі на своїх головних сторінках.
# ---------------------------------------------------------------------------

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_short_date_range(text, today=None):
    """
    Розпарсити короткий текст дат на кшталт 'Nov 10-13', 'Sep 28 - Oct 12',
    'Oct 02' або навіть просто 'Sep' (коли оголошено тільки місяць).
    Повертає (start_iso, end_iso, is_month_only). Рік вгадується відносно
    поточної дати: якщо вихідна дата давно в минулому (>120 днів),
    припускаємо, що йдеться про наступний рік.
    """
    if today is None:
        today = dt.date.today()
    text = text.replace("–", "-").replace("—", "-").strip()

    m = re.match(
        r'([A-Za-z]{3,9})\s+(\d{1,2})(?:\s*-\s*(?:([A-Za-z]{3,9})\s+)?(\d{1,2}))?\s*$', text
    )
    if m:
        mon1, d1, mon2, d2 = m.groups()
        mon1n = MONTHS.get(mon1[:3].lower())
        if mon1n:
            mon2n = MONTHS.get(mon2[:3].lower()) if mon2 else mon1n
            d2 = d2 or d1

            def build(y, mo, da):
                try:
                    return dt.date(y, mo, int(da))
                except ValueError:
                    return None

            year = today.year
            start = build(year, mon1n, d1)
            if start and (today - start).days > 120:
                year += 1
                start = build(year, mon1n, d1)
            end_year = year if mon2n >= mon1n else year + 1
            end = build(end_year, mon2n, d2)
            if start and end:
                return start.isoformat(), end.isoformat(), False

    # fallback: відомий лише місяць, конкретні дні ще не оголошено
    m2 = re.match(r'([A-Za-z]{3,9})\s*$', text)
    if m2:
        mon = MONTHS.get(m2.group(1)[:3].lower())
        if mon:
            year = today.year
            probe = dt.date(year, mon, 1)
            if (today - probe).days > 120:
                year += 1
            last_day = calendar.monthrange(year, mon)[1]
            start = dt.date(year, mon, 1)
            end = dt.date(year, mon, last_day)
            return start.isoformat(), end.isoformat(), True

    return None, None, False


# ---------------------------------------------------------------------------
# 2b. Liquipedia, метод 2 — панель "Tournaments" на головній сторінці
# ---------------------------------------------------------------------------

def parse_tournament_panel_html(html):
    """
    Витягує список турнірів з блоку "Tournaments" → вкладка "Upcoming"
    на головній сторінці Liquipedia. Розмітка станом на вересень 2026:
    кожен турнір — <div class="tournaments-list-item"> з полями
    __name (посилання+назва), tournament-badge__chip (тір) та __date.
    Якщо розмітку не знайдено — повертає порожній список, без падіння.
    """
    start_idx = html.find(">Tournaments</div>")
    if start_idx == -1:
        return []
    section = html[start_idx:start_idx + 260000]

    up_start = section.find('data-toggle-area-content="1"')
    up_end = section.find('data-toggle-area-content="2"')
    if up_start == -1:
        return []
    upcoming_html = section[up_start: up_end if up_end != -1 else up_start + 150000]

    item_re = re.compile(
        r'tournaments-list-item__name"><a href="([^"]+)"[^>]*>([^<]+)</a>.*?'
        r'tournament-badge__chip">([^<]*)</div>.*?'
        r'tournaments-list-item__date">([^<]+)</div>',
        re.S,
    )

    out = []
    for url, name, tier_text, date_text in item_re.findall(upcoming_html):
        tier_letter = (tier_text or "?").strip()[:1].upper()
        if tier_letter not in ("S", "A", "B", "C"):
            tier_letter = "C"
        start_d, end_d, month_only = _parse_short_date_range(date_text)
        if not start_d:
            continue
        slug = url.rstrip("/").rsplit("/leagueoflegends/", 1)[-1]
        note = "Дата уточнюється (відомий лише місяць)" if month_only else "Розклад матчів ще не оголошено"
        out.append({
            "id": "liq-panel-" + slug.replace("/", "-"),
            "league": name.strip(),
            "tier": tier_letter,
            "startDate": start_d,
            "endDate": end_d,
            "note": note,
        })
    return out


def fetch_liquipedia_tournament_panel(html_file=None, use_cache=True):
    """
    Джерело html для парсингу панелі турнірів:
      - html_file заданий → читаємо локально збережену сторінку
        (Ctrl+S у браузері на liquipedia.net/leagueoflegends/Main_Page) —
        явне ручне перевизначення, найвищий пріоритет;
      - інакше — живий запит до їхнього API (action=parse&page=Main_Page).
        Якщо він вдається — сирий HTML автоматично зберігається в
        cache/liquipedia_main.html (наступного разу це і є "локальна
        версія сайту", яку скрипт сам оновлює щоразу, коли є мережа).
        Якщо запит НЕ вдається (403, немає мережі тощо) і use_cache=True —
        скрипт сам підхоплює цю збережену копію замість падати в порожнечу.
    """
    CACHE_NAME = "liquipedia_main.html"

    if html_file:
        print(f"  (читаю локально збережену сторінку: {html_file})")
        try:
            with open(html_file, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()
        except OSError as e:
            print(f"  [!] Не вдалось прочитати '{html_file}': {e}", file=sys.stderr)
            return []
    else:
        headers = {"User-Agent": LIQUIPEDIA_UA}
        params = {"action": "parse", "page": "Main_Page", "prop": "text", "format": "json"}
        html = None
        try:
            r = requests.get(LIQUIPEDIA_API, params=params, headers=headers, timeout=20)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                print(f"  [!] Liquipedia: {data['error'].get('info', data['error'])}", file=sys.stderr)
            else:
                html = data["parse"]["text"]["*"]
                if use_cache:
                    save_to_cache(CACHE_NAME, html)
        except Exception as e:
            print(f"  [!] Не вдалось отримати Main_Page: {e}", file=sys.stderr)

        if html is None:
            if not use_cache:
                return []
            cached, age_hours = load_from_cache(CACHE_NAME)
            if cached is None:
                print(f"  [i] Кешу теж немає (ще жодного разу не вдавався живий запит).", file=sys.stderr)
                return []
            print(f"  (використовую збережену раніше копію, їй ~{age_hours:.1f} год)")
            html = cached

    items = parse_tournament_panel_html(html)
    for it in items:
        print(f"  [✓] {it['league']} ({it['tier']}-tier): {it['startDate']} — {it['endDate']}")
    return items


# ---------------------------------------------------------------------------
# 3a. Leaguepedia (lol.fandom.com), метод 1 — панель "Current Tournaments"
# ---------------------------------------------------------------------------

def parse_leaguepedia_tournament_panel_html(html):
    """
    Витягує список турнірів з блоку "Current Tournaments" на головній
    сторінці Leaguepedia. Розмітка станом на вересень 2026: чотири
    регіональні вкладки (Americas/EMEA/Asia/International), кожна — своя
    <table class="current-tournaments hoverable-rows"> з секціями-заголовками
    UPCOMING / CURRENT / PAST (<tr class="current-tournaments-header">).
    Беремо тільки рядки з секції UPCOMING: дата-текст у першій <td>,
    посилання+назва турніру у другій. Якщо розмітку не знайдено —
    повертає порожній список, без падіння.
    """
    tables = [m.start() for m in re.finditer(r'<table class="current-tournaments hoverable-rows">', html)]
    if not tables:
        return []

    hdr_re = re.compile(r'<tr class="current-tournaments-header"><th class="colspan-cell" colspan="\d">([A-Z]+)</th></tr>')
    row_re = re.compile(
        r'<tr><td class="">([^<]+)</td><td class="">.*?'
        r'<a href="([^"]+)"[^>]*title="([^"]+)"[^>]*>([^<]+)</a>',
        re.S,
    )

    out = []
    for pos in tables:
        end_pos = html.find("</table>", pos)
        if end_pos == -1:
            continue
        chunk = html[pos:end_pos + len("</table>")]

        hdrs = list(hdr_re.finditer(chunk))
        section_start = section_end = None
        for i, h in enumerate(hdrs):
            if h.group(1) == "UPCOMING":
                section_start = h.end()
                section_end = hdrs[i + 1].start() if i + 1 < len(hdrs) else len(chunk)
                break
        if section_start is None:
            continue
        section = chunk[section_start:section_end]

        for date_text, url, _title, name in row_re.findall(section):
            start_d, end_d, month_only = _parse_short_date_range(date_text)
            if not start_d:
                continue
            name = name.strip()
            slug = url.rstrip("/").rsplit("/wiki/", 1)[-1]
            note = "Дата уточнюється (відомий лише місяць)" if month_only else "Розклад матчів ще не оголошено"
            out.append({
                "id": "lpd-panel-" + slug.replace("/", "-"),
                "league": name,
                "tier": guess_tier(name),
                "startDate": start_d,
                "endDate": end_d,
                "note": note,
            })
    return out


def fetch_leaguepedia_tournament_panel(html_file=None, use_cache=True):
    """
    Так само, як fetch_liquipedia_tournament_panel(), тільки для lol.fandom:
      - html_file заданий → явне ручне перевизначення, найвищий пріоритет;
      - інакше — живий запит; при успіху автоматично зберігається у
        cache/leaguepedia_main.html і оновлюється щоразу заново; при
        невдачі (напр. 403 від Cloudflare) — сам підхоплює цю копію,
        якщо use_cache=True, замість повертати порожній список.
    """
    CACHE_NAME = "leaguepedia_main.html"

    if html_file:
        print(f"  (читаю локально збережену сторінку: {html_file})")
        try:
            with open(html_file, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()
        except OSError as e:
            print(f"  [!] Не вдалось прочитати '{html_file}': {e}", file=sys.stderr)
            return []
    else:
        params = {"action": "parse", "page": "League_of_Legends_Esports_Wiki", "prop": "text", "format": "json"}
        html = None
        try:
            r = requests.get(LEAGUEPEDIA_API, params=params, headers=LEAGUEPEDIA_HEADERS, timeout=20)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                print(f"  [!] Leaguepedia: {data['error'].get('info', data['error'])}", file=sys.stderr)
            else:
                html = data["parse"]["text"]["*"]
                if use_cache:
                    save_to_cache(CACHE_NAME, html)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                print(f"  [!] Leaguepedia повернула 403 (схоже на блокування ботів Cloudflare на боці Fandom).", file=sys.stderr)
            else:
                print(f"  [!] Не вдалось отримати головну сторінку Leaguepedia: {e}", file=sys.stderr)
        except Exception as e:
            print(f"  [!] Не вдалось отримати головну сторінку Leaguepedia: {e}", file=sys.stderr)

        if html is None:
            if not use_cache:
                return []
            cached, age_hours = load_from_cache(CACHE_NAME)
            if cached is None:
                print(f"  [i] Кешу теж немає (ще жодного разу не вдавався живий запит). "
                      f"Обхід: збережи сторінку вручну (Ctrl+S на lol.fandom.com) і передай "
                      f"через --leaguepedia-html-file.", file=sys.stderr)
                return []
            print(f"  (використовую збережену раніше копію, їй ~{age_hours:.1f} год)")
            html = cached

    items = parse_leaguepedia_tournament_panel_html(html)
    for it in items:
        print(f"  [✓] {it['league']} ({it['tier']}-tier): {it['startDate']} — {it['endDate']}")
    return items


# ---------------------------------------------------------------------------
# 3b. Leaguepedia, метод 2 (ЕКСПЕРИМЕНТАЛЬНИЙ) — Cargo-запит точних матчів
# ---------------------------------------------------------------------------
#
# На відміну від методу 1 (перевірявся на реальному знімку сторінки, і
# працює надійно), цей метод писався БЕЗ живого доступу до мережі й без
# змоги перевірити точні назви полів Cargo-таблиці "MatchSchedule".
# Тому він вимкнений за замовчуванням (прапорець --leaguepedia-cargo) —
# спробуй, і якщо побачиш помилку на кшталт "unknown field" в виводі,
# скинь мені цей вивід, підправимо назви полів разом.
#
# Якщо запит вдасться — це дає РЕАЛЬНІ матчі (з часом і форматом Bo1/3/5)
# для регіональних турнірів, яких немає у фіді Riot (напр. промоушени,
# кваліфаєри, аматорські ліги) — тобто саме "доповнення інформації".

def fetch_leaguepedia_matches_cargo(days_ahead: int = 21):
    """Пробує витягти точний розклад матчів з Cargo-таблиці MatchSchedule.
    Повертає список у тому ж форматі, що й collect_riot_matches(). При
    будь-якій помилці — друкує причину і повертає порожній список
    (ніколи не валить весь скрипт)."""
    today = dt.datetime.now(dt.timezone.utc)
    start = today.strftime("%Y-%m-%d %H:%M:%S")
    end = (today + dt.timedelta(days=days_ahead)).strftime("%Y-%m-%d %H:%M:%S")

    params = {
        "action": "cargoquery",
        "format": "json",
        "tables": "MatchSchedule",
        "fields": "Team1,Team2,DateTime_UTC,BestOf,OverviewPage,Tab",
        "where": f'DateTime_UTC >= "{start}" AND DateTime_UTC <= "{end}"',
        "order_by": "DateTime_UTC ASC",
        "limit": "500",
    }
    try:
        r = requests.get(LEAGUEPEDIA_API, params=params, headers=LEAGUEPEDIA_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            print(f"  [!] Leaguepedia Cargo повернула 403 (схоже на блокування ботів Cloudflare на боці Fandom).", file=sys.stderr)
            print(f"       Цей метод експериментальний і без offline-обходу — просто пропусти", file=sys.stderr)
            print(f"       --leaguepedia-cargo цього разу, панель Current Tournaments (метод 1) не постраждала.", file=sys.stderr)
        else:
            print(f"  [!] Cargo-запит до Leaguepedia не вдався: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  [!] Cargo-запит до Leaguepedia не вдався: {e}", file=sys.stderr)
        return []

    if "error" in data:
        print(f"  [!] Leaguepedia Cargo: {data['error'].get('info', data['error'])}", file=sys.stderr)
        print("       (можливо, змінились назви полів MatchSchedule — напиши мені вивід помилки)", file=sys.stderr)
        return []

    out = []
    for row in data.get("cargoquery", []):
        f = row.get("title", {})
        overview = f.get("OverviewPage", "")
        league_name = overview.split("/")[0].strip() if overview else "Unknown League"
        best_of = f.get("BestOf")
        try:
            best_of = int(best_of) if best_of not in (None, "") else None
        except (TypeError, ValueError):
            best_of = None
        out.append({
            "id": "lpd-cargo-" + str(len(out)),
            "league": league_name,
            "tier": guess_tier(league_name),
            "teamA": f.get("Team1") or "TBD",
            "teamB": f.get("Team2") or "TBD",
            "time": (f.get("DateTime_UTC") or "").replace(" ", "T") or None,
            "bestOf": best_of,
            "stage": f.get("Tab") or "",
        })
    out = [m for m in out if m["time"]]
    print(f"  [✓] Cargo: знайдено {len(out)} матчів")
    return out


def merge_matches(riot_matches, extra_matches):
    """Додає матчі з додаткового джерела (напр. Leaguepedia Cargo), уникаючи
    очевидних дублів за парою команд + датою (без часу, з запасом)."""
    seen = {(m["teamA"], m["teamB"], (m.get("time") or "")[:10]) for m in riot_matches}
    seen |= {(m["teamB"], m["teamA"], (m.get("time") or "")[:10]) for m in riot_matches}
    out = list(riot_matches)
    for m in extra_matches:
        key = (m["teamA"], m["teamB"], (m.get("time") or "")[:10])
        if key not in seen:
            out.append(m)
            seen.add(key)
    return out


def drop_upcoming_already_scheduled(upcoming, matches):
    """Якщо по турніру вже є конкретні матчі від Riot — не дублюємо його як 'TBD'."""
    scheduled_leagues = {m["league"] for m in matches}
    return [u for u in upcoming if u["league"] not in scheduled_leagues]


def merge_upcoming(*lists):
    """Об'єднує списки 'upcoming' з різних методів, прибираючи дублі за назвою ліги
    (без урахування регістру). Перший запис з таким іменем перемагає."""
    seen = {}
    for lst in lists:
        for item in lst:
            key = item["league"].strip().lower()
            if key not in seen:
                seen[key] = item
    return list(seen.values())


# ---------------------------------------------------------------------------
# 3. Запис результату прямо у HTML
# ---------------------------------------------------------------------------

def inject_into_html(html_path: str, matches: list, upcoming: list):
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    payload = json.dumps({
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "matches": matches,
        "upcoming": upcoming,
    }, ensure_ascii=False)

    pattern = re.compile(
        r'(<script id="match-data" type="application/json">)(.*?)(</script>)',
        re.S,
    )
    new_html, n = pattern.subn(lambda m: m.group(1) + payload + m.group(3), html)
    if n == 0:
        sys.exit(
            f'[!] У {html_path} не знайдено блок '
            f'<script id="match-data" type="application/json">...</script>. '
            f'Перевір, що редагуєш саме той файл, що йде разом з парсером.'
        )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"[✓] Записано {len(matches)} матчів і {len(upcoming)} турнірів без розкладу у {html_path}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Rift Slate — парсер розкладу LoL Esports")
    ap.add_argument("--html", default="rift-slate.html", help="шлях до HTML-файлу календаря")
    ap.add_argument(
        "--liquipedia-pages", nargs="*",
        default=["World_Championship/2026", "Mid-Season_Invitational/2026"],
        help="сторінки конкретних турнірів на Liquipedia (метод 1, потребує точної назви сторінки)"
    )
    ap.add_argument(
        "--liquipedia-html-file", default=None,
        help="шлях до локально збереженої головної сторінки Liquipedia (офлайн; "
             "Ctrl+S у браузері на liquipedia.net/leagueoflegends/Main_Page)"
    )
    ap.add_argument(
        "--leaguepedia-html-file", default=None,
        help="шлях до локально збереженої головної сторінки Leaguepedia (офлайн; "
             "Ctrl+S у браузері на lol.fandom.com)"
    )
    ap.add_argument("--max-pages", type=int, default=3, help="скільки сторінок розкладу Riot запитувати (пагінація)")
    ap.add_argument("--skip-liquipedia", action="store_true", help="не звертатись до Liquipedia взагалі")
    ap.add_argument("--skip-tournament-panel", action="store_true", help="вимкнути метод 2 Liquipedia (панель Tournaments)")
    ap.add_argument("--skip-tournament-pages", action="store_true", help="вимкнути метод 1 Liquipedia (--liquipedia-pages)")
    ap.add_argument("--skip-leaguepedia", action="store_true", help="не звертатись до Leaguepedia (lol.fandom) взагалі")
    ap.add_argument(
        "--leaguepedia-cargo", action="store_true",
        help="УВІМКНУТИ експериментальний Cargo-запит точних матчів з Leaguepedia "
             "(вимкнено за замовчуванням, бо не перевірено на живій мережі — див. коментар у коді)"
    )
    ap.add_argument("--leaguepedia-days", type=int, default=21, help="вікно днів вперед для --leaguepedia-cargo")
    ap.add_argument(
        "--no-cache", action="store_true",
        help="вимкнути автозбереження/автопідхоплення cache/*.html (за замовчуванням увімкнено — "
             "скрипт сам зберігає сторінки після вдалого живого запиту і сам підхоплює їх, "
             "якщо наступного разу запит заблокують)"
    )
    args = ap.parse_args()
    use_cache = not args.no_cache

    print("→ Отримую розклад матчів з Riot esports feed…")
    try:
        matches = collect_riot_matches(max_pages=args.max_pages)
        print(f"  знайдено {len(matches)} запланованих матчів")
    except Exception as e:
        print(f"  [!] Не вдалось отримати дані з Riot: {e}", file=sys.stderr)
        matches = []

    if args.leaguepedia_cargo:
        print("→ Доповнюю точними матчами з Leaguepedia (Cargo, експериментально)…")
        extra = fetch_leaguepedia_matches_cargo(days_ahead=args.leaguepedia_days)
        before = len(matches)
        matches = merge_matches(matches, extra)
        print(f"  додано {len(matches)-before} нових матчів (дублі за командами+датою відкинуті)")

    upcoming = []
    from_liq_pages, from_liq_panel, from_lpd_panel = [], [], []

    if not args.skip_liquipedia:
        if not args.skip_tournament_pages:
            print("→ Отримую дати проведення турнірів з Liquipedia (метод 1: конкретні сторінки)…")
            from_liq_pages = fetch_liquipedia_upcoming(args.liquipedia_pages)
        if not args.skip_tournament_panel:
            print("→ Отримую дати проведення турнірів з Liquipedia (метод 2: панель Tournaments)…")
            from_liq_panel = fetch_liquipedia_tournament_panel(html_file=args.liquipedia_html_file, use_cache=use_cache)

    if not args.skip_leaguepedia:
        print("→ Перевіряю Leaguepedia (lol.fandom) — панель Current Tournaments…")
        from_lpd_panel = fetch_leaguepedia_tournament_panel(html_file=args.leaguepedia_html_file, use_cache=use_cache)

    upcoming = merge_upcoming(from_liq_pages, from_liq_panel, from_lpd_panel)
    upcoming = drop_upcoming_already_scheduled(upcoming, matches)
    print(f"  разом {len(upcoming)} турнірів без детального розкладу (решта вже покрита матчами)")

    inject_into_html(args.html, matches, upcoming)


if __name__ == "__main__":
    main()