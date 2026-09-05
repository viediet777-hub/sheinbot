"""
Firebase StockGro Refer Telegram Bot
====================================
User submits their Firebase (URL + key), everything else is automatic:
  check number -> send OTP -> auto-read OTP from Firebase -> register.

  * Serial queue: only ONE user is processed at a time, rest wait in queue.
  * Firebase Checker: see active/inactive, device count, online count,
    numbers per Firebase BEFORE submitting.
  * Refer system: 1 referral = 2 points | 1 Firebase submission = 1 point.
    Points are deducted when the Firebase is accepted into queue.
  * Force-join channel + admin panel + colored buttons.

Install:  pip install python-telegram-bot>=22.7 requests PySocks
Run:      python firebase_refer_bot.py   (needs its OWN bot token)
Railway:  separate service with start command: python firebase_refer_bot.py
"""

import asyncio
import logging
import os
import random
import re
import sqlite3
import time
import json
import urllib.parse
from collections import deque
from datetime import datetime
from pathlib import Path

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

# ============================ CONFIG ============================
BOT_TOKEN = os.getenv("BOT_TOKEN_FB", os.getenv("BOT_TOKEN", ""))


def _parse_admins() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "1364476174")
    ids: set[int] = set()
    for part in raw.replace(",", " ").split():
        try:
            ids.add(int(part.strip()))
        except ValueError:
            pass
    return ids or {1364476174}


ADMIN_IDS = _parse_admins()
BOT_USERNAME_FALLBACK = os.getenv("BOT_USERNAME_FB", "@Stockgrorefer_bot")

DEFAULT_STOCKGRO_CODE = os.getenv("DEFAULT_STOCKGRO_CODE", "") or ""
DEFAULT_FORCE_CHANNEL = os.getenv("FORCE_CHANNEL", "@viedietlooters")
DEFAULT_FORCE_LINK = os.getenv("FORCE_CHANNEL_LINK", "https://t.me/viedietlooters")

POINTS_PER_REFER = int(os.getenv("POINTS_PER_REFER_FB", "2"))
COST_PER_JOB = int(os.getenv("COST_PER_JOB", "1"))
BONUS_ON_START = int(os.getenv("BONUS_ON_START_FB", "1"))
MAX_NUMBERS_PER_JOB = int(os.getenv("MAX_NUMBERS_PER_JOB", "0"))  # 0 = no limit, all fresh numbers
OTP_TIMEOUT = int(os.getenv("OTP_TIMEOUT", "40"))
SPAM_COOLDOWN_SEC = 1.5

STYLE_PRIMARY = "primary"
STYLE_SUCCESS = "success"
STYLE_DANGER = "danger"
ICON_BLUE = "5373141891321699086"
ICON_RED = "5370810157871667232"
ICON_GREEN = "5471984997361523302"
ICON_OFFERS = "5359664288241829619"
ICON_CANCEL = "5382224089295365367"
ICON_RENEW = "5891063600885273198"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "firebase_bot.db"
MAIN_DB_PATH = BASE_DIR / "stockgro_bot.db"  # shared numbers table
REFER_FILE = BASE_DIR / "refer.txt"
USED_NUMBERS_FILE = BASE_DIR / "usednumbers.txt"

BASE_URL = "https://accounts.stockgro.club/api"

FIRST_NAMES = ["Vishal", "Rahul", "Amit", "Rohan", "Priya", "Neha", "Ankit", "Saurav",
               "Vikas", "Manish", "Karan", "Pooja", "Deepak", "Aman", "Ravi", "Sachin",
               "Aditya", "Yash", "Nitin", "Rohit", "Sameer", "Gaurav", "Varun", "Abhishek",
               "Sneha", "Kavita", "Ritu", "Megha", "Shweta", "Anjali", "Divya", "Sonam"]
LAST_NAMES = ["Sharma", "Verma", "Singh", "Kumar", "Gupta", "Joshi", "Mehta", "Patel",
              "Yadav", "Chauhan", "Mishra", "Pandey", "Rajput", "Rathore", "Agarwal", "Bansal",
              "Malhotra", "Kapoor", "Saxena", "Saini", "Goyal", "Tiwari", "Deshmukh", "Reddy"]

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
log = logging.getLogger("firebase-bot")

_last_msg_time: dict[int, float] = {}
_last_attempt_time: dict[int, float] = {}
_JOIN_CACHE: dict[int, float] = {}
JOIN_CACHE_TTL = 300

# ============================ PROXY (StockGro + Firebase) ============================
PROXY_MODE = os.getenv("PROXY_MODE", "auto")
PROXY_FILE = BASE_DIR / "proxies.txt"
_PROXY_POOL: list[str] | None = None


def _split_proxy_source(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,\n]+", raw)
            if p.strip() and not p.strip().startswith("#")]


def _proxy_has_auth(entry: str) -> bool:
    e = (entry or "").strip()
    if "@" in e:
        return True
    if "://" not in e and e.count(":") == 3:  # host:port:user:pass
        return True
    return False


def load_proxy_pool() -> list[str]:
    global _PROXY_POOL
    if _PROXY_POOL is not None:
        return _PROXY_POOL
    entries: list[str] = []
    env_raw = os.getenv("PROXIES", "").strip()
    if env_raw:
        entries = _split_proxy_source(env_raw)
    elif PROXY_FILE.exists():
        try:
            entries = _split_proxy_source(PROXY_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("could not read proxies.txt: %s", e)
    # reliable (paid/auth) proxies first, free ones last
    entries.sort(key=lambda e: 0 if _proxy_has_auth(e) else 1)
    _PROXY_POOL = entries
    log.info("proxy pool loaded: %d entries", len(entries))
    return entries


def proxy_to_url(entry: str) -> str | None:
    e = (entry or "").strip()
    if not e:
        return None
    if "://" in e:
        return e
    parts = e.split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        return f"http://{user}:{pwd}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{e}"
    return None


def proxy_label(entry: str | None) -> str:
    try:
        url = proxy_to_url(entry or "") or ""
        scheme = url.split("://")[0] if "://" in url else "http"
        host = url.split("://", 1)[-1]
        if "@" in host:
            host = host.split("@", 1)[-1]
        return f"{scheme}://{host}" if host else "direct"
    except Exception:
        return "proxy"


def pick_proxy() -> str | None:
    if PROXY_MODE == "off":
        return None
    pool = load_proxy_pool()
    if not pool:
        return None
    auth = [e for e in pool if _proxy_has_auth(e)]
    return random.choice(auth or pool)  # paid/auth proxies preferred


def proxy_alive(entry: str | None, timeout: int = 8) -> bool:
    """Fast healthcheck: can this route reach StockGro at all?"""
    try:
        r = requests.get("https://app.stockgro.club", headers={
            "user-agent": "Mozilla/5.0 (Linux; Android 14; SM-A135F) AppleWebKit/537.36 "
                          "Chrome/151.0.7922.169 Mobile Safari/537.36"},
            timeout=timeout, proxies=proxy_dicts(entry))
        return r.status_code == 200
    except Exception:
        return False


def ensure_proxy(preferred: str | None) -> str | None:
    """Validate the job's proxy; fail over to other pool entries, else direct.
    A dead proxy used to kill the whole job with 0 success."""
    if PROXY_MODE == "off":
        return None
    tried = set()
    candidates = [preferred] if preferred else []
    candidates += [e for e in load_proxy_pool() if e != preferred]
    for entry in candidates[:4]:
        if entry in tried:
            continue
        tried.add(entry)
        if proxy_alive(entry):
            if entry != preferred:
                log.info("proxy failover: %s -> %s", proxy_label(preferred), proxy_label(entry))
            return entry
        log.warning("dead proxy skipped: %s", proxy_label(entry))
    log.warning("no working proxy, falling back to direct")
    return None


def proxy_dicts(entry: str | None) -> dict | None:
    if not entry:
        return None
    url = proxy_to_url(entry)
    if not url:
        return None
    return {"http": url, "https": url}


# ============================ DB ============================
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def main_db():
    con = sqlite3.connect(MAIN_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def normalize_channel(inp: str) -> str:
    s = (inp or "").strip()
    if not s:
        return s
    if s.startswith("-100") or s.startswith("-"):
        return s
    m = re.search(r"t\.me/(?:joinchat/|\+)?([A-Za-z0-9_]+)", s)
    if m:
        return "@" + m.group(1)
    s = s.replace("@", "")
    if re.fullmatch(r"[A-Za-z0-9_]{5,64}", s):
        return "@" + s
    return (inp or "").strip()


def channel_link_for(chat_id: str, saved_link: str = "") -> str:
    if saved_link and saved_link.startswith("http"):
        return saved_link
    if chat_id.startswith("@"):
        return "https://t.me/" + chat_id[1:]
    return saved_link or DEFAULT_FORCE_LINK


def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            points INTEGER DEFAULT 0,
            total_refers INTEGER DEFAULT 0,
            stockgro_code TEXT,
            referred_by INTEGER,
            joined_at TEXT
        )""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            created_at TEXT
        )""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS channels(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE,
            link TEXT
        )""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            fb_host TEXT,
            numbers_tried INTEGER DEFAULT 0,
            numbers_success INTEGER DEFAULT 0,
            status TEXT,
            created_at TEXT
        )""")
    cur.execute("DELETE FROM channels WHERE chat_id IN ('@viedietloots','viedietloots')")
    cur.execute("INSERT OR IGNORE INTO channels(chat_id, link) VALUES(?,?)",
                (DEFAULT_FORCE_CHANNEL, DEFAULT_FORCE_LINK))
    cur.execute("UPDATE channels SET link=? WHERE chat_id=?",
                (DEFAULT_FORCE_LINK, DEFAULT_FORCE_CHANNEL))
    try:
        cur.execute("UPDATE users SET stockgro_code=? WHERE stockgro_code IS NULL OR stockgro_code=''",
                    (DEFAULT_STOCKGRO_CODE,))
    except Exception:
        pass
    con.commit()
    con.close()


def get_user(uid: int):
    con = db()
    row = con.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return row


def credit_referral(referrer_id: int, referred_id: int) -> bool:
    if not referrer_id or referrer_id == referred_id:
        return False
    con = db()
    try:
        if con.execute("SELECT 1 FROM referrals WHERE referred_id=?", (referred_id,)).fetchone():
            return False
        if not con.execute("SELECT 1 FROM users WHERE user_id=?", (referrer_id,)).fetchone():
            return False
        con.execute("INSERT INTO referrals(referrer_id, referred_id, created_at) VALUES(?,?,?)",
                    (referrer_id, referred_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        con.execute("UPDATE users SET points = points + ?, total_refers = total_refers + 1 WHERE user_id=?",
                    (POINTS_PER_REFER, referrer_id))
        con.commit()
        log.info("Referral credited: %s -> %s (+%s pts)", referrer_id, referred_id, POINTS_PER_REFER)
        return True
    finally:
        con.close()


def credit_pending_referrals(uid: int) -> int:
    con = db()
    rows = con.execute("SELECT user_id FROM users WHERE referred_by=?", (uid,)).fetchall()
    con.close()
    n = 0
    for r in rows:
        try:
            if credit_referral(uid, r["user_id"]):
                n += 1
        except Exception as e:
            log.warning("pending credit fail %s: %s", r["user_id"], e)
    return n


def ensure_user(uid: int, username: str = "", first_name: str = "", referred_by: int | None = None):
    """Returns (is_new, referral_credited_now)."""
    con = db()
    row = con.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if row:
        con.close()
        return False, False
    con.execute(
        "INSERT INTO users(user_id, username, first_name, points, total_refers, stockgro_code, referred_by, joined_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (uid, username or "", first_name or "", BONUS_ON_START, 0,
         DEFAULT_STOCKGRO_CODE, referred_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()
    credited = False
    if referred_by and referred_by != uid:
        credited = credit_referral(referred_by, uid)
    return True, credited


def deduct_job_point(uid: int) -> bool:
    con = db()
    row = con.execute("SELECT points FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row or row["points"] < COST_PER_JOB:
        con.close()
        return False
    con.execute("UPDATE users SET points = points - ? WHERE user_id=?", (COST_PER_JOB, uid))
    con.commit()
    con.close()
    return True


def set_stockgro_code(uid: int, code: str):
    con = db()
    con.execute("UPDATE users SET stockgro_code=? WHERE user_id=?", (code, uid))
    con.commit()
    con.close()


def record_job(uid: int, host: str, tried: int, success: int, status: str):
    con = db()
    con.execute("INSERT INTO jobs(user_id, fb_host, numbers_tried, numbers_success, status, created_at)"
                " VALUES(?,?,?,?,?,?)",
                (uid, host, tried, success, status,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()


def get_channels() -> list[dict]:
    con = db()
    rows = con.execute("SELECT * FROM channels ORDER BY id").fetchall()
    con.close()
    return [dict(r) for r in rows]


# ---- shared numbers (same source of truth as the main bot) ----
def is_number_used(phone: str) -> bool:
    try:
        if MAIN_DB_PATH.exists():
            con = main_db()
            row = con.execute("SELECT * FROM numbers WHERE phone=?", (phone,)).fetchone()
            con.close()
            if row:
                return True
    except Exception:
        pass
    try:
        if USED_NUMBERS_FILE.exists():
            for line in USED_NUMBERS_FILE.read_text().splitlines():
                if line.strip() == phone:
                    return True
    except Exception:
        pass
    return False


def save_success(phone: str, uid: int, display_name: str, sg_user_id: str, refcode: str):
    try:
        if MAIN_DB_PATH.exists():
            con = main_db()
            con.execute("INSERT OR REPLACE INTO numbers(phone, user_id, display_name, stockgro_user_id, status, created_at)"
                        " VALUES(?,?,?,?,?,?)",
                        (phone, uid, display_name, sg_user_id, "success",
                         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            con.commit()
            con.close()
    except Exception as e:
        log.warning("main db save fail: %s", e)
    try:
        with open(USED_NUMBERS_FILE, "a") as f:
            f.write(f"{phone}\n")
        with open(REFER_FILE, "a") as f:
            f.write(f"{phone} | RefCode: {refcode} | Name: {display_name} | "
                    f"UserID: {sg_user_id} | ByTG: {uid} | Time: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    except Exception as e:
        log.warning("file save fail: %s", e)


# ============================ STOCKGRO API ============================
_STATE_CACHE = {"state": None, "ts": 0.0}
STATE_TTL_SEC = 60
_SENTINEL = object()


def get_server_state(force: bool = False, proxy=_SENTINEL) -> tuple[str | None, str | None]:
    if proxy is _SENTINEL:
        proxy = pick_proxy()
    px = proxy_dicts(proxy)
    tag = proxy_label(proxy) if proxy else "direct"
    now = time.time()
    if not force and _STATE_CACHE["state"] and now - _STATE_CACHE["ts"] < STATE_TTL_SEC:
        return _STATE_CACHE["state"], None
    last_err = "unknown error"
    for attempt in range(3):
        try:
            res = requests.get("https://app.stockgro.club", headers={
                "user-agent": "Mozilla/5.0 (Linux; Android 14; SM-A135F) AppleWebKit/537.36 Chrome/151.0.7922.169 Mobile Safari/537.36",
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
                timeout=15, proxies=px)
            if res.status_code == 200:
                m = re.search(r"state=([^&\"]+)", res.text)
                if m:
                    st = urllib.parse.unquote(m.group(1))
                    _STATE_CACHE.update(state=st, ts=time.time())
                    return st, None
                last_err = "HTTP 200 but no state token found"
            else:
                last_err = f"HTTP {res.status_code} from StockGro server"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:150]}"
        log.warning("state attempt %d via %s failed: %s", attempt + 1, tag, last_err)
        time.sleep(1.5 * (attempt + 1))
    return None, f"{last_err} (via {tag})"


def build_headers(state: str) -> dict:
    sg_info = urllib.parse.quote(json.dumps({
        "client_id": "b711c4dd-7df5-42e6-80e6-d111c1255cd7",
        "client_name": "stockgro_web",
        "redirect_uri": "https://app.stockgro.club?",
        "state": state, "theme": "dark"}))
    return {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "client-state": state,
        "origin": "https://accounts.stockgro.club",
        "referer": f"https://accounts.stockgro.club/?client_id=b711c4dd-7df5-42e6-80e6-d111c1255cd7&client_name=stockgro_web&redirect_uri=https%3A%2F%2Fapp.stockgro.club%3F&state={urllib.parse.quote(state)}&theme=dark",
        "user-agent": "Mozilla/5.0 (Linux; Android 14; SM-A135F) AppleWebKit/537.36 Chrome/151.0.7922.169 Mobile Safari/537.36",
        "cookie": f"sgInfo={sg_info}",
    }


def sg_post(url: str, payload: dict, headers: dict, proxy: str | None = None) -> dict:
    try:
        return requests.post(url, json=payload, headers=headers, timeout=15,
                             proxies=proxy_dicts(proxy)).json()
    except Exception as e:
        tag = proxy_label(proxy) if proxy else "direct"
        return {"success": False, "error": f"{str(e)[:150]} (via {tag})"}


def call_with_state(fn, proxy: str | None = None):
    if proxy is None:
        proxy = pick_proxy()
    state, err = get_server_state(proxy=proxy)
    if not state:
        return None, None, f"StockGro server issue: {err}"
    d = fn(state)
    if isinstance(d, dict) and d.get("error_code") == "CLIENT_STATE_EXPIRE":
        log.info("state expired, refreshing once")
        state, err = get_server_state(force=True, proxy=proxy)
        if not state:
            return None, None, f"StockGro server issue: {err}"
        d = fn(state)
    return d, state, None


def is_rate_limited(raw) -> bool:
    s = str(raw)
    return "1015" in s or "rate-limit" in s.lower() or "rate limit" in s.lower()


RATE_LIMIT_MSG = ("StockGro is temporarily rate-limiting requests.\n"
                  "Please wait *5-10 minutes* and try again.\n"
                  "No points deducted.")


# ============================ FIREBASE ============================
_PHONE_PATTERNS = [
    re.compile(r'(?:Jio|JIO|Airtel|AIRTEL|Vi|VI|Vodafone|BSNL)\s+(?:Number|No\.?|Num)\s*[:\-]\s*([6-9][0-9]{9})', re.IGNORECASE),
    re.compile(r'(?:your\s+)?(?:mobile|mob\.?|phone|contact)\s+(?:no\.?|number|num)\s*[:\-]\s*(?:\+?91[-\s]?)([6-9][0-9]{9})', re.IGNORECASE),
    re.compile(r'Number\s*[:\-]\s*([6-9][0-9]{9})', re.IGNORECASE),
    re.compile(r'(\+91[-\s]?[6-9][0-9]{9})'),
    re.compile(r'(?:\b91)([6-9][0-9]{9})\b'),
    re.compile(r'(?:^|\s|:)([6-9][0-9]{9})(?:\s|$|\.)'),
]


def parse_firebase_input(text: str) -> tuple[str | None, str | None, str]:
    """Accept ONE Firebase only. Key is OPTIONAL:
    'url' | 'url|||key' | 'url\\nkey' | profex '?s=' links.
    Bulk (multiple Firebase) is rejected. Returns (url, key, error)."""
    t = (text or "").strip()
    fmt_help = ("Send *ONE* Firebase URL only:\n"
                "`https://xxx.firebaseio.com`\n"
                "If it needs a key: `URL ||| KEY`\n"
                "Bulk is not allowed - send them one by one.")
    # bulk detection: multiple separators / multiple URLs / many lines
    if t.count("|||") > 1:
        return None, None, "*Only ONE Firebase at a time.*\n" + fmt_help
    if len(re.findall(r"firebaseio\.com|firebasedatabase", t)) > 1:
        return None, None, "*Only ONE Firebase at a time.*\n" + fmt_help
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    if len(lines) > 2:
        return None, None, "*Only ONE Firebase at a time.*\n" + fmt_help
    url, key = None, ""
    if "|||" in t:
        parts = t.split("|||")
        url = parts[0].strip()
        key = parts[1].strip() if len(parts) > 1 else ""
    elif "?s=" in t or "&s=" in t:
        m = re.search(r'[?&]s=([A-Za-z0-9+/=]+)', t)
        if m:
            try:
                import base64
                dec = base64.b64decode(m.group(1)).decode("utf-8")
                p = dec.split("|||")
                if len(p) == 2:
                    url, key = p[0].strip(), p[1].strip()
            except Exception:
                pass
    elif len(lines) == 2:
        url, key = lines[0], lines[1]
    elif len(lines) == 1:
        url, key = lines[0], ""  # URL only: public access, no key needed
    if not url:
        return None, None, fmt_help
    url = url.rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    if "firebaseio.com" not in url and "firebasedatabase" not in url:
        return None, None, "That URL does not look like a Firebase database URL."
    return url, key, ""


def _auth_qs(key: str, first: bool) -> str:
    """Auth query-string fragment; empty when no key (public Firebase)."""
    if not key:
        return ""
    return ("?auth=" if first else "&auth=") + key


def fb_get(url: str, proxy: str | None = None, timeout: int = 12):
    try:
        r = requests.get(url, timeout=timeout, proxies=proxy_dicts(proxy))
        if r.status_code == 200:
            return r.json()
        return {"__http_error__": r.status_code}
    except Exception as e:
        return {"__error__": str(e)[:150]}


def fb_host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc or url[:40]
    except Exception:
        return url[:40]


def fetch_clients(fb_url: str, fb_key: str, proxy: str | None = None) -> dict:
    data = fb_get(f"{fb_url}/clients.json{_auth_qs(fb_key, True)}", proxy)
    if not data or not isinstance(data, dict) or "__error__" in data or "__http_error__" in data:
        return {}
    return data


def extract_phone_from_device(device: dict) -> str:
    raw = device.get("mobNo", "")
    if not raw or str(raw) in ("", "-", "None"):
        sims = device.get("sims")
        if sims:
            if isinstance(sims, dict):
                sims = list(sims.values())
            if isinstance(sims, list) and sims and isinstance(sims[0], dict):
                raw = sims[0].get("phoneNumber", "")
    if not raw or str(raw) in ("", "-", "None"):
        raw = device.get("phoneNumber", "")
    if not raw or str(raw) in ("", "-", "None"):
        return ""
    mobile = str(raw).replace("+91", "").replace(" ", "").replace("-", "").strip()
    if len(mobile) != 10 or not mobile.isdigit():
        return ""
    return mobile


def extract_phone_from_sms(text: str):
    for pattern in _PHONE_PATTERNS:
        m = pattern.search(text)
        if m and m.group(1):
            digits = re.sub(r"[^0-9]", "", m.group(1))
            if len(digits) == 10 and digits[0] in "6789":
                return digits
            if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
                return digits[2:]
    return None


def _scan_device(args) -> tuple:
    """Fetch one device's messages and extract numbers. Thread-safe."""
    fb_url, fb_key, proxy, dev_id, dev = args
    sms_nums = set()
    try:
        data = fb_get(f"{fb_url}/messages/{dev_id}.json?orderBy=\"$key\"&limitToLast=150{_auth_qs(fb_key, False)}",
                      proxy, timeout=10)
        if data and isinstance(data, dict):
            for _k, msg in data.items():
                if not isinstance(msg, dict):
                    continue
                txt = str(msg.get("message", "") or msg.get("body", "") or msg.get("text", ""))
                if txt.strip():
                    ph = extract_phone_from_sms(txt)
                    if ph:
                        sms_nums.add(ph)
    except Exception:
        pass
    return dev_id, bool(dev.get("status")), extract_phone_from_device(dev), sorted(sms_nums)


def collect_numbers(fb_url: str, fb_key: str, proxy: str | None = None, clients: dict | None = None):
    """Returns (devices_info, all_numbers). Device message scans run in parallel."""
    from concurrent.futures import ThreadPoolExecutor
    if clients is None:
        clients = fetch_clients(fb_url, fb_key, proxy)
    items = [(fb_url, fb_key, proxy, dev_id, dev) for dev_id, dev in clients.items()
             if isinstance(dev, dict)]
    devices, seen, order = [], set(), []
    if not items:
        return devices, order
    with ThreadPoolExecutor(max_workers=min(10, len(items))) as ex:
        results = list(ex.map(_scan_device, items))
    by_id = {dev_id: (online, primary, sms) for dev_id, online, primary, sms in results}
    for _url, _key, _px, dev_id, _dev in items:
        online, primary, sms = by_id[dev_id]
        devices.append({"id": dev_id, "online": online, "primary": primary, "sms": sms})
        for ph in ([primary] if primary else []) + sms:
            if ph and ph not in seen:
                seen.add(ph)
                order.append((ph, dev_id))
    return devices, order


def get_last_message_key(fb_url: str, fb_key: str, device_id: str, proxy: str | None = None) -> str:
    try:
        data = fb_get(f"{fb_url}/messages/{device_id}.json?orderBy=\"$key\"&limitToLast=1{_auth_qs(fb_key, False)}", proxy)
        if data and isinstance(data, dict):
            keys = list(data.keys())
            if keys:
                return keys[-1]
    except Exception:
        pass
    return ""


def poll_for_stockgro_otp(fb_url: str, fb_key: str, device_id: str, last_key: str,
                          proxy: str | None = None, timeout: int = 40):
    start = time.time()
    while time.time() - start < timeout:
        try:
            data = fb_get(f"{fb_url}/messages/{device_id}.json?orderBy=\"$key\"&limitToLast=20{_auth_qs(fb_key, False)}", proxy)
            if data and isinstance(data, dict):
                for msg_key, msg in data.items():
                    if msg_key > last_key and isinstance(msg, dict):
                        text = str(msg.get("message", "") or msg.get("body", "") or msg.get("text", ""))
                        sender = str(msg.get("sender", "") or msg.get("from", ""))
                        if not text.strip():
                            continue
                        tl, sl = text.lower(), sender.lower()
                        is_sg = any(k in tl for k in ["stockgro", "verification code for stockgro", "stockgro app"]) \
                            or any(k in sl for k in ["stockgro", "stkgro", "sg"])
                        if is_sg or "verification code" in tl or "otp" in tl:
                            m = re.search(r"(\d{6})\s+is your verification code", text, re.IGNORECASE) \
                                or re.search(r"\b(\d{6})\b", text)
                            if m:
                                return m.group(1)
        except Exception:
            pass
        time.sleep(3)
    return None


def checker_report(fb_url: str, fb_key: str, proxy: str | None = None) -> str:
    clients = fetch_clients(fb_url, fb_key, proxy)
    if not clients:
        return ("*FIREBASE CHECK*\n------------------------\n"
                f"Host: `{fb_host(fb_url)}`\nStatus: *INACTIVE / INVALID*\n"
                "Could not read clients. Check the URL and key.")
    devices, order = collect_numbers(fb_url, fb_key, proxy, clients)
    online = sum(1 for d in devices if d["online"])
    with_primary = sum(1 for d in devices if d["primary"])
    lines = [f"*FIREBASE CHECK*\n------------------------",
             f"Host: `{fb_host(fb_url)}`",
             f"Key: {'provided' if fb_key else 'not provided (public access)'}",
             "Status: *ACTIVE*",
             f"Devices: *{len(devices)}* (Online: *{online}*)",
             f"Numbers found: *{len(order)}*",
             ""]
    for d in devices[:15]:
        short = d["id"][:10]
        prim = f"`{d['primary']}`" if d["primary"] else "-"
        extra = f" +{len(d['sms'])} sms" if d["sms"] else ""
        lines.append(f"{'🟢' if d['online'] else '🔴'} `{short}` | {prim}{extra}")
    if len(devices) > 15:
        lines.append(f"...and {len(devices) - 15} more")
    fresh = sum(1 for ph, _ in order if not is_number_used(ph))
    lines += ["", f"Fresh (unused) numbers: *{fresh}*",
              "Submit this Firebase with the Submit button to start auto refers."]
    return "\n".join(lines)


# ============================ JOB (runs in a thread, serial) ============================
def run_firebase_job(bot, loop, chat_id: int, uid: int, fb_url: str, fb_key: str,
                     refcode: str, proxy: str | None):
    def say(text: str):
        try:
            fut = asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id, text, parse_mode="Markdown"), loop)
            fut.result(timeout=20)
        except Exception as e:
            log.warning("progress send fail: %s", e)

    host = fb_host(fb_url)
    proxy = ensure_proxy(proxy)  # dead proxy = 0 success, so validate first
    log.info("job uid=%s host=%s via %s", uid, host, proxy_label(proxy) if proxy else "direct")
    say(f"*Your turn started.*\nHost: `{host}`\nScanning numbers. Please wait.")
    _devices, order = collect_numbers(fb_url, fb_key, proxy)
    fresh = [(ph, dev) for ph, dev in order if not is_number_used(ph)]
    if MAX_NUMBERS_PER_JOB > 0:
        fresh = fresh[:MAX_NUMBERS_PER_JOB]
    if not fresh:
        record_job(uid, host, 0, 0, "no_fresh_numbers")
        say("No fresh numbers found on this Firebase.\n"
            "All numbers are already used. Check with the Checker first.")
        return
    say(f"Found *{len(fresh)}* fresh number(s). Starting auto refers.")
    tried, success = 0, []
    for ph, dev_id in fresh:
        tried += 1
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        d, _st, err = call_with_state(
            lambda st: sg_post(f"{BASE_URL}/getIdentity",
                               {"phone_number": ph, "country_code": "IN", "otp_channel": "sms"},
                               build_headers(st), proxy), proxy)
        if err or not d or not d.get("success"):
            if d and is_rate_limited(d):
                say("*Rate limited by StockGro.* Stopping this job. No points lost beyond the entry fee. Try later.")
                break
            continue
        if d["data"].get("existing_user"):
            save_success(ph, uid, "ALREADY_REGISTERED", "-", refcode)
            continue
        last_key = get_last_message_key(fb_url, fb_key, dev_id, proxy)
        time.sleep(2)
        dc, sdata, derr = call_with_state(
            lambda st: sg_post(f"{BASE_URL}/login/createOtp",
                               {"phone_number": ph, "country_code": "IN", "otp_channel": "sms",
                                "invitation_code": refcode, "flow_type": "signup"},
                               build_headers(st)), proxy)
        if derr or not dc or not dc.get("success"):
            if dc and is_rate_limited(dc):
                say("*Rate limited by StockGro.* Stopping this job. Try later.")
                break
            continue
        say(f"SMS sent to `{ph}`. Waiting for auto OTP (up to {OTP_TIMEOUT}s).")
        otp = poll_for_stockgro_otp(fb_url, fb_key, dev_id, last_key, proxy, OTP_TIMEOUT)
        if not otp:
            continue
        v = sg_post(f"{BASE_URL}/login/validateOtp",
                    {"session_id": sdata["session_id"], "otp": otp, "phone_number": ph,
                     "country_code": "IN", "otp_channel": "sms", "flow_type": "signup"},
                    build_headers(sdata.get("state", "")), proxy)
        if not v or not v.get("success"):
            continue
        r = sg_post(f"{BASE_URL}/signup/registerUser",
                    {"display_name": name, "invitation_code": refcode, "otp": otp,
                     "session_id": sdata["session_id"], "whatsapp_consent": True,
                     "phone_number": ph, "country_code": "IN", "otp_channel": "sms"},
                    build_headers(sdata.get("state", "")), proxy)
        if not r or not r.get("success"):
            continue
        sg_uid = r.get("data", {}).get("user_id", "")
        save_success(ph, uid, name, sg_uid, refcode)
        success.append((ph, name))
        say(f"*Success {len(success)}:* `{ph}` registered as *{name}*.")
    record_job(uid, host, tried, len(success), "done")
    u = get_user(uid)
    bal = u["points"] if u else 0
    say(f"*Job finished.*\nTried: *{tried}* | Success: *{len(success)}*\nBalance: *{bal}* points.")


# ============================ QUEUE (serial, one user at a time) ============================
_QUEUE: deque = deque()
_QUEUE_LOCK = asyncio.Lock()
_ACTIVE_UID: int | None = None


async def queue_add(uid: int, fb_url: str, fb_key: str, refcode: str, proxy: str | None) -> int:
    async with _QUEUE_LOCK:
        _QUEUE.append({"uid": uid, "fb_url": fb_url, "fb_key": fb_key,
                       "refcode": refcode, "proxy": proxy,
                       "at": datetime.now().strftime("%H:%M:%S")})
        return len(_QUEUE)


async def queue_position(uid: int) -> int | None:
    async with _QUEUE_LOCK:
        for i, j in enumerate(_QUEUE, 1):
            if j["uid"] == uid:
                return i
    return None


async def queue_list() -> list[dict]:
    async with _QUEUE_LOCK:
        return list(_QUEUE)


async def queue_cancel(uid: int) -> bool:
    async with _QUEUE_LOCK:
        for j in list(_QUEUE):
            if j["uid"] == uid:
                _QUEUE.remove(j)
                return True
    return False


async def queue_clear() -> int:
    async with _QUEUE_LOCK:
        n = len(_QUEUE)
        _QUEUE.clear()
        return n


async def queue_worker(app: Application):
    global _ACTIVE_UID
    log.info("queue worker started")
    while True:
        async with _QUEUE_LOCK:
            job = _QUEUE.popleft() if _QUEUE else None
        if not job:
            await asyncio.sleep(2)
            continue
        _ACTIVE_UID = job["uid"]
        try:
            await app.bot.send_message(job["uid"], "*Your turn started.*", parse_mode="Markdown")
        except Exception:
            pass
        loop = asyncio.get_running_loop()
        try:
            await asyncio.to_thread(run_firebase_job, app.bot, loop, job["uid"],
                                    job["uid"], job["fb_url"], job["fb_key"],
                                    job["refcode"], job["proxy"])
        except Exception as e:
            log.error("job crash uid=%s: %s", job["uid"], e)
            try:
                await app.bot.send_message(job["uid"], "Job stopped due to an error. Contact admin.")
            except Exception:
                pass
        _ACTIVE_UID = None


# ============================ UI HELPERS ============================
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def not_spam(uid: int) -> bool:
    now = time.time()
    if now - _last_msg_time.get(uid, 0) < SPAM_COOLDOWN_SEC:
        return False
    _last_msg_time[uid] = now
    return True


def md_esc(s) -> str:
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", str(s or ""))


async def safe_answer(q) -> None:
    try:
        await q.answer()
    except Exception as e:
        log.debug("answer skipped: %s", str(e)[:120])


async def safe_edit(q, text: str, parse_mode: str | None = "Markdown", reply_markup=None) -> None:
    try:
        await q.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as e:
        if "not modified" in str(e).lower():
            try:
                await q.answer()
            except Exception:
                pass
        else:
            raise


def main_menu_kb(is_adm: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🔍 Check Firebase", callback_data="m_check",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_BLUE),
         InlineKeyboardButton("🚀 Submit Firebase", callback_data="m_submit",
                              style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_GREEN)],
        [InlineKeyboardButton("⏳ My Queue", callback_data="m_queue",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_OFFERS),
         InlineKeyboardButton("📊 Dashboard", callback_data="m_dash",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_BLUE)],
        [InlineKeyboardButton("👥 My Referrals", callback_data="m_refers",
                              style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_RENEW),
         InlineKeyboardButton("🎁 Set Refer Code", callback_data="m_setcode",
                              style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_GREEN)],
        [InlineKeyboardButton("❓ Help", callback_data="m_help")],
    ]
    if is_adm:
        rows.append([InlineKeyboardButton("👑 Admin Panel", callback_data="m_admin",
                                          style=STYLE_DANGER, icon_custom_emoji_id=ICON_RED)])
    return InlineKeyboardMarkup(rows)


def dashboard_text(u: sqlite3.Row, bot_username: str) -> str:
    link = f"https://t.me/{bot_username}?start=r_{u['user_id']}"
    code = u["stockgro_code"] or DEFAULT_STOCKGRO_CODE
    return (
        "DASHBOARD\n------------------------\n"
        f"User ID: `{u['user_id']}`\n"
        f"Points: *{u['points']}* (1 Firebase = {COST_PER_JOB} pt)\n"
        f"Total Referrals: *{u['total_refers']}* (1 referral = {POINTS_PER_REFER} pts)\n"
        f"StockGro Code: `{code}`\n\n"
        f"Your Referral Link:\n`{link}`\n\n"
        f"Share your link. You earn *{POINTS_PER_REFER} points* per join (= {POINTS_PER_REFER} Firebase uses)."
    )


async def check_force_join(context: ContextTypes.DEFAULT_TYPE, uid: int):
    if uid in ADMIN_IDS:
        return True, [], ""
    hit = _JOIN_CACHE.get(uid)
    if hit and time.time() - hit < JOIN_CACHE_TTL:
        return True, [], ""
    missing, errors = [], []
    for ch in get_channels():
        try:
            m = await context.bot.get_chat_member(ch["chat_id"], uid)
            if m.status in ("left", "kicked"):
                missing.append(ch)
        except Exception as e:
            errors.append(f"{ch['chat_id']}: {e}")
            missing.append(ch)
    if not missing:
        _JOIN_CACHE[uid] = time.time()
    return (len(missing) == 0, missing, " | ".join(errors))


async def show_force_join(msg_target, missing: list[dict], debug: str = ""):
    rows = []
    for ch in missing:
        rows.append([InlineKeyboardButton(f"📢 Join {ch['chat_id']}",
                                          url=channel_link_for(ch["chat_id"], ch.get("link", "")),
                                          style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_BLUE)])
    rows.append([InlineKeyboardButton("✅ Verify - I Have Joined", callback_data="verify_join",
                                      style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_RENEW)])
    txt = ("*Channel Membership Required*\n\n"
           "Please join the channel(s) below to use this bot.\n"
           "After joining, tap Verify.")
    if debug and getattr(msg_target, "chat", None) is not None:
        try:
            if msg_target.chat.id in ADMIN_IDS:
                txt += f"\n\nDebug: `{debug[:400]}`"
        except Exception:
            pass
    await msg_target.reply_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


# ============================ HANDLERS ============================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or ""
    fname = update.effective_user.first_name or ""
    referred_by = None
    if context.args:
        m = re.match(r"r_(\d+)", context.args[0] or "")
        if m:
            try:
                referred_by = int(m.group(1))
            except ValueError:
                referred_by = None
    is_new, credited = ensure_user(uid, username, fname, referred_by)
    u = get_user(uid)
    joined, missing, dbg = await check_force_join(context, uid)
    if not joined:
        await show_force_join(update.message, missing, dbg)
        return
    if credited and referred_by and referred_by != uid:
        try:
            await context.bot.send_message(
                referred_by,
                f"*New Referral!* +{POINTS_PER_REFER} points\nUser `{uid}` joined using your link.",
                parse_mode="Markdown")
        except Exception:
            pass
    if not is_new:
        try:
            pending_n = credit_pending_referrals(uid)
        except Exception:
            pending_n = 0
        if pending_n:
            u = get_user(uid)
            try:
                await update.message.reply_text(
                    f"*Pending referrals credited:* {pending_n} user(s).\n"
                    f"+*{pending_n * POINTS_PER_REFER}* points. Balance: *{u['points']}*.",
                    parse_mode="Markdown")
            except Exception:
                pass
    bonus_line = f"\nWelcome bonus: *{BONUS_ON_START} point(s)* credited." if is_new else ""
    await update.message.reply_text(
        "*Welcome to Firebase Auto-Refer Bot*\n------------------------\n"
        "1. *Check Firebase* - inspect any Firebase first (free).\n"
        "2. *Submit Firebase* - queue it, everything else is automatic.\n"
        f"3. Referrals earn *{POINTS_PER_REFER} points*. One Firebase submission costs *{COST_PER_JOB} point*.\n"
        "4. Only ONE user is processed at a time - everyone gets their turn.\n"
        f"{bonus_line}\nYour balance: *{u['points']} points*",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(is_admin(uid)))


async def on_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await safe_answer(q)
    uid = q.from_user.id
    joined, missing, dbg = await check_force_join(context, uid)
    if not joined:
        rows = []
        for c in missing:
            rows.append([InlineKeyboardButton(f"📢 Join {c['chat_id']}",
                                             url=channel_link_for(c['chat_id'], c.get('link', '')),
                                             style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_BLUE)])
        rows.append([InlineKeyboardButton("✅ Verify Again", callback_data="verify_join",
                                          style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_RENEW)])
        txt = "*Membership still pending.*\nPlease join the channel and tap Verify again."
        if uid in ADMIN_IDS and dbg:
            txt += f"\n\nDebug: `{dbg[:400]}`"
        await safe_edit(q, txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return
    await safe_edit(q, "*Verification successful.*\n\nPlease select an option below.",
                    parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await safe_answer(q)
    uid = q.from_user.id
    data = q.data
    joined, missing, dbg = await check_force_join(context, uid)
    if not joined:
        await show_force_join(q.message, missing, dbg)
        return
    u = get_user(uid)
    bot_username = (context.bot.username or BOT_USERNAME_FALLBACK).replace("@", "")
    if data == "m_back":
        context.user_data.pop("awaiting", None)
        await safe_edit(q, "*Main Menu*\nPlease select an option.",
                        parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_check":
        context.user_data["awaiting"] = "fb_check"
        await safe_edit(q, "*Check Firebase* (free)\n\nSend *ONE* Firebase URL:\n"
                           "`https://xxx.firebaseio.com`\n"
                           "If it needs a key: `URL ||| KEY`\n"
                           "You will get: active/inactive, devices, online count, numbers.\n"
                           "Send /cancel to cancel.",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_back")]]))
    elif data == "m_submit":
        if u["points"] < COST_PER_JOB:
            await safe_edit(q, f"*Insufficient points.*\nBalance: *{u['points']}* | Required: *{COST_PER_JOB}*\n\n"
                               "Share your referral link to earn points.",
                            parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
            return
        if await queue_position(uid) is not None or _ACTIVE_UID == uid:
            await safe_edit(q, "You already have a job in queue / running. Wait for it to finish.",
                            parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
            return
        context.user_data["awaiting"] = "fb_submit"
        code_now = u["stockgro_code"] or DEFAULT_STOCKGRO_CODE
        await safe_edit(q, "*Submit Firebase* (1 point)\n\nSend *ONE* Firebase URL:\n"
                           "`https://xxx.firebaseio.com`\n"
                           "If it needs a key: `URL ||| KEY`\n\n"
                           f"Active refer code: `{code_now}` (change via Set Refer Code).\n"
                           f"All fresh numbers will be processed automatically.\n"
                           "Send /cancel to cancel.",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_back")]]))
    elif data == "m_queue":
        pos = await queue_position(uid)
        running = (_ACTIVE_UID == uid)
        pend = await queue_list()
        if running:
            txt = "*MY QUEUE*\n------------------------\nStatus: *PROCESSING NOW* - your Firebase is running."
        elif pos:
            txt = (f"*MY QUEUE*\n------------------------\nPosition: *#{pos}* in queue.\n"
                   "Only one user runs at a time. You will be notified on your turn.")
        else:
            txt = "*MY QUEUE*\n------------------------\nYou have no job in queue."
        txt += f"\n\nTotal waiting: *{len(pend)}*"
        kb = [[InlineKeyboardButton("🔙 Back", callback_data="m_back")]]
        if pos:
            kb = [[InlineKeyboardButton("❌ Cancel My Job", callback_data="q_cancel",
                                        style=STYLE_DANGER, icon_custom_emoji_id=ICON_CANCEL)],
                  [InlineKeyboardButton("🔙 Back", callback_data="m_back")]]
        await safe_edit(q, txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "q_cancel":
        if await queue_cancel(uid):
            await safe_edit(q, "Your queued job was cancelled. *No refund* (point was used on submit).",
                            parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
        else:
            await safe_edit(q, "No pending job found (it may already be running).",
                            parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_dash":
        await safe_edit(q, dashboard_text(u, bot_username),
                        parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_refers":
        link = f"https://t.me/{bot_username}?start=r_{uid}"
        await safe_edit(q, "*MY REFERRALS*\n------------------------\n"
                           f"Total referrals: *{u['total_refers']}*\n"
                           f"Points: *{u['points']}*\n"
                           f"1 referral = *{POINTS_PER_REFER} points* = *{POINTS_PER_REFER} Firebase uses*\n\n"
                           f"Your link:\n`{link}`",
                        parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_setcode":
        context.user_data["awaiting"] = "code"
        await safe_edit(q, "*Set Refer Code*\n\nPlease send your StockGro referral code (e.g. `NIP8OG9M`).\n"
                           "Set once - it stays for all your Firebase jobs until you change it.\n"
                           "Send /cancel to cancel.",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_back")]]))
    elif data == "m_help":
        await safe_edit(q, "*HELP*\n------------------------\n"
                           "1. Check Firebase - inspect any Firebase free of charge.\n"
                           "2. Submit Firebase - costs 1 point, queued, fully automatic.\n"
                           "3. One user runs at a time. Queue position is shown under My Queue.\n"
                           "4. Already-registered numbers are skipped automatically.\n"
                           "5. Set your StockGro code once with Set Refer Code.\n"
                           "6. Refer friends: 1 join = 2 points = 2 Firebase uses.",
                        parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_admin":
        if not is_admin(uid):
            await safe_answer(q)
            return
        context.user_data.pop("awaiting", None)
        await show_admin(q, context)


async def show_admin(q_or_msg, context):
    text = ("*ADMIN PANEL*\n------------------------\nPlease select an action.")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistics", callback_data="a_stats",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_BLUE),
         InlineKeyboardButton("⏳ Queue", callback_data="a_queue",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_OFFERS)],
        [InlineKeyboardButton("📢 Channels", callback_data="a_channels",
                              style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_GREEN),
         InlineKeyboardButton("➕ Add Points", callback_data="a_addpts",
                              style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_RENEW)],
        [InlineKeyboardButton("🔍 Search User", callback_data="a_search",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_BLUE),
         InlineKeyboardButton("📣 Broadcast", callback_data="a_bcast",
                              style=STYLE_DANGER, icon_custom_emoji_id=ICON_CANCEL)],
        [InlineKeyboardButton("🔙 Back", callback_data="m_back")],
    ])
    if hasattr(q_or_msg, "edit_message_text"):
        await safe_edit(q_or_msg, text, parse_mode="Markdown", reply_markup=kb)
    else:
        await q_or_msg.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def on_admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if not is_admin(uid):
        await safe_answer(q)
        return
    await safe_answer(q)
    data = q.data
    back = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_admin")]])
    if data == "a_stats":
        con = db()
        users = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        refs = con.execute("SELECT COUNT(*) c FROM referrals").fetchone()["c"]
        jobs = con.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        succ = con.execute("SELECT COALESCE(SUM(numbers_success),0) s FROM jobs").fetchone()["s"]
        pts = con.execute("SELECT COALESCE(SUM(points),0) s FROM users").fetchone()["s"]
        pend = await queue_list()
        con.close()
        await safe_edit(q, f"*STATISTICS*\n------------------------\nUsers: *{users}*\n"
                           f"Referrals: *{refs}*\nJobs done: *{jobs}*\nSuccessful refers: *{succ}*\n"
                           f"Points in system: *{pts}*\nQueue waiting: *{len(pend)}*"
                           f"{' | RUNNING: ' + str(_ACTIVE_UID) if _ACTIVE_UID else ''}",
                        parse_mode="Markdown", reply_markup=back)
    elif data == "a_queue":
        pend = await queue_list()
        lines = [f"{i+1}. `{j['uid']}` at {j['at']}" for i, j in enumerate(pend)] or ["Queue is empty."]
        if _ACTIVE_UID:
            lines.insert(0, f"RUNNING: `{_ACTIVE_UID}`")
        await safe_edit(q, "*QUEUE*\n------------------------\n" + "\n".join(lines) +
                           "\n\n/clearqueue empties the waiting list.",
                        parse_mode="Markdown", reply_markup=back)
    elif data == "a_channels":
        chs = get_channels()
        line = "\n".join([f"{c['id']}. `{c['chat_id']}`" for c in chs]) or "None"
        context.user_data["awaiting"] = "admin_addchannel"
        await safe_edit(q, f"*FORCE-JOIN CHANNELS*\n------------------------\n{line}\n\n"
                           "To add, just send `@username` or `https://t.me/username` here.\n"
                           "To remove: `/removechannel @username`\nSend /cancel to cancel.",
                        parse_mode="Markdown", reply_markup=back)
    elif data == "a_addpts":
        context.user_data["awaiting"] = "admin_give_id"
        context.user_data.pop("give_target", None)
        await safe_edit(q, "Please send the *User ID* of the user.\n"
                           "(Or both at once: `USERID POINTS`, e.g. `123456 4`)\nSend /cancel to cancel.",
                        parse_mode="Markdown")
    elif data == "a_search":
        context.user_data["awaiting"] = "admin_search"
        await safe_edit(q, "Please send the *User ID* to search.\nSend /cancel to cancel.",
                        parse_mode="Markdown")
    elif data == "a_bcast":
        context.user_data["awaiting"] = "admin_bcast"
        await safe_edit(q, "Please send the broadcast message (it will go to all users):",
                        parse_mode="Markdown")


def get_user_profile(uid: int) -> str | None:
    u = get_user(uid)
    if not u:
        return None
    con = db()
    jobs = con.execute("SELECT COUNT(*) c FROM jobs WHERE user_id=?", (uid,)).fetchone()["c"]
    succ = con.execute("SELECT COALESCE(SUM(numbers_success),0) s FROM jobs WHERE user_id=?", (uid,)).fetchone()["s"]
    refs = con.execute("SELECT referred_id FROM referrals WHERE referrer_id=? ORDER BY created_at DESC LIMIT 5",
                       (uid,)).fetchall()
    con.close()
    card = (f"*USER DETAILS*\n------------------------\n"
            f"ID: `{u['user_id']}`\n"
            f"Username: @{md_esc(u['username']) or '-'} \n"
            f"Name: {md_esc(u['first_name']) or '-'}\n"
            f"Points: *{u['points']}*\n"
            f"Referrals: *{u['total_refers']}*\n"
            f"StockGro Code: `{u['stockgro_code'] or DEFAULT_STOCKGRO_CODE}`\n"
            f"Referred By: `{u['referred_by'] or 'Direct'}`\n"
            f"Joined: {u['joined_at']}\n"
            f"Firebase Jobs: *{jobs}* | Successful refers: *{succ}*")
    if refs:
        card += "\n\nReferred users:\n" + ", ".join(f"`{r['referred_id']}`" for r in refs)
    return card


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not not_spam(uid):
        return
    text = (update.message.text or "").strip()
    if text == "/cancel":
        context.user_data.pop("awaiting", None)
        context.user_data.pop("give_target", None)
        await update.message.reply_text("Cancelled.", reply_markup=main_menu_kb(is_admin(uid)))
        return
    if text.startswith("/"):
        return
    joined, missing, dbg = await check_force_join(context, uid)
    if not joined:
        await show_force_join(update.message, missing, dbg)
        return
    u = get_user(uid)
    if not u:
        ensure_user(uid, update.effective_user.username or "",
                    update.effective_user.first_name or "")
        u = get_user(uid)
    state = context.user_data.get("awaiting")

    # ---------- ADMIN states ----------
    if state == "admin_addchannel" and is_admin(uid):
        parts = text.split()
        raw = parts[0]
        link = parts[1] if len(parts) > 1 else ""
        if "t.me" in raw and not link:
            link = raw
        chat_id = normalize_channel(raw)
        if not chat_id.startswith("@") and not chat_id.startswith("-"):
            await update.message.reply_text("Invalid channel. Send `@username` or `https://t.me/username`.",
                                            parse_mode="Markdown")
            return
        if not link:
            link = channel_link_for(chat_id, "")
        con = db()
        con.execute("INSERT OR REPLACE INTO channels(chat_id, link) VALUES(?,?)", (chat_id, link))
        con.commit()
        chs = get_channels()
        con.close()
        context.user_data.pop("awaiting", None)
        line = "\n".join([f"{c['id']}. `{c['chat_id']}`" for c in chs])
        await update.message.reply_text(
            f"Channel added: {chat_id}\n{link}\n\n*Active force-join channels:*\n{line}\n\n"
            "Important: make the bot an admin of that channel, then run /checkchannel.",
            parse_mode="Markdown")
        return
    if state == "admin_give_id" and is_admin(uid):
        parts = text.split()
        try:
            if len(parts) == 2:
                target, pts = int(parts[0]), int(parts[1])
                ok, bal = give_points(target, pts)
                context.user_data.pop("awaiting", None)
                await update.message.reply_text(
                    f"User `{target}` credited with *{pts}* points.\nNew balance: *{bal}*."
                    if ok else f"User `{target}` not found.", parse_mode="Markdown")
                return
            target = int(parts[0])
        except (ValueError, IndexError):
            await update.message.reply_text("Please send a numeric User ID.", parse_mode="Markdown")
            return
        tu = get_user(target)
        if not tu:
            await update.message.reply_text(f"User `{target}` not found.", parse_mode="Markdown")
            return
        context.user_data["give_target"] = target
        context.user_data["awaiting"] = "admin_give_pts"
        await update.message.reply_text(
            f"User: `{target}` (balance: *{tu['points']}*)\nHow many points to add?",
            parse_mode="Markdown")
        return
    if state == "admin_give_pts" and is_admin(uid):
        target = context.user_data.get("give_target")
        if not target:
            context.user_data["awaiting"] = "admin_give_id"
            await update.message.reply_text("Please send the *User ID* first.", parse_mode="Markdown")
            return
        try:
            pts = int(text.split()[0])
        except (ValueError, IndexError):
            await update.message.reply_text("Please send a valid number.", parse_mode="Markdown")
            return
        if pts <= 0 or pts > 100000:
            await update.message.reply_text("Points must be between 1 and 100000.", parse_mode="Markdown")
            return
        ok, bal = give_points(target, pts)
        context.user_data.pop("awaiting", None)
        context.user_data.pop("give_target", None)
        await update.message.reply_text(
            f"User `{target}` credited with *{pts}* points.\nNew balance: *{bal}*."
            if ok else f"User `{target}` not found.", parse_mode="Markdown")
        if ok:
            try:
                await context.bot.send_message(target, f"Admin credited *{pts}* points.\nNew balance: *{bal}*.",
                                               parse_mode="Markdown")
            except Exception:
                pass
        return
    if state == "admin_search" and is_admin(uid):
        try:
            target = int(text.split()[0])
        except (ValueError, IndexError):
            await update.message.reply_text("Please send a numeric User ID.", parse_mode="Markdown")
            return
        card = get_user_profile(target)
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(card if card else f"User `{target}` not found.",
                                        parse_mode="Markdown")
        return
    if state == "admin_bcast" and is_admin(uid):
        context.user_data.pop("awaiting", None)
        con = db()
        ids = [r["user_id"] for r in con.execute("SELECT user_id FROM users").fetchall()]
        con.close()
        ok = 0
        for tid in ids:
            try:
                await context.bot.send_message(tid, f"*Announcement*\n\n{text}", parse_mode="Markdown")
                ok += 1
            except Exception:
                pass
        await update.message.reply_text(f"Broadcast completed: {ok}/{len(ids)} users.")
        return

    # ---------- USER states ----------
    if state == "code":
        code = re.sub(r"\s+", "", text).upper()
        if not re.fullmatch(r"[A-Z0-9]{4,20}", code):
            await update.message.reply_text("Invalid code. Use A-Z and 0-9 (4-20 chars). Try again or /cancel.")
            return
        set_stockgro_code(uid, code)
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"Refer code saved: `{code}`\nIt stays for all your jobs until you change it.",
                                        parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
        return

    if state == "fb_check":
        fb_url, fb_key, err = parse_firebase_input(text)
        if err:
            await update.message.reply_text(err, parse_mode="Markdown")
            return
        context.user_data.pop("awaiting", None)
        wait = await update.message.reply_text("Checking Firebase. Please wait.")
        entry = pick_proxy()
        report = await asyncio.to_thread(checker_report, fb_url, fb_key, entry)
        await wait.edit_text(report, parse_mode="Markdown",
                             reply_markup=main_menu_kb(is_admin(uid)))
        return

    if state == "fb_submit":
        fb_url, fb_key, err = parse_firebase_input(text)
        if err:
            await update.message.reply_text(err, parse_mode="Markdown")
            return
        if await queue_position(uid) is not None or _ACTIVE_UID == uid:
            context.user_data.pop("awaiting", None)
            await update.message.reply_text("You already have a job in queue / running.",
                                            reply_markup=main_menu_kb(is_admin(uid)))
            return
        if u["points"] < COST_PER_JOB:
            context.user_data.pop("awaiting", None)
            await update.message.reply_text(f"Insufficient points. Balance: *{u['points']}*.",
                                            parse_mode="Markdown",
                                            reply_markup=main_menu_kb(is_admin(uid)))
            return
        wait = await update.message.reply_text("Validating Firebase. Please wait.")
        entry = pick_proxy()
        valid = await asyncio.to_thread(fetch_clients, fb_url, fb_key, entry)
        if not valid:
            await wait.edit_text("This Firebase looks *inactive or invalid* (no clients readable).\n"
                                 "No points deducted. If it needs a key, send `URL ||| KEY`.",
                                 parse_mode="Markdown",
                                 reply_markup=main_menu_kb(is_admin(uid)))
            context.user_data.pop("awaiting", None)
            return
        if not deduct_job_point(uid):
            await wait.edit_text(f"Insufficient points.", reply_markup=main_menu_kb(is_admin(uid)))
            context.user_data.pop("awaiting", None)
            return
        refcode = u["stockgro_code"] or DEFAULT_STOCKGRO_CODE
        pos = await queue_add(uid, fb_url, fb_key, refcode, entry)
        context.user_data.pop("awaiting", None)
        nu = get_user(uid)
        await wait.edit_text(
            f"*Firebase accepted.*\nHost: `{fb_host(fb_url)}`\n"
            f"Queue position: *#{pos}* (one user runs at a time).\n"
            f"-*{COST_PER_JOB}* point | Balance: *{nu['points']}*\n\n"
            "You will be notified when your turn starts.",
            parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
        return

    await update.message.reply_text("Please select an option from the menu.",
                                    reply_markup=main_menu_kb(is_admin(uid)))


def give_points(target_id: int, pts: int) -> tuple[bool, int | None]:
    con = db()
    row = con.execute("SELECT points FROM users WHERE user_id=?", (target_id,)).fetchone()
    if not row:
        con.close()
        return False, None
    con.execute("UPDATE users SET points = points + ? WHERE user_id=?", (pts, target_id))
    con.commit()
    bal = con.execute("SELECT points FROM users WHERE user_id=?", (target_id,)).fetchone()["points"]
    con.close()
    return True, bal


# ============================ ADMIN COMMANDS ============================
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied. Admins only.")
        return
    await show_admin(update.message, context)


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pos = await queue_position(uid)
    if _ACTIVE_UID == uid:
        await update.message.reply_text("Status: *PROCESSING NOW*.", parse_mode="Markdown")
    elif pos:
        await update.message.reply_text(f"Queue position: *#{pos}*.", parse_mode="Markdown")
    else:
        await update.message.reply_text("You have no job in queue.")


async def cmd_cancelq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await queue_cancel(update.effective_user.id):
        await update.message.reply_text("Queued job cancelled. No refund (point was used on submit).")
    else:
        await update.message.reply_text("No pending job found.")


async def cmd_clearqueue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    n = await queue_clear()
    await update.message.reply_text(f"Queue cleared: {n} waiting job(s) removed.")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    con = db()
    users = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    jobs = con.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
    con.close()
    pend = await queue_list()
    await update.message.reply_text(f"Users: {users} | Jobs: {jobs} | Waiting: {len(pend)}")


async def cmd_addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 1:
        await update.message.reply_text("Use:\n`/addchannel @ch https://t.me/ch`", parse_mode="Markdown")
        return
    raw = context.args[0]
    link = context.args[1] if len(context.args) > 1 else ""
    if "t.me" in raw and not link:
        link = raw
    chat_id = normalize_channel(raw)
    if not link:
        link = channel_link_for(chat_id, "")
    con = db()
    con.execute("INSERT OR REPLACE INTO channels(chat_id, link) VALUES(?,?)", (chat_id, link))
    con.commit()
    con.close()
    await update.message.reply_text(f"Channel added: {chat_id}\n{link}", parse_mode="Markdown")


async def cmd_setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Use: `/setchannel https://t.me/viedietlooters`", parse_mode="Markdown")
        return
    chat_id = normalize_channel(context.args[0])
    link = context.args[1] if len(context.args) > 1 else channel_link_for(chat_id, "")
    con = db()
    con.execute("DELETE FROM channels")
    con.execute("INSERT INTO channels(chat_id, link) VALUES(?,?)", (chat_id, link))
    con.commit()
    con.close()
    await update.message.reply_text(f"Force-join channel set to: {chat_id}\n{link}", parse_mode="Markdown")


async def cmd_checkchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    chs = get_channels()
    if not chs:
        await update.message.reply_text("No channel in database.")
        return
    out = ["*CHANNEL CHECK*"]
    me = await context.bot.get_me()
    out.append(f"Bot: @{me.username} (`{me.id}`)")
    for ch in chs:
        out.append(f"\n`{ch['chat_id']}`\n{ch.get('link', '')}")
        try:
            info = await context.bot.get_chat(ch["chat_id"])
            out.append(f"get_chat OK: {info.type} | {getattr(info, 'title', '')}")
        except Exception as e:
            out.append(f"get_chat FAILED: `{str(e)[:200]}`")
            continue
        try:
            bm = await context.bot.get_chat_member(ch["chat_id"], me.id)
            out.append(f"Bot status: `{bm.status}`")
        except Exception as e:
            out.append(f"Bot check FAILED: `{str(e)[:200]}`")
    await update.message.reply_text("\n".join(out), parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_removechannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Use: `/removechannel @channel`")
        return
    chat_id = normalize_channel(context.args[0])
    con = db()
    con.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
    con.commit()
    con.close()
    await update.message.reply_text(f"Removed: {chat_id}")


async def cmd_addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        ok, bal = give_points(int(context.args[0]), int(context.args[1]))
        await update.message.reply_text(f"{context.args[0]} credited. Balance: {bal}." if ok else "User not found.")
    except Exception:
        await update.message.reply_text("Use: `/addpoints USERID POINTS`", parse_mode="Markdown")


async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Use: `/userinfo USERID`", parse_mode="Markdown")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("User ID must be numeric.")
        return
    card = get_user_profile(target)
    await update.message.reply_text(card if card else f"User `{target}` not found.", parse_mode="Markdown")


# ============================ MAIN ============================
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Update %s error: %s", update, context.error, exc_info=context.error)


async def _post_init(app: Application):
    asyncio.create_task(queue_worker(app))


def main():
    if not BOT_TOKEN or BOT_TOKEN.startswith("PUT_"):
        print("ERROR: set BOT_TOKEN_FB (or BOT_TOKEN) environment variable.")
        return
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("cancelq", cmd_cancelq))
    app.add_handler(CommandHandler("clearqueue", cmd_clearqueue))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("addchannel", cmd_addchannel))
    app.add_handler(CommandHandler("setchannel", cmd_setchannel))
    app.add_handler(CommandHandler("checkchannel", cmd_checkchannel))
    app.add_handler(CommandHandler("removechannel", cmd_removechannel))
    app.add_handler(CommandHandler("addpoints", cmd_addpoints))
    app.add_handler(CommandHandler("userinfo", cmd_userinfo))
    app.add_handler(CommandHandler("cancel", on_text))

    app.add_handler(CallbackQueryHandler(on_verify, pattern="^verify_join$"))
    app.add_handler(CallbackQueryHandler(on_admin_cb, pattern="^a_"))
    app.add_handler(CallbackQueryHandler(on_menu, pattern="^m_|^q_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    print("=" * 55)
    print("FIREBASE BOT started (serial queue, 1 user at a time)")
    print(f"⭐ {POINTS_PER_REFER} pts/refer | -{COST_PER_JOB} pt/firebase | bonus {BONUS_ON_START}")
    print("=" * 55)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
