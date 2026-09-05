"""
StockGro Refer + OTP Telegram Bot
=================================
Features:
  1. /start -> Force Join Channel (admin can add/remove) -> Verify button
  2. Set Refer Code (StockGro invitation_code) -> Number -> OTP -> Register
  3. Already-registered number check ("Already registered, try another number")
  4. Points system: 1 refer = 5 points | 1 successful use = 1 point deduct
     - Points deduct ONLY on SUCCESS. Fail = no deduct.
  5. Bot refer system: t.me/<bot>?start=r_<user_id> -> referrer +5 points, refer count +1
  6. Dashboard with emojis, no spam (cooldown + clean menus)
  7. Admin panel: stats, users, add/remove force-join channels, add points, broadcast

Install:  pip install python-telegram-bot==22.* requests
Run:      python stockgro_refer_bot.py

NOTE on button colors:
  Colored inline buttons ARE supported (python-telegram-bot >= 22.7):
  style="primary" (blue), style="success" (green), style="danger" (red),
  plus icon_custom_emoji_id for a custom emoji icon before the label.
  Note: colors render only on Telegram apps updated after Feb 9, 2026,
  and custom-emoji icons need a Fragment username or Premium owner.
"""

import logging
import asyncio
import os
import sqlite3
import random
import re
import time
import json
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

# ============================ CONFIG ============================
# Values can be set via environment variables (required for Railway).
# Fallback to hardcoded values for local run.
BOT_TOKEN = os.getenv("BOT_TOKEN", "8812724251:AAFWjNmEGAFUd6d425z0xsirAj2U-kR7n_s")

def _parse_admins() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "")
    ids: set[int] = set()
    if raw.strip():
        for part in raw.replace(",", " ").split():
            try:
                ids.add(int(part.strip()))
            except ValueError:
                pass
    if not ids:
        ids = {1364476174}
    return ids

ADMIN_IDS = _parse_admins()
BOT_USERNAME_FALLBACK = os.getenv("BOT_USERNAME", "@Tesetingorder_bot")

DEFAULT_STOCKGRO_CODE = os.getenv("DEFAULT_STOCKGRO_CODE", "NIP8OG9M")

# Force-join channel (overridable via env for Railway)
DEFAULT_FORCE_CHANNEL = os.getenv("FORCE_CHANNEL", "@viedietlooters")
DEFAULT_FORCE_LINK = os.getenv("FORCE_CHANNEL_LINK", "https://t.me/viedietlooters")

POINTS_PER_REFER = int(os.getenv("POINTS_PER_REFER", "5"))
COST_PER_USE = int(os.getenv("COST_PER_USE", "1"))
BONUS_ON_START = int(os.getenv("BONUS_ON_START", "2"))
DAILY_BONUS_POINTS = int(os.getenv("DAILY_BONUS_POINTS", "1"))
SPAM_COOLDOWN_SEC = 1.5

# ---- Button styles (Telegram colored buttons, needs PTB >= 22.7) ----
STYLE_PRIMARY = "primary"  # blue
STYLE_SUCCESS = "success"  # green
STYLE_DANGER = "danger"    # red

# Custom-emoji icons shown before the button label
ICON_BLUE = "5373141891321699086"     # blue dot
ICON_RED = "5370810157871667232"      # red dot
ICON_GREEN = "5471984997361523302"    # green dot
ICON_OFFERS = "5359664288241829619"   # offers/star
ICON_CANCEL = "5382224089295365367"   # cancel cross
ICON_RENEW = "5891063600885273198"    # renew tick

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "stockgro_bot.db"
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
log = logging.getLogger("stockgro-bot")

_last_msg_time: dict[int, float] = {}  # anti-spam


# ============================ DB ============================
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def normalize_channel(inp: str) -> str:
    """'@abc', 'abc', 'https://t.me/abc', 't.me/abc' -> '@abc'. '-100...' ids same rahenge."""
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
        CREATE TABLE IF NOT EXISTS numbers(
            phone TEXT PRIMARY KEY,
            user_id INTEGER,
            display_name TEXT,
            stockgro_user_id TEXT,
            status TEXT,
            created_at TEXT
        )""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS channels(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE,
            link TEXT
        )""")
    # default channel (admins can change it with /addchannel)
    # --- AUTO-MIGRATION: replace the old incorrect channel ---
    cur.execute("DELETE FROM channels WHERE chat_id IN ('@viedietloots','viedietloots')")
    cur.execute("INSERT OR IGNORE INTO channels(chat_id, link) VALUES(?,?)",
                (DEFAULT_FORCE_CHANNEL, DEFAULT_FORCE_LINK))
    # fix the link of existing rows as well
    cur.execute("UPDATE channels SET link=? WHERE chat_id=?",
                (DEFAULT_FORCE_LINK, DEFAULT_FORCE_CHANNEL))
    # --- AUTO-MIGRATION: daily bonus column for older databases ---
    try:
        cur.execute("ALTER TABLE users ADD COLUMN last_daily TEXT DEFAULT ''")
    except Exception:
        pass
    con.commit()
    con.close()


def get_user(uid: int):
    con = db()
    row = con.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return row


def ensure_user(uid: int, username: str = "", first_name: str = "", referred_by: int | None = None):
    """Create the user, grant the starting bonus, credit the referral. Returns is_new."""
    con = db()
    row = con.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if row:
        con.close()
        return False
    con.execute(
        "INSERT INTO users(user_id, username, first_name, points, total_refers, stockgro_code, referred_by, joined_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (uid, username or "", first_name or "", BONUS_ON_START, 0,
         DEFAULT_STOCKGRO_CODE, referred_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    # referral credit: award the referrer
    if referred_by and referred_by != uid:
        ref = con.execute("SELECT * FROM users WHERE user_id=?", (referred_by,)).fetchone()
        exists = con.execute("SELECT * FROM referrals WHERE referred_id=?", (uid,)).fetchone()
        if ref and not exists:
            con.execute("INSERT INTO referrals(referrer_id, referred_id, created_at) VALUES(?,?,?)",
                        (referred_by, uid, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            con.execute("UPDATE users SET points = points + ?, total_refers = total_refers + 1 WHERE user_id=?",
                        (POINTS_PER_REFER, referred_by))
            log.info("Referral credited: %s -> %s (+%s pts)", referred_by, uid, POINTS_PER_REFER)
    con.commit()
    con.close()
    return True


def add_points(uid: int, pts: int):
    con = db()
    con.execute("UPDATE users SET points = points + ? WHERE user_id=?", (pts, uid))
    con.commit()
    con.close()


def give_points(target_id: int, pts: int) -> tuple[bool, int | None]:
    """Credit points to a specific user. Returns (success, new_balance)."""
    con = db()
    row = con.execute("SELECT points FROM users WHERE user_id=?", (target_id,)).fetchone()
    if not row:
        con.close()
        return False, None
    con.execute("UPDATE users SET points = points + ? WHERE user_id=?", (pts, target_id))
    con.commit()
    new_bal = con.execute("SELECT points FROM users WHERE user_id=?", (target_id,)).fetchone()["points"]
    con.close()
    return True, new_bal


def claim_daily(uid: int) -> tuple[str, int]:
    """Claim the daily bonus. Returns (status, balance).
    status: 'claimed' | 'already' | 'nouser'"""
    today = datetime.now().strftime("%Y-%m-%d")
    con = db()
    row = con.execute("SELECT points, last_daily FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        con.close()
        return "nouser", 0
    last = row["last_daily"] or ""
    if last == today:
        con.close()
        return "already", row["points"]
    con.execute("UPDATE users SET points = points + ?, last_daily = ? WHERE user_id=?",
                (DAILY_BONUS_POINTS, today, uid))
    con.commit()
    bal = con.execute("SELECT points FROM users WHERE user_id=?", (uid,)).fetchone()["points"]
    con.close()
    return "claimed", bal


def get_history(uid: int, limit: int = 10) -> tuple[list[dict], int]:
    con = db()
    rows = con.execute("SELECT phone, display_name, status, created_at FROM numbers "
                       "WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (uid, limit)).fetchall()
    total = con.execute("SELECT COUNT(*) c FROM numbers WHERE user_id=?", (uid,)).fetchone()["c"]
    con.close()
    return [dict(r) for r in rows], total


def get_leaderboard(limit: int = 10) -> list[dict]:
    con = db()
    rows = con.execute("SELECT user_id, total_refers, points FROM users "
                       "ORDER BY total_refers DESC, points DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_user_profile(uid: int) -> str | None:
    """Full profile card for admin search. Returns None if user not found."""
    u = get_user(uid)
    if not u:
        return None
    con = db()
    num_total = con.execute("SELECT COUNT(*) c FROM numbers WHERE user_id=?", (uid,)).fetchone()["c"]
    last_nums = con.execute("SELECT phone, status, created_at FROM numbers WHERE user_id=? "
                            "ORDER BY created_at DESC LIMIT 3", (uid,)).fetchall()
    refs = con.execute("SELECT referred_id FROM referrals WHERE referrer_id=? "
                       "ORDER BY created_at DESC LIMIT 5", (uid,)).fetchall()
    con.close()
    ref_by = u["referred_by"] or "Direct"
    code = u["stockgro_code"] or DEFAULT_STOCKGRO_CODE
    card = (f"*USER DETAILS*\n------------------------\n"
            f"ID: `{u['user_id']}`\n"
            f"Username: @{u['username'] or '-'} \n"
            f"Name: {u['first_name'] or '-'}\n"
            f"Points: *{u['points']}*\n"
            f"Referrals: *{u['total_refers']}*\n"
            f"StockGro Code: `{code}`\n"
            f"Referred By: `{ref_by}`\n"
            f"Joined: {u['joined_at']}\n"
            f"Numbers Done: *{num_total}*")
    if last_nums:
        card += "\n\nLast numbers:\n" + "\n".join(
            f"`{n['phone']}` ({n['status']}, {n['created_at']})" for n in last_nums)
    if refs:
        card += "\n\nReferred users:\n" + ", ".join(f"`{r['referred_id']}`" for r in refs)
    return card


def get_rank(uid: int) -> int | None:
    con = db()
    row = con.execute("SELECT total_refers FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        con.close()
        return None
    rank = con.execute("SELECT COUNT(*)+1 r FROM users WHERE total_refers > ?",
                       (row["total_refers"],)).fetchone()["r"]
    con.close()
    return rank


def deduct_point(uid: int) -> bool:
    """Deducts 1 point only when balance >= COST. Returns True if deducted."""
    con = db()
    row = con.execute("SELECT points FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row or row["points"] < COST_PER_USE:
        con.close()
        return False
    con.execute("UPDATE users SET points = points - ? WHERE user_id=?", (COST_PER_USE, uid))
    con.commit()
    con.close()
    return True


def set_stockgro_code(uid: int, code: str):
    con = db()
    con.execute("UPDATE users SET stockgro_code=? WHERE user_id=?", (code, uid))
    con.commit()
    con.close()


def is_number_used(phone: str) -> bool:
    con = db()
    row = con.execute("SELECT * FROM numbers WHERE phone=?", (phone,)).fetchone()
    con.close()
    if row:
        return True
    # file fallback (compatibility with the older standalone script)
    try:
        if USED_NUMBERS_FILE.exists():
            used = {l.strip() for l in USED_NUMBERS_FILE.read_text().splitlines() if l.strip()}
            return phone in used
    except Exception:
        pass
    return False


def save_success(phone: str, uid: int, display_name: str, sg_user_id: str, refcode: str):
    con = db()
    con.execute("INSERT OR REPLACE INTO numbers(phone, user_id, display_name, stockgro_user_id, status, created_at)"
                " VALUES(?,?,?,?,?,?)",
                (phone, uid, display_name, sg_user_id, "success",
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()
    try:
        with open(USED_NUMBERS_FILE, "a") as f:
            f.write(f"{phone}\n")
        with open(REFER_FILE, "a") as f:
            f.write(f"{phone} | RefCode: {refcode} | Name: {display_name} | "
                    f"UserID: {sg_user_id} | ByTG: {uid} | Time: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    except Exception as e:
        log.warning("file save fail: %s", e)


def get_channels() -> list[dict]:
    con = db()
    rows = con.execute("SELECT * FROM channels ORDER BY id").fetchall()
    con.close()
    return [dict(r) for r in rows]


# ============================ STOCKGRO API ============================
def get_server_state() -> str | None:
    try:
        res = requests.get("https://app.stockgro.club", headers={
            "user-agent": "Mozilla/5.0 (Linux; Android 14; SM-A135F) AppleWebKit/537.36 Chrome/151.0.7922.169 Mobile Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}, timeout=12)
        m = re.search(r"state=([^&\"]+)", res.text)
        if m:
            return urllib.parse.unquote(m.group(1))
    except Exception as e:
        log.warning("state fail: %s", e)
    return None


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


def sg_post(url: str, payload: dict, headers: dict) -> dict:
    try:
        return requests.post(url, json=payload, headers=headers, timeout=12).json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_number_registered(phone: str):
    """Returns (ok, is_existing, raw)."""
    state = get_server_state()
    if not state:
        return False, None, {"error": "could not reach StockGro server"}
    d = sg_post(f"{BASE_URL}/getIdentity",
                {"phone_number": phone, "country_code": "IN", "otp_channel": "sms"},
                build_headers(state))
    if not d or not d.get("success"):
        return False, None, d
    return True, bool(d["data"].get("existing_user")), d


def send_otp(phone: str, referral_code: str):
    state = get_server_state()
    if not state:
        return False, None, "server state fail"
    h = build_headers(state)
    sg_post(f"{BASE_URL}/getIdentity",
            {"phone_number": phone, "country_code": "IN", "otp_channel": "sms"}, h)
    d = sg_post(f"{BASE_URL}/login/createOtp",
                {"phone_number": phone, "country_code": "IN", "otp_channel": "sms",
                 "invitation_code": referral_code, "flow_type": "signup"}, h)
    if not d or not d.get("success"):
        return False, None, d
    return True, {"session_id": d["data"]["session_id"], "state": state}, d


def verify_and_register(phone: str, otp: str, session_id: str, state: str, referral_code: str):
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    h = build_headers(state)
    v = sg_post(f"{BASE_URL}/login/validateOtp",
                {"session_id": session_id, "otp": otp, "phone_number": phone,
                 "country_code": "IN", "otp_channel": "sms", "flow_type": "signup"}, h)
    if not v or not v.get("success"):
        return False, f"OTP is incorrect or expired.\n`{str(v)[:300]}`", None
    r = sg_post(f"{BASE_URL}/signup/registerUser",
                {"display_name": name, "invitation_code": referral_code, "otp": otp,
                 "session_id": session_id, "whatsapp_consent": True,
                 "phone_number": phone, "country_code": "IN", "otp_channel": "sms"}, h)
    if not r or not r.get("success"):
        return False, f"Registration failed.\n`{str(r)[:300]}`", None
    sg_uid = r["data"].get("user_id", "")
    try:
        code = r["data"].get("redirect_uri", "").split("access_code=")[-1]
        if code:
            sg_post("https://app.stockgro.club/api/login", {"code": code}, h)
    except Exception:
        pass
    return True, name, sg_uid


# ============================ UI HELPERS ============================
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def not_spam(uid: int) -> bool:
    now = time.time()
    if now - _last_msg_time.get(uid, 0) < SPAM_COOLDOWN_SEC:
        return False
    _last_msg_time[uid] = now
    return True


def main_menu_kb(is_adm: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🎁 Set Refer Code", callback_data="m_setcode",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_BLUE),
         InlineKeyboardButton("📱 New Number", callback_data="m_number",
                              style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_GREEN)],
        [InlineKeyboardButton("📊 Dashboard", callback_data="m_dash",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_OFFERS),
         InlineKeyboardButton("👥 My Referrals", callback_data="m_refers",
                              style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_RENEW)],
        [InlineKeyboardButton("🎁 Daily Bonus", callback_data="m_daily",
                              style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_GREEN),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="m_board",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_OFFERS)],
        [InlineKeyboardButton("🕘 My History", callback_data="m_hist",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_BLUE),
         InlineKeyboardButton("❓ Help", callback_data="m_help")],
    ]
    if is_adm:
        rows.append([InlineKeyboardButton("👑 Admin Panel", callback_data="m_admin",
                                          style=STYLE_DANGER, icon_custom_emoji_id=ICON_RED)])
    return InlineKeyboardMarkup(rows)


def back_kb(is_adm: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_back")]])


def dashboard_text(u: sqlite3.Row, bot_username: str) -> str:
    link = f"https://t.me/{bot_username}?start=r_{u['user_id']}"
    code = u["stockgro_code"] or DEFAULT_STOCKGRO_CODE
    return (
        "DASHBOARD\n"
        "------------------------\n"
        f"User ID: `{u['user_id']}`\n"
        f"Points: *{u['points']}* (1 use = {COST_PER_USE} pt)\n"
        f"Total Referrals: *{u['total_refers']}* (1 referral = {POINTS_PER_REFER} pts)\n"
        f"StockGro Code: `{code}`\n\n"
        f"Your Referral Link:\n`{link}`\n\n"
        f"Share your link. You earn *{POINTS_PER_REFER} points* for every user who joins."
    )


async def check_force_join(context: ContextTypes.DEFAULT_TYPE, uid: int):
    """Returns (all_joined, missing, debug). Debug holds the raw Telegram
    error so admins can fix configuration issues."""
    if uid in ADMIN_IDS:
        return True, [], ""  # admins are exempt from force-join
    missing = []
    errors = []
    for ch in get_channels():
        chat_id = ch["chat_id"]
        try:
            m = await context.bot.get_chat_member(chat_id, uid)
            if m.status in ("left", "kicked"):
                missing.append(ch)
        except Exception as e:
            err = str(e)
            errors.append(f"{chat_id}: {err}")
            log.warning("force-join check fail %s uid=%s: %s", chat_id, uid, err)
            missing.append(ch)  # on error, ask to join (safe side)
    return (len(missing) == 0, missing, " | ".join(errors))


async def show_force_join(msg_target, missing: list[dict], debug: str = ""):
    rows = []
    for ch in missing:
        link = channel_link_for(ch["chat_id"], ch.get("link", ""))
        rows.append([InlineKeyboardButton(f"📢 Join {ch['chat_id']}", url=link,
                                          style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_BLUE)])
    rows.append([InlineKeyboardButton("✅ Verify - I Have Joined", callback_data="verify_join",
                                      style=STYLE_SUCCESS, icon_custom_emoji_id=ICON_RENEW)])
    txt = ("*Channel Membership Required*\n\n"
           "Please join the channel(s) below to use this bot.\n"
           "After joining, tap Verify.")
    # also show the real error to admins so it can be fixed quickly
    if debug and getattr(msg_target, "chat", None) is not None:
        try:
            uid = msg_target.chat.id
            if uid in ADMIN_IDS:
                txt += f"\n\nDebug: `{debug[:400]}`\nMake the bot an admin of the channel."
        except Exception:
            pass
    await msg_target.reply_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


# ============================ HANDLERS ============================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or ""
    fname = update.effective_user.first_name or ""

    # bot refer: /start r_123456
    referred_by = None
    if context.args:
        m = re.match(r"r_(\d+)", context.args[0] or "")
        if m:
            try:
                referred_by = int(m.group(1))
            except ValueError:
                referred_by = None

    is_new = ensure_user(uid, username, fname, referred_by)
    u = get_user(uid)

    joined, missing, dbg = await check_force_join(context, uid)
    if not joined:
        await show_force_join(update.message, missing, dbg)
        return

    if is_new and referred_by and referred_by != uid:
        try:
            await context.bot.send_message(
                referred_by,
                f"*New Referral!* +{POINTS_PER_REFER} points\nUser `{uid}` joined using your link.",
                parse_mode="Markdown")
        except Exception:
            pass

    bonus_line = f"\nWelcome bonus: *{BONUS_ON_START} points* credited." if is_new else ""
    await update.message.reply_text(
        "*Welcome to StockGro Referral Bot*\n"
        "------------------------\n"
        "1. *Set Refer Code* - Save the StockGro referral code to use.\n"
        "2. *New Number* - Submit a number, receive the OTP, submit the OTP. Done.\n"
        f"3. Referrals earn *{POINTS_PER_REFER} points*. One successful registration costs *{COST_PER_USE} point*.\n"
        f"{bonus_line}\n"
        f"Your balance: *{u['points']} points*",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(is_admin(uid)))


async def on_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
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
            txt += f"\n\nDebug: `{dbg[:400]}`\nMake the bot an admin of the channel."
        await q.edit_message_text(txt, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup(rows))
        return
    u = get_user(uid)
    await q.edit_message_text(
        "*Verification successful.*\n\nPlease select an option below.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(is_admin(uid)))


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
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
        context.user_data.pop("give_target", None)
        context.user_data.pop("pending", None)
        await q.edit_message_text("*Main Menu*\nPlease select an option.",
                                  parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_setcode":
        context.user_data["awaiting"] = "code"
        await q.edit_message_text(
            "*Set Refer Code*\n\nPlease send your StockGro referral code (e.g. `NIP8OG9M`).\n"
            "Send /cancel to cancel.",
            parse_mode="Markdown", reply_markup=back_kb(is_admin(uid)))
    elif data == "m_number":
        if u["points"] < COST_PER_USE:
            await q.edit_message_text(
                f"*Insufficient points.*\nBalance: *{u['points']}* | Required: *{COST_PER_USE}*\n\n"
                "Share your referral link to earn points. Your link is in Dashboard.",
                parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
            return
        context.user_data["awaiting"] = "number"
        await q.edit_message_text(
            "*Submit Number*\n\nPlease send a 10-digit Indian mobile number (e.g. `98765xxxxx`).\n"
            "If the number is already registered, you will be notified.\nSend /cancel to cancel.",
            parse_mode="Markdown", reply_markup=back_kb(is_admin(uid)))
    elif data == "m_dash":
        await q.edit_message_text(dashboard_text(u, bot_username),
                                  parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_refers":
        link = f"https://t.me/{bot_username}?start=r_{uid}"
        await q.edit_message_text(
            "*MY REFERRALS*\n------------------------\n"
            f"Total referrals: *{u['total_refers']}*\n"
            f"Points: *{u['points']}*\n"
            f"1 referral = *{POINTS_PER_REFER} points* = *{POINTS_PER_REFER} uses*\n\n"
            f"Your link:\n`{link}`",
            parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_help":
        await q.edit_message_text(
            "*HELP*\n------------------------\n"
            "1. Set Refer Code - the StockGro code used for registrations.\n"
            "2. New Number - submit a number:\n"
            "   - New number: OTP is sent. Submit the OTP. *-1 point* on success.\n"
            "   - Already registered: `Try another number` (no points deducted).\n"
            "3. Share your referral link. Every join earns points.\n"
            "4. Claim your Daily Bonus every day for free points.\n"
            "5. No points are deducted for failed or expired OTPs.",
            parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_daily":
        status, bal = claim_daily(uid)
        if status == "claimed":
            await q.edit_message_text(
                f"*Daily Bonus Claimed*\n------------------------\n"
                f"+*{DAILY_BONUS_POINTS}* point added.\nNew balance: *{bal}*.\n\nCome back tomorrow!",
                parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
        else:
            await q.edit_message_text(
                f"*Already Claimed*\n------------------------\n"
                f"You already took today's bonus.\nBalance: *{bal}*.\n\nCome back tomorrow!",
                parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_board":
        top = get_leaderboard(10)
        rank = get_rank(uid)
        medals = ["1st", "2nd", "3rd"]
        lines = []
        for i, r in enumerate(top):
            tag = medals[i] if i < 3 else f"{i+1}th"
            you = " (you)" if r["user_id"] == uid else ""
            lines.append(f"{tag} - `{r['user_id']}` - {r['total_refers']} referrals - {r['points']} pts{you}")
        body = "\n".join(lines) if lines else "No users yet."
        await q.edit_message_text(
            f"*LEADERBOARD - Top Referrers*\n------------------------\n{body}\n\nYour rank: *#{rank}*",
            parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_hist":
        items, total = get_history(uid, 10)
        if items:
            lines = [f"`{h['phone']}` - {h['display_name']} ({h['status']}, {h['created_at']})"
                     for h in items]
            body = "\n".join(lines)
        else:
            body = "No registrations yet. Tap New Number to start."
        await q.edit_message_text(
            f"*MY HISTORY* (total {total})\n------------------------\n{body}",
            parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
    elif data == "m_admin":
        if not is_admin(uid):
            await q.answer("Admin only!", show_alert=True)
            return
        context.user_data.pop("awaiting", None)
        context.user_data.pop("give_target", None)
        context.user_data.pop("pending", None)
        await show_admin(q, context)


async def show_admin(q_or_msg, context):
    is_cb = hasattr(q_or_msg, "edit_message_text")
    text = ("*ADMIN PANEL*\n------------------------\n"
            "Please select an action.")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistics", callback_data="a_stats",
                              style=STYLE_PRIMARY, icon_custom_emoji_id=ICON_BLUE),
         InlineKeyboardButton("👥 Users", callback_data="a_users",
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
    if is_cb:
        await q_or_msg.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await q_or_msg.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def on_admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if not is_admin(uid):
        await q.answer("Admin only!", show_alert=True)
        return
    await q.answer()
    data = q.data
    if data == "a_stats":
        con = db()
        users = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        nums = con.execute("SELECT COUNT(*) c FROM numbers").fetchone()["c"]
        refs = con.execute("SELECT COUNT(*) c FROM referrals").fetchone()["c"]
        pts = con.execute("SELECT COALESCE(SUM(points),0) s FROM users").fetchone()["s"]
        top = con.execute("SELECT user_id, total_refers FROM users ORDER BY total_refers DESC LIMIT 5").fetchall()
        con.close()
        topline = "\n".join([f"{i+1}. `{r['user_id']}` - {r['total_refers']} referrals" for i, r in enumerate(top)]) or "None"
        await q.edit_message_text(
            f"*STATISTICS*\n------------------------\nUsers: *{users}*\nSuccessful numbers: *{nums}*\n"
            f"Referrals: *{refs}*\nTotal points in system: *{pts}*\n\nTop:\n{topline}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("?? 🔙 Back", callback_data="m_admin")]]))
    elif data == "a_users":
        con = db()
        rows = con.execute("SELECT user_id, points, total_refers FROM users ORDER BY rowid DESC LIMIT 10").fetchall()
        total = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        con.close()
        line = "\n".join([f"`{r['user_id']}` | {r['points']} pts | {r['total_refers']} referrals" for r in rows]) or "None"
        await q.edit_message_text(f"*LAST 10 USERS* (total {total})\n------------------------\n{line}",
                                  parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("?? 🔙 Back", callback_data="m_admin")]]))
    elif data == "a_channels":
        chs = get_channels()
        line = "\n".join([f"{c['id']}. `{c['chat_id']}`" for c in chs]) or "None"
        context.user_data["awaiting"] = "admin_addchannel"
        await q.edit_message_text(
            f"*FORCE-JOIN CHANNELS*\n------------------------\n{line}\n\n"
            "To add a channel, just send it here:\n"
            "`@username` or `https://t.me/username`\n"
            "(Or use `/addchannel @username https://t.me/username`)\n"
            "To remove: `/removechannel @username`\n"
            "Send /cancel to cancel.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("?? 🔙 Back", callback_data="m_admin")]]))
    elif data == "a_addpts":
        context.user_data["awaiting"] = "admin_give_id"
        context.user_data.pop("give_target", None)
        await q.edit_message_text("Please send the *User ID* of the user.\n"
                                  "(Or send both at once: `USERID POINTS`, e.g. `123456 10`)\n"
                                  "Send /cancel to cancel.",
                                  parse_mode="Markdown")
    elif data == "a_search":
        context.user_data["awaiting"] = "admin_search"
        await q.edit_message_text("Please send the *User ID* to search.\n"
                                  "Send /cancel to cancel.",
                                  parse_mode="Markdown")
    elif data == "a_bcast":
        context.user_data["awaiting"] = "admin_bcast"
        await q.edit_message_text("Please send the broadcast message (it will go to all users):",
                                  parse_mode="Markdown")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not not_spam(uid):
        return  # silent anti-spam, no extra message
    text = (update.message.text or "").strip()

    if text == "/cancel":
        context.user_data.pop("awaiting", None)
        context.user_data.pop("pending", None)
        await update.message.reply_text("Cancelled.", reply_markup=main_menu_kb(is_admin(uid)))
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
    if state == "admin_search" and is_admin(uid):
        try:
            target = int(text.split()[0])
        except (ValueError, IndexError):
            await update.message.reply_text("Please send a numeric User ID (e.g. `123456`).",
                                            parse_mode="Markdown")
            return
        card = get_user_profile(target)
        context.user_data.pop("awaiting", None)
        if card:
            await update.message.reply_text(card, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"User `{target}` not found.", parse_mode="Markdown")
        return
    if state == "admin_give_id" and is_admin(uid):
        parts = text.split()
        try:
            # shortcut: "USERID POINTS" in one message
            if len(parts) == 2:
                target, pts = int(parts[0]), int(parts[1])
                ok, bal = give_points(target, pts)
                context.user_data.pop("awaiting", None)
                if ok:
                    await update.message.reply_text(
                        f"User `{target}` credited with *{pts}* points.\nNew balance: *{bal}*.",
                        parse_mode="Markdown")
                else:
                    await update.message.reply_text(
                        f"User `{target}` not found. No points added.", parse_mode="Markdown")
                return
            target = int(parts[0])
        except (ValueError, IndexError):
            await update.message.reply_text("Please send a numeric User ID (e.g. `123456`).",
                                            parse_mode="Markdown")
            return
        tu = get_user(target)
        if not tu:
            await update.message.reply_text(f"User `{target}` not found in the database.",
                                            parse_mode="Markdown")
            return
        context.user_data["give_target"] = target
        context.user_data["awaiting"] = "admin_give_pts"
        await update.message.reply_text(
            f"User: `{target}` (balance: *{tu['points']}*, referrals: *{tu['total_refers']}*)\n"
            "How many points to add? Send a number (e.g. `10`).",
            parse_mode="Markdown")
        return
    if state == "admin_give_pts" and is_admin(uid):
        target = context.user_data.get("give_target")
        if not target:
            context.user_data["awaiting"] = "admin_give_id"
            await update.message.reply_text("Please send the *User ID* of the user.",
                                            parse_mode="Markdown")
            return
        try:
            pts = int(text.split()[0])
        except (ValueError, IndexError):
            await update.message.reply_text("Please send a valid number (e.g. `10`).",
                                            parse_mode="Markdown")
            return
        if pts <= 0 or pts > 100000:
            await update.message.reply_text("Points must be between 1 and 100000.",
                                            parse_mode="Markdown")
            return
        ok, bal = give_points(target, pts)
        context.user_data.pop("awaiting", None)
        context.user_data.pop("give_target", None)
        if ok:
            await update.message.reply_text(
                f"User `{target}` credited with *{pts}* points.\nNew balance: *{bal}*.",
                parse_mode="Markdown")
            try:
                await context.bot.send_message(
                    target, f"Your account was credited with *{pts}* points by the admin.\n"
                            f"New balance: *{bal}*.", parse_mode="Markdown")
            except Exception:
                pass
        else:
            await update.message.reply_text(f"User `{target}` not found. No points added.",
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
            await update.message.reply_text("Invalid code. Use only A-Z and 0-9 (4-20 characters). Try again or send /cancel.")
            return
        set_stockgro_code(uid, code)
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"Refer code saved: `{code}`\nNow tap New Number to continue.",
                                        parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
        return

    if state == "number":
        phone = re.sub(r"\D", "", text)[-10:]
        if not re.fullmatch(r"[6-9]\d{9}", phone or ""):
            await update.message.reply_text("Please send a valid 10-digit Indian number starting with 6-9. Or send /cancel.")
            return
        if is_number_used(phone):
            await update.message.reply_text(
                f"This number `{phone}` is *already registered/used.*\nPlease try another number.",
                parse_mode="Markdown")
            return  # NO point deduct
        if u["points"] < COST_PER_USE:
            await update.message.reply_text(f"Insufficient points. Balance: *{u['points']}*. Share your referral link to earn more.",
                                            parse_mode="Markdown")
            return

        wait = await update.message.reply_text("Checking number and sending OTP. Please wait.")
        ok, is_existing, raw = await asyncio.to_thread(check_number_registered, phone)
        if not ok:
            await wait.edit_text(f"Server error. No points deducted. Please try again.\n`{str(raw)[:300]}`",
                                 parse_mode="Markdown")
            return
        if is_existing:
            save_success(phone, uid, "ALREADY_REGISTERED", "-", u["stockgro_code"] or DEFAULT_STOCKGRO_CODE)
            await wait.edit_text(f"`{phone}` is *already registered.*\nPlease try another number.",
                                 parse_mode="Markdown")
            return  # NO point deduct

        refcode = u["stockgro_code"] or DEFAULT_STOCKGRO_CODE
        ok2, sess, raw2 = await asyncio.to_thread(send_otp, phone, refcode)
        if not ok2:
            await wait.edit_text(f"OTP could not be sent. No points deducted.\n`{str(raw2)[:300]}`",
                                 parse_mode="Markdown")
            return
        context.user_data["pending"] = {"phone": phone, "session_id": sess["session_id"],
                                        "state": sess["state"], "refcode": refcode}
        context.user_data["awaiting"] = "otp"
        await wait.edit_text(f"OTP sent to `{phone}`.\n\nPlease send the OTP here. ( /cancel to cancel )",
                             parse_mode="Markdown")
        return

    if state == "otp":
        otp = re.sub(r"\D", "", text)
        if not re.fullmatch(r"\d{4,8}", otp or ""):
            await update.message.reply_text("Please send a valid OTP (digits only). Or send /cancel.")
            return
        pend = context.user_data.get("pending")
        if not pend:
            context.user_data.pop("awaiting", None)
            await update.message.reply_text("Session expired. Please start again with New Number.",
                                            reply_markup=main_menu_kb(is_admin(uid)))
            return
        wait = await update.message.reply_text("Verifying OTP. Please wait.")
        ok, name_or_err, sg_uid = await asyncio.to_thread(
            verify_and_register, pend["phone"], otp,
            pend["session_id"], pend["state"], pend["refcode"])
        if not ok:
            # FAIL = NO deduct
            await wait.edit_text(f"{name_or_err}\n\nNo points deducted. Please try again with a new OTP or number.",
                                 parse_mode="Markdown")
            return
        deducted = deduct_point(uid)
        save_success(pend["phone"], uid, name_or_err, sg_uid, pend["refcode"])
        context.user_data.pop("awaiting", None)
        context.user_data.pop("pending", None)
        nu = get_user(uid)
        await wait.edit_text(
            "*Registration Successful*\n------------------------\n"
            f"Number: `{pend['phone']}`\nName: *{name_or_err}*\n"
            f"Referral code: `{pend['refcode']}`\n"
            f"Points deducted: *{COST_PER_USE}* | Balance: *{nu['points']}*\n\n"
            "Tap New Number for the next registration.",
            parse_mode="Markdown", reply_markup=main_menu_kb(is_admin(uid)))
        return

    # no state -> menu hint
    await update.message.reply_text("Please select an option from the menu.",
                                    reply_markup=main_menu_kb(is_admin(uid)))


# ============================ ADMIN COMMANDS ============================
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied. Admins only.")
        return
    await show_admin(update.message, context)


async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    joined, missing, dbg = await check_force_join(context, uid)
    if not joined:
        await show_force_join(update.message, missing, dbg)
        return
    status, bal = claim_daily(uid)
    if status == "claimed":
        await update.message.reply_text(
            f"*Daily Bonus Claimed*\n+*{DAILY_BONUS_POINTS}* point added.\nNew balance: *{bal}*.",
            parse_mode="Markdown")
    elif status == "already":
        await update.message.reply_text(
            f"You already took today's bonus.\nBalance: *{bal}*. Come back tomorrow!",
            parse_mode="Markdown")
    else:
        await update.message.reply_text("Please send /start first.")


async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Use: `/userinfo USERID`", parse_mode="Markdown")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("User ID must be numeric.", parse_mode="Markdown")
        return
    card = get_user_profile(target)
    if card:
        await update.message.reply_text(card, parse_mode="Markdown")
    else:
        await update.message.reply_text(f"User `{target}` not found.", parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    con = db()
    users = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    nums = con.execute("SELECT COUNT(*) c FROM numbers").fetchone()["c"]
    refs = con.execute("SELECT COUNT(*) c FROM referrals").fetchone()["c"]
    con.close()
    await update.message.reply_text(f"Users: {users} | Numbers: {nums} | Referrals: {refs}")


async def cmd_addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 1:
        await update.message.reply_text(
            "Use:\n`/addchannel @viedietlooters https://t.me/viedietlooters`\n"
            "ya sirf link: `/addchannel https://t.me/viedietlooters`", parse_mode="Markdown")
        return
    raw = context.args[0]
    link = context.args[1] if len(context.args) > 1 else ""
    # if the first arg is a link, derive the username from it
    if "t.me" in raw:
        link = raw if not link else link
        chat_id = normalize_channel(raw)
    else:
        chat_id = normalize_channel(raw)
    if not link:
        link = channel_link_for(chat_id, "")
    con = db()
    con.execute("INSERT OR REPLACE INTO channels(chat_id, link) VALUES(?,?)", (chat_id, link))
    con.commit()
    con.close()
    await update.message.reply_text(f"Channel added: {chat_id}\n{link}\n\nImportant: make the bot an admin of that channel.", parse_mode="Markdown")


async def cmd_setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Replace all channels with a single one. Example: /setchannel https://t.me/viedietlooters"""
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
    """Full diagnostic: checks whether the bot can read the channel."""
    if not is_admin(update.effective_user.id):
        return
    chs = get_channels()
    if not chs:
        await update.message.reply_text("No channel in database. Run `/setchannel https://t.me/viedietlooters`")
        return
    out = ["*CHANNEL CHECK*"]
    me = await context.bot.get_me()
    out.append(f"Bot: @{me.username} (`{me.id}`)")
    for ch in chs:
        out.append(f"\n`{ch['chat_id']}`\n{ch.get('link','')}")
        try:
            info = await context.bot.get_chat(ch["chat_id"])
            out.append(f"get_chat OK: {info.type} | {getattr(info,'title','')}")
        except Exception as e:
            out.append(f"get_chat FAILED: `{str(e)[:200]}`")
            out.append("Check the username spelling. For a private channel, use its numeric ID.")
            continue
        try:
            bm = await context.bot.get_chat_member(ch["chat_id"], me.id)
            out.append(f"Bot status: `{bm.status}`" + (" (OK)" if bm.status in ("administrator","creator","member") else " - MAKE THE BOT AN ADMIN."))
        except Exception as e:
            out.append(f"Bot membership check FAILED: `{str(e)[:200]}`")
            out.append("Make the bot an admin of the channel, otherwise join verification will not work.")
        try:
            um = await context.bot.get_chat_member(ch["chat_id"], update.effective_user.id)
            out.append(f"Your status: `{um.status}`")
        except Exception as e:
            out.append(f"Your check FAILED: `{str(e)[:150]}`")
    out.append("\nIf everything is OK, users will see the Join + Verify screen.\n'member list is inaccessible' means the bot is not an admin.")
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
        add_points(int(context.args[0]), int(context.args[1]))
        await update.message.reply_text(f"{context.args[0]} credited with {context.args[1]} points.")
    except Exception:
        await update.message.reply_text("Use: `/addpoints USERID POINTS`", parse_mode="Markdown")


# ============================ MAIN ============================
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Update %s error: %s", update, context.error, exc_info=context.error)


def main():
    if not BOT_TOKEN or BOT_TOKEN.startswith("PUT_"):
        print("ERROR: BOT_TOKEN is not set. Set the BOT_TOKEN environment variable.")
        return
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("userinfo", cmd_userinfo))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("addchannel", cmd_addchannel))
    app.add_handler(CommandHandler("setchannel", cmd_setchannel))
    app.add_handler(CommandHandler("checkchannel", cmd_checkchannel))
    app.add_handler(CommandHandler("removechannel", cmd_removechannel))
    app.add_handler(CommandHandler("addpoints", cmd_addpoints))
    app.add_handler(CommandHandler("cancel", on_text))

    app.add_handler(CallbackQueryHandler(on_verify, pattern="^verify_join$"))
    app.add_handler(CallbackQueryHandler(on_admin_cb, pattern="^a_"))
    app.add_handler(CallbackQueryHandler(on_menu, pattern="^m_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    print("=" * 55)
    print("🤖 StockGro Refer Bot started!")
    print(f"⭐ {POINTS_PER_REFER} pts/refer | -{COST_PER_USE} pt/use | bonus {BONUS_ON_START}")
    print("=" * 55)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
