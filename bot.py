#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VIEDIET SHOP - Single file Telegram selling bot
Run:  python viediet_shop.py
"""

import json
import os
import time
import html
import threading
import urllib.request
import urllib.error
import urllib.parse

# ============================================================
# CONFIG - edit these
# ============================================================
TOKEN = os.environ.get("BOT_TOKEN")  # @BotFather se token
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1364476174"))            # tera Telegram user id
CURRENCY = "₹"
SUPPORT_LINK = "https://t.me/viedietlooterschat"   # support group link

# ============================================================
# PAYMENT GATEWAY - AUTO VERIFICATION (API-based)
# (QR auto-generate hota hai, payment auto-verify hota hai)
# ============================================================
PAYMENT_API_KEY = os.environ.get("PAYMENT_API_KEY", "PAYB5854A51403EA6F080279257")
PAY_UPI_ID = os.environ.get("PAY_UPI_ID", "paytm.s1dw5n0@pty")
PAYMENT_API_URL = os.environ.get("PAYMENT_API_URL", "https://vcapi.vcstore.site/payment_api.php")
PAYMENT_CHECK_INTERVAL = int(os.environ.get("PAYMENT_CHECK_INTERVAL", "15"))   # seconds
PAYMENT_TIMEOUT_MIN = int(os.environ.get("PAYMENT_TIMEOUT_MIN", "30"))         # order cancel after X min pending

API_BASE = "https://api.telegram.org/bot" + TOKEN
# DATA_FILE: env variable "DATA_FILE" se override ho sakta hai (Railway volume ke liye).
# Railway par volume mount karke DATA_FILE=/data/data.json set karo - data hamesha save rahega.
_DEFAULT_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
DATA_FILE = os.environ.get("DATA_FILE", _DEFAULT_DATA)
if DATA_FILE != _DEFAULT_DATA and not os.path.exists(DATA_FILE) and os.path.exists(_DEFAULT_DATA):
    try:
        import shutil
        shutil.copy(_DEFAULT_DATA, DATA_FILE)
        print("Copied existing data.json to", DATA_FILE)
    except Exception as e:
        print("Data copy error:", e)

# Custom emoji icons (Telegram official sample ids)
ICON_PRIMARY = "5373141891321699086"
ICON_DANGER = "5370810157871667232"
ICON_SUCCESS = "5471984997361523302"


# ============================================================
# DATA STORE
# ============================================================
def fresh_data():
    return {
        "setup": {
            "brand": "Viediet Shop",
            "tagline": "Coupons & Gift Cards - Instant Delivery",
            "welcome": "Welcome! Pick a product, pay via UPI QR and get your codes instantly.",
            "upi_id": "",
            "qr_file_id": "",
            "support": SUPPORT_LINK,
            "terms": ("1. BUY karne se pehle apni SCREEN RECORDING ON karein - poora payment "
                      "aur code delivery record ho.\n"
                      "2. Screen recording ke bina koi REFUND ya REPLACEMENT nahi milega.\n"
                      "3. Payment sirf diye gaye QR se exact amount ka karein.\n"
                      "4. Codes delivery ke baad ek baar hi use hote hain - duplicate / "
                      "repeat nahi hote.\n"
                      "5. Galat UPI ya galat amount se hui payment ka refund nahi hoga.\n"
                      "6. Koi bhi issue ho to support group join karein.")
        },
        "admins": [int(ADMIN_ID)],
        "users": {},
        "products": {},
        "orders": [],
        "seq": {"product": 0, "order": 0},
        "poll_offset": 0
    }


def save_data(data=None):
    if data is None:
        data = DATA
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = fresh_data()
        save_data(data)
    base = fresh_data()
    if "setup" not in data:
        data["setup"] = {}
    for k, v in base["setup"].items():
        data["setup"].setdefault(k, v)
    data.setdefault("admins", [int(ADMIN_ID)])
    data.setdefault("users", {})
    data.setdefault("products", {})
    data.setdefault("orders", [])
    data.setdefault("seq", {"product": 0, "order": 0})
    data["seq"].setdefault("product", 0)
    data["seq"].setdefault("order", 0)
    data.setdefault("poll_offset", 0)
    if not data["setup"].get("support") or data["setup"].get("support") == "Type your support contact here":
        data["setup"]["support"] = SUPPORT_LINK
    if int(ADMIN_ID) not in data["admins"]:
        data["admins"].append(int(ADMIN_ID))
    return data


DATA = load_data()


def setup():
    return DATA["setup"]


def is_admin(uid):
    return int(uid) in DATA["admins"]


def stock(product):
    return len(product.get("codes", []))


# ============================================================
# TELEGRAM API (pure stdlib - no pip install needed)
# ============================================================
_LAST_ERR_PRINT = {}


def _print_error(method, detail):
    now = time.time()
    if now - _LAST_ERR_PRINT.get(method, 0) > 30:
        _LAST_ERR_PRINT[method] = now
        print("[bot] {} -> {}".format(method, str(detail)[:150]))


def api_call(method, payload=None):
    url = API_BASE + "/" + method
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("ok"):
                return res.get("result")
            _print_error(method, res.get("description", "api error"))
            return None
    except urllib.error.HTTPError as e:
        _print_error(method, "HTTP " + str(e.code) + " " + e.read().decode("utf-8", "ignore")[:200])
        return None
    except Exception as e:
        _print_error(method, e)
        return None


def send_message(chat_id, text, kb=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if kb is not None:
        payload["reply_markup"] = kb
    result = api_call("sendMessage", payload)
    if result is None and kb is not None:
        # retry without fancy keyboard (safety net)
        plain = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        return api_call("sendMessage", plain)
    return result


def send_photo(chat_id, file_id, caption=None, kb=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "photo": file_id}
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = parse_mode
    if kb is not None:
        payload["reply_markup"] = kb
    result = api_call("sendPhoto", payload)
    if result is None and kb is not None:
        plain = {"chat_id": chat_id, "photo": file_id}
        if caption:
            plain["caption"] = caption
            plain["parse_mode"] = parse_mode
        return api_call("sendPhoto", plain)
    return result


def send_photo_url(chat_id, image_url, caption=None, kb=None, parse_mode="HTML"):
    """QR image download karke multipart upload - 100% reliable."""
    import uuid as _uuid
    try:
        req = urllib.request.Request(image_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ViedietShop/1.0"
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            img_bytes = resp.read()
        if not img_bytes:
            return None
    except Exception as e:
        _print_error("qr_download", e)
        return None

    boundary = "----Viediet" + _uuid.uuid4().hex
    def _field(name, value):
        return ('--' + boundary + '\r\n'
                'Content-Disposition: form-data; name="{}"\r\n\r\n{}\r\n').format(name, value).encode("utf-8")
    def _photo():
        return ('--' + boundary + '\r\n'
                'Content-Disposition: form-data; name="photo"; filename="qr.png"\r\n'
                'Content-Type: image/png\r\n\r\n').encode("utf-8") + img_bytes + b'\r\n'
    body = b""
    body += _field("chat_id", str(chat_id))
    body += _photo()
    if caption:
        body += _field("caption", caption)
        body += _field("parse_mode", parse_mode)
    if kb is not None:
        body += _field("reply_markup", json.dumps(kb))
    body += ('--' + boundary + '--\r\n').encode("utf-8")

    url = API_BASE + "/sendPhoto"
    req2 = urllib.request.Request(url, data=body, headers={
        "Content-Type": "multipart/form-data; boundary=" + boundary,
        "Content-Length": str(len(body)),
        "User-Agent": "Mozilla/5.0 ViedietShop/1.0"
    })
    try:
        with urllib.request.urlopen(req2, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("ok"):
                return res.get("result")
            _print_error("sendPhoto", res.get("description", "api error"))
            return None
    except urllib.error.HTTPError as e:
        _print_error("sendPhoto", "HTTP " + str(e.code) + " " + e.read().decode("utf-8", "ignore")[:200])
        return None
    except Exception as e:
        _print_error("sendPhoto", e)
        return None


def edit_message(chat_id, msg_id, text, kb=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": parse_mode}
    if kb is not None:
        payload["reply_markup"] = kb
    return api_call("editMessageText", payload)


def answer_cb(cb_id, text=None):
    payload = {"callback_query_id": cb_id}
    if text:
        payload["text"] = text
    return api_call("answerCallbackQuery", payload)


def set_reaction(chat_id, message_id, emoji):
    """Message par emoji reaction lagao (Telegram setMessageReaction)."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reaction": [{"type": "emoji", "emoji": emoji}]
    }
    return api_call("setMessageReaction", payload)


# ============================================================
# BUTTON BUILDERS (colored buttons supported)
# ============================================================
def btn(text, data, style=None, icon=None):
    text = str(text)
    if len(text) > 60:
        text = text[:57] + "..."
    b = {"text": text, "callback_data": data}
    if style:
        b["style"] = style
    if icon:
        b["icon_custom_emoji_id"] = icon
    return b


def kb(rows):
    return {"inline_keyboard": rows}


def esc(s):
    return html.escape(str(s))


def money(n):
    return CURRENCY + format(int(n), ",")


def div():
    return "━━━━━━━━━━━━━━━━━"


def bar(pct, width=10):
    """▰▰▱ style progress bar"""
    pct = max(0, min(100, pct))
    full = int(round(pct / 100.0 * width))
    return "▰" * full + "▱" * (width - full)


# ============================================================
# PAYMENT GATEWAY - AUTO VERIFICATION (qrgen.txt logic)
# ============================================================
def pay_txn_id():
    """Unique transaction id - QR aur API dono ke liye (ORD + timestamp)."""
    return "ORD" + str(int(time.time() * 1000))


def pay_qr_url(txn_id, amount):
    """qrgen.txt wala HD QR: quickchart.io size=1000 margin=4 ecLevel=H."""
    upi = ("upi://pay?pa={}"
           "&pn={}"
           "&tid={}"
           "&tr={}"
           "&tn={}"
           "&am={}"
           "&cu=INR").format(PAY_UPI_ID,
                             urllib.parse.quote("Viediet Shop"),
                             txn_id, txn_id,
                             urllib.parse.quote("Viediet Payment"),
                             amount)
    return ("https://quickchart.io/qr"
            "?text=" + urllib.parse.quote(upi) +
            "&size=1000&margin=4&ecLevel=H&format=png")


def pay_check(order):
    """Payment verify karo (check_payment API).
    Returns True=paid, False=nahi mila, None=API error."""
    oid = order.get("txn_id") or order.get("id")
    amount = order.get("total", 0)
    url = "{}?api_key={}&order_id={}&amount={}".format(
        PAYMENT_API_URL, urllib.parse.quote(PAYMENT_API_KEY),
        urllib.parse.quote(str(oid)), urllib.parse.quote(str(amount)))
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ViedietShop/1.0"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _print_error("pay_check", e)
        return None
    st = str(res.get("status", "")).lower()
    if st in ("success", "paid", "received", "completed", "confirmed"):
        return True
    if st in ("error", "failed", "pending", "not received"):
        return False
    return False


def cb_check(cid, uid, oid, cb_id):
    """'Check Payment' dabaya -> verify + auto deliver."""
    answer_cb(cb_id, "Verifying...")
    o = next((x for x in DATA["orders"] if x["id"] == oid and x["userId"] == uid), None)
    if not o:
        return send_message(cid, "😕 Order not found.",
                            kb([[btn("🏠 Home", "home")]]))
    if o["status"] != "pending":
        return send_message(cid,
                            "✅ Order <b>#{}</b> already handled: {}.\n"
                            "My Orders mein codes + receipt dekh lo.".format(o["id"], status_label(o)),
                            kb([[btn("📦 My Orders", "myorders")], [btn("🏠 Home", "home")]]))
    if pay_check(o):
        if auto_deliver(o):
            return
        return send_message(cid, "⚠️ Payment mil gayi lekin stock khatam - admin ko bata diya gaya.",
                            kb([[btn("📦 My Orders", "myorders")]]))
    send_message(cid,
                 "⏳ <b>Payment abhi tak receive nahi hui.</b>\n\n"
                 "🆔 Order: <b>#{}</b>\n"
                 "💰 Amount: <b>{}</b>\n\n"
                 "Jaisi hi payment aayegi, codes <b>AUTOMATICALLY</b> mil jayenge. "
                 "Kuch bhi nahi karna - bas wait karo! 🔄".format(o["id"], money(o["total"])),
                 kb([[btn("🔄 Check Payment", "check:" + o["id"], "primary", ICON_PRIMARY)],
                     [btn("📦 My Orders", "myorders")]]))


def payment_worker():
    """Background thread - har interval mein pending orders verify karta hai.
    Payment milte hi codes AUTO-DELIVER."""
    last_check = {}
    while True:
        time.sleep(PAYMENT_CHECK_INTERVAL)
        try:
            now_ms = int(time.time() * 1000)
            for o in DATA["orders"]:
                if o.get("status") != "pending":
                    continue
                # payment karne ke liye thoda time do (15 sec)
                if now_ms - o.get("at", 0) < 15000:
                    continue
                if now_ms - last_check.get(o["id"], 0) < PAYMENT_CHECK_INTERVAL * 1000:
                    continue
                last_check[o["id"]] = now_ms
                if pay_check(o):
                    print("[pay] Payment confirmed for order", o["id"])
                    auto_deliver(o)
        except Exception as e:
            _print_error("pay_worker", e)


# ============================================================
# TEXTS & KEYBOARDS (user side)
# ============================================================
def home_text():
    s = setup()
    return ("✨ <b>{}</b> ✨\n"
            "<i>{}</i>\n"
            "{}\n"
            "━━━━━━━━━━━━━━━━━\n"
            "👋 Namaste! Niche se <b>Shop</b> karo aur instant codes pao! 🎁").format(
        esc(s["brand"]), esc(s["tagline"]), esc(s["welcome"]))


def home_keys(chat_id):
    rows = [
        [btn("🛍️ Shop Products", "shop", "primary", ICON_PRIMARY)],
        [btn("📦 My Orders", "myorders"), {"text": "🆘 Support", "url": SUPPORT_LINK}]
    ]
    if is_admin(chat_id):
        rows.append([btn("⚙️ Admin Panel", "admin", "success", ICON_SUCCESS)])
    return rows


def send_home(chat_id):
    send_message(chat_id, home_text(), kb(home_keys(chat_id)))


def product_list():
    return sorted(DATA["products"].values(), key=lambda p: (p.get("category", ""), p.get("name", "")))


def catalog_text():
    s = setup()
    t = ("🛒 <b>{}</b>\n"
         "<i>{}</i>\n"
         "📋 <b>CATALOG</b>\n"
         "{}").format(esc(s["brand"]), esc(s["tagline"]), div())
    plist = product_list()
    if not plist:
        return t + "\n\n😕 <i>No products yet - check back soon!</i>"
    for p in plist:
        st = stock(p)
        if st > 0:
            t += ("\n\n✅ <b>{}</b>\n"
                  "   🗂️ {} · 💰 {}\n"
                  "   🎟️ Stock: {} left").format(
                esc(p.get("name", "")), esc(p.get("category", "General")),
                money(p.get("price", 0)), st)
        else:
            t += "\n\n❌ <s><b>{}</b> - SOLD OUT</s>".format(esc(p.get("name", "")))
    return t + "\n\n{}".format(div())


def catalog_keys():
    rows = []
    for p in product_list():
        if stock(p) > 0:
            rows.append([btn("🛒 BUY " + esc(p.get("name", "")), "p:" + p["id"], "primary", ICON_PRIMARY)])
        else:
            rows.append([btn("❌ SOLD OUT - " + esc(p.get("name", "")), "noop")])
    rows.append([btn("◀️ Back to menu", "home")])
    return rows


def product_text(p, uid):
    q = get_qty(uid, p["id"])
    per = p.get("price", 0)
    return ("🛍️ <b>PRODUCT DETAILS</b>\n"
            "{}\n"
            "📦 <b>{}</b>\n"
            "🗂️ Category: <i>{}</i>\n"
            "━━━━━━━━━━━━━━━━━\n"
            "💰 Price: <b>{}</b> / code\n"
            "🎟️ Available: <b>{}</b>\n"
            "━━━━━━━━━━━━━━━━━\n"
            "🔢 Qty: <b>{}</b>  (➖/➕ se change karo)\n"
            "💎 <b>Total: {}</b>\n"
            "━━━━━━━━━━━━━━━━━\n"
            "👇 Total paise ke liye <b>BUY NOW</b> dabao").format(
        div(), esc(p.get("name", "")), esc(p.get("category", "General")),
        money(per), stock(p), q, money(per * q))


def product_keys(p, uid):
    q = get_qty(uid, p["id"])
    return [
        [btn("➖", "qdec:" + p["id"]), btn("  {}  ".format(q), "noop"), btn("➕", "qinc:" + p["id"])],
        [btn("1", "qset:{}:1".format(p["id"])), btn("2", "qset:{}:2".format(p["id"])),
         btn("3", "qset:{}:3".format(p["id"])), btn("5", "qset:{}:5".format(p["id"])),
         btn("10", "qset:{}:10".format(p["id"]))],
        [btn("✍️ Custom Qty (type karo)", "qtype:" + p["id"], "primary")],
        [btn("💳 BUY NOW - {}".format(money(p.get("price", 0) * q)), "pay:" + p["id"], "success", ICON_SUCCESS)],
        [btn("◀️ Back to catalog", "shop")]
    ]


def status_label(o):
    return {"pending": "⏳ Waiting", "delivered": "✅ Delivered", "rejected": "❌ Rejected"}.get(o["status"], o["status"])


# ============================================================
# SESSIONS
# ============================================================
ADMIN_DRAFT = {}   # user_id -> {"type": ..., "name": ..., "price": ..., "productId": ...}
QTY_SEL = {}       # "uid:pid" -> qty
QTY_INPUT = {}     # uid -> {"pid": .., "mid": ..}  (custom qty typing mode)


def get_qty(uid, pid):
    return QTY_SEL.get("{}:{}".format(uid, pid), 1)


def set_qty(uid, pid, q):
    key = "{}:{}".format(uid, pid)
    if q <= 0:
        QTY_SEL.pop(key, None)
    else:
        QTY_SEL[key] = min(q, 50)


# ============================================================
# ORDER FLOW
# ============================================================
def create_order(uid, username, pid, qty):
    p = DATA["products"][pid]
    DATA["seq"]["order"] += 1
    order = {
        "id": "ORD" + str(DATA["seq"]["order"]).zfill(4),
        "txn_id": pay_txn_id(),
        "userId": uid,
        "userName": username,
        "productId": pid,
        "productName": p.get("name", ""),
        "qty": qty,
        "price": p.get("price", 0),
        "total": p.get("price", 0) * qty,
        "status": "pending",
        "codes": [],
        "at": int(time.time() * 1000)
    }
    DATA["orders"].append(order)
    save_data()
    return order


def notify_admins(order):
    s = setup()
    cap = ("💳 <b>New Order Placed</b>\n"
           "━━━━━━━━━━━━━━━━\n"
           "🆔 ID: <b>#{}</b>\n"
           "👤 User: {} (id: {})\n"
           "🛍️ Product: {} x{}\n"
           "💰 Total: <b>{}</b>\n"
           "🆔 Txn: <code>{}</code>\n"
           "📊 Status: ⏳ Auto-verify in process - payment aate hi codes deliver honge").format(
        order["id"], esc(order["userName"]), order["userId"],
        esc(order["productName"]), order["qty"], money(order["total"]),
        order.get("txn_id", "-"))
    for aid in DATA["admins"]:
        send_message(aid, cap)


def notify_paid(order, file_id):
    s = setup()
    cap = ("⏳ <b>Payment Claimed - Verify Karein!</b>\n"
           "━━━━━━━━━━━━━━━━\n"
           "🆔 Order: <b>#{}</b>\n"
           "👤 User: {} (id: {})\n"
           "🛍️ Product: {} x{}\n"
           "💰 Expected: <b>{}</b>\n"
           "🏦 UPI: <code>{}</code>\n"
           "━━━━━━━━━━━━━━━━\n"
           "👇 Screenshot upar hai - amount match karke <b>DELIVER</b> ya <b>REJECT</b> karein.").format(
        order["id"], esc(order["userName"]), order["userId"],
        esc(order["productName"]), order["qty"], money(order["total"]),
        esc(s["upi_id"]) if s.get("upi_id") else "-")
    rows = [
        [btn("✅ DELIVER CODES", "deliver:" + order["id"], "success", ICON_SUCCESS),
         btn("❌ REJECT", "reject:" + order["id"], "danger", ICON_DANGER)]
    ]
    for aid in DATA["admins"]:
        if file_id:
            send_photo(aid, file_id, cap, kb(rows))
        else:
            send_message(aid, cap + "\n\n<i>(⚠️ bina screenshot ke claim)</i>", kb(rows))


# ============================================================
# USER CALLBACKS
# ============================================================
def cb_home(cid, uid):
    send_home(cid)


def cb_shop(cid, uid):
    send_message(cid, catalog_text(), kb(catalog_keys()))


def cb_support(cid, uid):
    send_message(cid,
                 "🆘 <b>Support</b>\n\n"
                 "Kisi bhi problem ke liye hamare <b>support group</b> me join karein:\n\n"
                 "<a href=\"{}\">🔗 Join Group - @viedietlooterschat</a>\n\n"
                 "👇 Direct open karne ke liye button dabayein:".format(SUPPORT_LINK),
                 kb([[{"text": "💬 Open Support Group", "url": SUPPORT_LINK, "style": "primary"}],
                     [btn("◀️ Back", "home")]]))


def cb_myorders(cid, uid):
    mine = [o for o in DATA["orders"] if o["userId"] == uid][-10:]
    if not mine:
        send_message(cid, "📦 <b>My Orders</b>\n\n😕 Aapke paas abhi koi order nahi hai.",
                     kb([[btn("🛍️ Shop now", "shop", "primary", ICON_PRIMARY)]]))
        return
    t = "📦 <b>MY ORDERS</b>\n{}".format(div())
    for o in mine:
        t += "\n\n🧾 <b>#{}</b>  {}\n   {} x{} = <b>{}</b>".format(
            o["id"], status_label(o), esc(o["productName"]), o["qty"], money(o["total"]))
        if o["status"] == "delivered" and o.get("codes"):
            shown = esc("\n".join(o["codes"][:3]))
            if len(o["codes"]) > 3:
                shown += "\n..."
            t += "\n   🎟️ <code>{}</code>".format(shown)
            rp = DATA["products"].get(o["productId"])
            if rp and rp.get("redeem"):
                t += "\n   📝 <i>Redeem guide: {}</i>".format(esc(rp["redeem"]))
    send_message(cid, t + "\n\n" + div(), kb([[btn("◀️ Back", "home")]]))


def cb_product(cid, uid, pid, mid=None):
    p = DATA["products"].get(pid)
    if not p:
        return
    if mid:
        edit_message(cid, mid, product_text(p, uid), kb(product_keys(p, uid)))
    else:
        send_message(cid, product_text(p, uid), kb(product_keys(p, uid)))


def user_display(cb):
    f = cb.get("from", {})
    n = f.get("first_name", "user")
    if f.get("last_name"):
        n += " " + f["last_name"]
    if f.get("username"):
        n += " @" + f["username"]
    return n


PAY_THROTTLE = {}
PENDING_SS = {}   # uid -> order id (user ne paid dabaya, screenshot ka wait)


def cb_pay(cid, uid, pid, cb_id, cb=None):
    """STEP 1: BUY dabate hi Terms & Conditions dikhao. Accept kare bina aage nahi."""
    if cb_id:
        answer_cb(cb_id)
    p = DATA["products"].get(pid)
    if not p:
        return send_message(cid, "😕 Product not found.",
                            kb([[btn("◀️ Back to catalog", "shop")]]))
    s = setup()
    q = get_qty(uid, pid)
    if not s.get("upi_id") and not s.get("qr_file_id"):
        return send_message(cid, "⚠️ Payment methods not set up yet - try again later.",
                            kb([[btn("◀️ Back to catalog", "shop")]]))
    if stock(p) < q:
        return send_message(cid, "⚠️ Only {} codes left in stock.".format(stock(p)),
                            kb([[btn("◀️ Back to catalog", "shop")]]))
    key = "{}:{}".format(uid, pid)
    now_t = time.time()
    if now_t - PAY_THROTTLE.get(key, 0) < 8:
        return
    PAY_THROTTLE[key] = now_t

    terms = s.get("terms") or ""
    msg = ("📜 <b>TERMS & CONDITIONS</b>\n"
           "{}\n"
           "🛍️ Product: <b>{}</b>\n"
           "🔢 Qty: {} · 💰 Total: <b>{}</b>\n"
           "{}\n\n"
           "<b>⚠️ BUY karne se pehle padhein:</b>\n\n"
           "{}\n\n"
           "👇 Screen recording <b>ON</b> kar ke hi <b>I AGREE</b> dabayein. "
           "Screen recording ke bina <b>NO REFUND / NO REPLACEMENT</b> milega.\n"
           "{}").format(
        div(), esc(p.get("name", "")), q, money(p.get("price", 0) * q), div(),
        esc(terms), div())
    rows = [
        [btn("✅ I AGREE - Continue", "tac:" + pid, "success", ICON_SUCCESS)],
        [btn("❌ Decline", "home", "danger", ICON_DANGER)]
    ]
    send_message(cid, msg, kb(rows))


def cb_pay_accept(cid, uid, pid, cb_id, cb=None):
    """STEP 2: T&C accept hone ke baad QR + exact amount."""
    answer_cb(cb_id)
    p = DATA["products"].get(pid)
    if not p:
        return
    s = setup()
    q = get_qty(uid, pid)
    if stock(p) < q:
        return send_message(cid, "⚠️ Only {} codes left.".format(stock(p)),
                            kb([[btn("◀️ Back to catalog", "shop")]]))
    now = int(time.time() * 1000)
    dup = any(o["userId"] == uid and o["productId"] == pid and o["status"] == "pending"
              and now - o["at"] < 300000 for o in DATA["orders"])
    if dup:
        return send_message(cid,
                            "<b>📦 Order already placed!</b>\n\n"
                            "Aapka ek pending order already hai. Payment verify hote hi "
                            "codes mil jayenge. Check: My Orders",
                            kb([[btn("📦 My Orders", "myorders")], [btn("🏠 Home", "home")]]))
    uname = user_display(cb) if cb else "user"
    order = create_order(uid, uname, pid, q)
    QTY_SEL.pop("{}:{}".format(uid, pid), None)

    cap = ("🛒 <b>ORDER PLACED - #{}</b>\n"
           "{}\n"
           "🏪 <b>{}</b>\n"
           "{}\n"
           "📦 Product: <b>{}</b> x{}\n"
           "💰 Total: <b>{}</b>\n"
           "{}\n"
           "👇 <b>PAYMENT STEPS:</b>\n"
           "1️⃣ Upar wala <b>QR scan</b> karein\n"
           "2️⃣ <b>Exact amount</b> ({}) pay karein\n"
           "3️⃣ <b>✅ I HAVE PAID</b> dabayein\n"
           "4️⃣ Payment <b>AUTO-verify</b> hote hi codes mil jayenge 🎁\n"
           "{}\n"
           "⚡ <b>Fastest Delivery</b> - koi manual wait nahi, sab automatic!").format(
        order["id"], div(), esc(setup()["brand"]), div(),
        esc(p.get("name", "")), q, money(order["total"]), div(),
        money(order["total"]), div())
    rows = [
        [btn("✅ I HAVE PAID", "paid:" + pid, "success", ICON_SUCCESS)],
        [btn("📦 My Orders", "myorders")],
        [btn("❌ Cancel", "home", "danger", ICON_DANGER)]
    ]
    qr_url = pay_qr_url(order["txn_id"], order["total"])
    sent = send_photo_url(cid, qr_url, cap, kb(rows))
    if sent is None:
        sent = send_photo(cid, qr_url, cap, kb(rows))
    if sent is None:
        send_message(cid, cap + "\n\n<i>⚠️ (QR image load nahi hua - dobara try karo, ya support se contact karo)</i>", kb(rows))
    notify_admins(order)


def cb_paid(cid, uid, pid, cb_id, uname="user"):
    """STEP 3: user ne paid dabaya -> AUTO-verify."""
    answer_cb(cb_id, "Payment verify ho raha hai...")
    o = next((x for x in DATA["orders"]
              if x["userId"] == uid and x["productId"] == pid and x["status"] == "pending"), None)
    if not o:
        p = DATA["products"].get(pid)
        if not p:
            return
        q = get_qty(uid, pid)
        if stock(p) < q:
            answer_cb(cb_id, "No stock")
            return
        o = create_order(uid, uname, pid, q)
        QTY_SEL.pop("{}:{}".format(uid, pid), None)
    if pay_check(o):
        if auto_deliver(o):
            return
    send_message(cid,
                 "⏳ <b>Payment check kar rahe hain...</b>\n\n"
                 "🆔 Order: <b>#{}</b>\n"
                 "💰 Amount: <b>{}</b>\n\n"
                 "Payment abhi tak receive nahi hui. Jaisi hi payment aayegi, "
                 "codes <b>AUTOMATICALLY</b> mil jayenge - aapko kuch nahi karna. 🔄".format(
                     o["id"], money(o["total"])),
                 kb([[btn("🔄 Check Payment", "check:" + o["id"], "primary", ICON_PRIMARY)],
                     [btn("📦 My Orders", "myorders")]]))


def cb_noss(cid, uid, oid, cb_id):
    """Screenshot ke bina admin ko notify karo."""
    answer_cb(cb_id)
    o = next((x for x in DATA["orders"] if x["id"] == oid), None)
    if not o:
        return
    PENDING_SS.pop(uid, None)
    notify_paid(o, None)
    send_message(cid,
                 "👌 Admin ko bata diya gaya. Verify hote hi codes mil jayenge.",
                 kb([[btn("📦 My Orders", "myorders")], [btn("🏠 Home", "home")]]))


# ============================================================
# ADMIN PANEL
# ============================================================
def admin_panel(cid):
    send_message(cid,
                 "⚙️ <b>Admin Panel</b>\n\n✨ <b>{}</b>".format(esc(setup()["brand"])),
                 kb([
                     [btn("📦 Products", "ap:prods", "primary", ICON_PRIMARY), btn("➕ New Product", "ap:addprod", "success", ICON_SUCCESS)],
                     [btn("🧾 Orders", "ap:orders"), btn("📊 Stats", "ap:stats")],
                     [btn("🛠️ Settings", "ap:settings"), btn("📣 Broadcast", "ap:bc")],
                     [btn("🏠 Storefront", "home", "danger", ICON_DANGER)]
                 ]))


def ap_products(cid):
    plist = list(DATA["products"].values())
    if not plist:
        send_message(cid, "😕 No products yet.",
                     kb([[btn("➕ Add Product", "ap:addprod", "success", ICON_SUCCESS)],
                         [btn("◀️ Back", "admin")]]))
        return
    rows = [[btn("📦 {} - {} [codes: {}]".format(esc(p.get("name", "")), money(p.get("price", 0)), stock(p)),
                 "aprod:" + p["id"], "primary")] for p in plist]
    rows.append([btn("➕ Add Product", "ap:addprod", "success", ICON_SUCCESS)])
    rows.append([btn("◀️ Back", "admin")])
    send_message(cid, "📦 <b>Products</b> ({})\nTap a product to manage it.".format(len(plist)), kb(rows))


def prod_view(p):
    t = ("📦 <b>{}</b>\n"
         "{}\n"
         "🗂️ Category: <i>{}</i>\n"
         "💰 Price: <b>{}</b>\n"
         "🎟️ Codes: <b>{}</b>\n"
         "📝 Redeem Guide: {}\n"
         "{}").format(
        esc(p.get("name", "")), div(), esc(p.get("category", "General")),
        money(p.get("price", 0)), stock(p),
        "✅ set" if p.get("redeem") else "❌ not set", div())
    if p.get("redeem"):
        t += "\n<i>{}</i>\n".format(esc(p["redeem"]))
    return t


def prod_rows(p):
    return [
        [btn("✏️ Rename", "aedit:name:" + p["id"], "primary"), btn("💰 Price", "aedit:price:" + p["id"])],
        [btn("🗂️ Category", "aedit:cat:" + p["id"]), btn("🎟️ Add Codes", "aedit:codes:" + p["id"], "success", ICON_SUCCESS)],
        [btn("📝 Redeem Guide", "aedit:redeem:" + p["id"], "primary"), btn("👁️ See Codes", "aedit:see:" + p["id"])],
        [btn("🗑️ Delete", "aedit:del:" + p["id"], "danger", ICON_DANGER)],
        [btn("◀️ Back", "ap:prods")]
    ]


def ap_orders(cid):
    orders = DATA["orders"][-15:][::-1]
    if not orders:
        send_message(cid, "😕 No orders yet.", kb([[btn("◀️ Back", "admin")]]))
        return
    t = "🧾 <b>RECENT ORDERS</b>\n{}".format(div())
    rows = []
    for o in orders:
        t += "\n\n<b>#{}</b> {}\n   {} x{} = <b>{}</b>".format(
            o["id"], status_label(o), esc(o["productName"]), o["qty"], money(o["total"]))
        rows.append([btn("🧾 Order #" + o["id"], "ord:" + o["id"], "primary")])
    rows.append([btn("◀️ Back", "admin")])
    send_message(cid, t + "\n\n" + div(), kb(rows))


def cb_order(cid, oid):
    o = next((x for x in DATA["orders"] if x["id"] == oid), None)
    if not o:
        return
    t = ("🧾 <b>Order #{}</b>  {}\n"
         "{}\n"
         "👤 User: {} (id: <code>{}</code>)\n"
         "📦 Product: {} x{}\n"
         "💰 Total: <b>{}</b>\n"
         "🕐 Time: {}\n").format(
        o["id"], status_label(o), div(), esc(o["userName"]), o["userId"],
        esc(o["productName"]), o["qty"], money(o["total"]),
        time.strftime("%Y-%m-%d %H:%M", time.localtime(o["at"] / 1000)))
    if o.get("codes"):
        t += "\n🎟️ Delivered:\n<code>{}</code>\n".format(esc("\n".join(o["codes"])))
    if o.get("ss"):
        t += "\n📸 Screenshot attached (upar).\n"
    t += div()
    rows = []
    if o["status"] == "pending":
        rows.append([btn("✅ DELIVER CODES", "deliver:" + o["id"], "success", ICON_SUCCESS),
                     btn("❌ REJECT", "reject:" + o["id"], "danger", ICON_DANGER)])
    rows.append([btn("💬 Message User", "msg:" + o["id"])])
    rows.append([btn("◀️ Back", "ap:orders")])
    send_message(cid, t, kb(rows))


def auto_deliver(o):
    """Codes user ko bhejo aur order delivered mark karo. Returns True on success."""
    p = DATA["products"].get(o["productId"])
    if not p:
        return False
    codes = p.get("codes", [])
    got = codes[:o["qty"]]
    if not got:
        for aid in DATA["admins"]:
            send_message(aid, "⚠️ <b>Paid but no codes!</b>\n\nOrder #{} ({}) ka payment claim hua hai "
                              "lekin stock khatam. User ko manually codes do.".format(o["id"], esc(o["productName"])))
        return False
    p["codes"] = codes[o["qty"]:]
    o["status"] = "delivered"
    o["codes"] = got
    o["paidAt"] = int(time.time() * 1000)
    save_data()
    short = ""
    if len(got) < o["qty"]:
        short = "\n\n<i>Only {} codes were in stock. Admin will contact you about the remaining {}.</i>\n".format(
            len(got), o["qty"] - len(got))
    code_block = "\n".join("<code>{}</code>".format(esc(c)) for c in got)
    redeem_block = ""
    if p.get("redeem"):
        redeem_block = ("\n📝 <b>HOW TO REDEEM / USE:</b>\n"
                        "<i>{}</i>\n".format(esc(p["redeem"])))
    s = setup()
    t = time.strftime("%d %b %Y, %I:%M %p", time.localtime(o["paidAt"] / 1000))
    receipt = ("🎉🎉 <b>PAYMENT CONFIRMED!</b> 🎉🎉\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "🏪 <b>{}</b>\n"
               "✨ <i>{}</i>\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "🧾 <b>ORDER RECEIPT</b>\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "🆔 Order ID: <code>#{}</code>\n"
               "🕐 Date: {}\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "📦 Product: <b>{}</b>\n"
               "🔢 Qty: <b>{}x</b>\n"
               "💰 Paid: <b>{}</b>\n"
               "✅ Status: <b>DELIVERED ✓</b>\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "🎟️ <b>YOUR CODES:</b>\n"
               "┌─────────────────────────┐\n"
               "{}\n"
               "└─────────────────────────┘\n"
               "{}{}"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "🙏 Thank you for shopping!\n"
               "💬 Support: {}\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "⭐ Hamare saath shopping karo - <b>Fastest Delivery in Telegram!</b> ⚡").format(
        esc(s["brand"]), esc(s["tagline"]), o["id"], t,
        esc(o["productName"]), o["qty"], money(o["total"]),
        code_block, short, redeem_block, esc(s.get("support", "-")))
    sent = send_message(o["userId"], receipt,
                        kb([[btn("🛍️ Shop More", "shop", "primary", ICON_PRIMARY),
                             btn("📦 My Orders", "myorders")],
                            [{"text": "🆘 Support", "url": SUPPORT_LINK}]],
                           ))
    if sent:
        mid = sent.get("message_id") if isinstance(sent, dict) else None
        if mid:
            set_reaction(o["userId"], mid, "🎉")
    for aid in DATA["admins"]:
        send_message(aid, "✅ Order <b>#{}</b> deliver kar diya - codes user ko bhej diye.".format(o["id"]))
    return True


def deliver_order(cid, cb_id, oid):
    o = next((x for x in DATA["orders"] if x["id"] == oid), None)
    if not o or o["status"] != "pending":
        answer_cb(cb_id, "Already handled")
        return
    if not auto_deliver(o):
        answer_cb(cb_id, "No codes left in stock!")
        return
    answer_cb(cb_id, "Codes delivered")


def reject_order(cid, cb_id, oid):
    o = next((x for x in DATA["orders"] if x["id"] == oid), None)
    if not o or o["status"] != "pending":
        answer_cb(cb_id, "Already handled")
        return
    o["status"] = "rejected"
    save_data()
    answer_cb(cb_id, "Rejected")
    send_message(o["userId"],
                 "❌ <b>Order #{}</b> reject kar diya gaya.\n"
                 "Agar aapne payment kiya tha to support se baat karein: {}".format(
                     o["id"], esc(setup().get("support", ""))))


def ap_stats(cid):
    delivered = [o for o in DATA["orders"] if o["status"] == "delivered"]
    pending = [o for o in DATA["orders"] if o["status"] == "pending"]
    revenue = sum(o["total"] for o in delivered)
    total_codes = sum(stock(p) for p in DATA["products"].values())
    total_orders = len(DATA["orders"])
    delivered_pct = round(len(delivered) / total_orders * 100) if total_orders else 0
    revenue_pct = min(100, round(revenue / 100) if revenue > 0 else 0)
    send_message(cid,
                 "📊 <b>STORE STATS</b>\n"
                 "{}\n"
                 "👥 Users: <b>{}</b>\n"
                 "📦 Products: <b>{}</b>\n"
                 "🎟️ Live codes: <b>{}</b>\n"
                 "{}\n"
                 "🧾 Total orders: <b>{}</b>\n"
                 "⏳ Pending: {} · ✅ Delivered: <b>{}</b>  {}\n"
                 "💎 Success rate: <b>{}%</b>  {}\n"
                 "💰 Revenue: <b>{}</b>  {}\n"
                 "{}".format(
                     div(), len(DATA["users"]), len(DATA["products"]), total_codes, div(),
                     total_orders, len(pending), len(delivered),
                     bar(len(delivered) / total_orders * 100 if total_orders else 0),
                     delivered_pct, bar(delivered_pct), money(revenue), bar(revenue_pct), div()),
                 kb([[btn("◀️ Back", "admin")]]))


def ap_settings(cid):
    s = setup()
    send_message(cid,
                 "🛠️ <b>Settings</b>\n"
                 "━━━━━━━━━━━━━━━\n"
                 "🏷️ Name: <b>{}</b>\n"
                 "💬 Tagline: <i>{}</i>\n"
                 "🏦 UPI: <code>{}</code>\n"
                 "📱 QR: {}\n"
                 "🆘 Support: {}\n"
                 "👋 Welcome: {}\n"
                 "📜 Terms: {}\n\n"
                 "👇 <i>Tap to change:</i>".format(
                     esc(s["brand"]), esc(s["tagline"]), esc(s.get("upi_id", "")),
                     "✅ set" if s.get("qr_file_id") else "❌ not set",
                     esc(s.get("support", "")), esc(s.get("welcome", "")),
                     "✅ set" if s.get("terms") else "❌ not set"),
                 kb([
                     [btn("🏷️ Name", "as:brand", "primary"), btn("💬 Tagline", "as:tagline")],
                     [btn("🏦 UPI ID", "as:upi", "primary"), btn("📱 QR Image", "as:qr")],
                     [btn("👋 Welcome", "as:welcome"), btn("🆘 Support", "as:support")],
                     [btn("📜 Terms", "as:terms", "success", ICON_SUCCESS)],
                     [btn("◀️ Back", "admin")]
                 ]))


# ============================================================
# CALLBACK DISPATCHER
# ============================================================
def handle_callback(upd):
    cb = upd.get("callback_query")
    if not cb:
        return
    data = cb.get("data", "")
    uid = cb["from"]["id"]
    cid = cb["message"]["chat"]["id"]
    mid = cb["message"]["message_id"]
    cb_id = cb["id"]

    # Spam control: navigation buttons par click karte hi purana message delete
    # (taaki chat na bhare). Edit-in-place (qty +/-) aur payment proof
    # (paid/deliver/reject) wale messages delete NAHI hote.
    DELETE_NAV = ("home", "shop", "support", "myorders", "p:", "pay:", "tac:", "noss:",
                  "admin", "ap:", "aprod:", "aedit:", "as:", "ord:", "qtype:")
    if data.startswith(DELETE_NAV):
        api_call("deleteMessage", {"chat_id": cid, "message_id": mid})

    if data == "noop":
        return answer_cb(cb_id)

    if data == "home":
        answer_cb(cb_id)
        return send_home(cid)
    if data == "shop":
        answer_cb(cb_id)
        return send_message(cid, catalog_text(), kb(catalog_keys()))
    if data == "support":
        answer_cb(cb_id)
        return cb_support(cid, uid)
    if data == "myorders":
        answer_cb(cb_id)
        return cb_myorders(cid, uid)

    if data.startswith("p:"):
        answer_cb(cb_id)
        return cb_product(cid, uid, data[2:])
    if data.startswith("qinc:"):
        p = data[5:]
        set_qty(uid, p, get_qty(uid, p) + 1)
        answer_cb(cb_id)
        return cb_product(cid, uid, p, mid)
    if data.startswith("qdec:"):
        p = data[5:]
        set_qty(uid, p, max(1, get_qty(uid, p) - 1))
        answer_cb(cb_id)
        return cb_product(cid, uid, p, mid)
    if data.startswith("qset:"):
        parts = data[5:].split(":")
        set_qty(uid, parts[0], int(parts[1]))
        answer_cb(cb_id)
        return cb_product(cid, uid, parts[0], mid)
    if data.startswith("qtype:"):
        p = data[6:]
        answer_cb(cb_id)
        res = send_message(cid, "🔢 <b>Kitne codes chahiye?</b>\n"
                                "1 se 50 tak number type karo (e.g. <code>4</code>)\n"
                                "{}",
                           kb([[btn("❌ Cancel", "qcancel")]]))
        mid = res.get("result", {}).get("message_id") if isinstance(res, dict) else None
        QTY_INPUT[uid] = {"pid": p, "mid": mid}
        return
    if data == "qcancel":
        QTY_INPUT.pop(uid, None)
        api_call("deleteMessage", {"chat_id": cid, "message_id": mid})
        return answer_cb(cb_id)
    if data.startswith("pay:"):
        return cb_pay(cid, uid, data[4:], cb_id, cb)
    if data.startswith("tac:"):
        return cb_pay_accept(cid, uid, data[4:], cb_id, cb)
    if data.startswith("paid:"):
        uname = user_display(cb)
        return cb_paid(cid, uid, data[5:], cb_id, uname)
    if data.startswith("noss:"):
        return cb_noss(cid, uid, data[5:], cb_id)
    if data.startswith("check:"):
        return cb_check(cid, uid, data[6:], cb_id)

    if not is_admin(uid):
        return answer_cb(cb_id, "Restricted")

    if data == "admin":
        answer_cb(cb_id)
        return admin_panel(cid)
    if data == "ap:prods":
        answer_cb(cb_id)
        return ap_products(cid)
    if data == "ap:addprod":
        answer_cb(cb_id)
        ADMIN_DRAFT[uid] = {"type": "newname"}
        return send_message(cid, "+ Send the <b>product name</b>, e.g.: Blinkit 200 coupon\n(You can /cancel anytime)")
    if data == "ap:orders":
        answer_cb(cb_id)
        return ap_orders(cid)
    if data == "ap:stats":
        answer_cb(cb_id)
        return ap_stats(cid)
    if data == "ap:settings":
        answer_cb(cb_id)
        return ap_settings(cid)
    if data == "ap:bc":
        answer_cb(cb_id)
        ADMIN_DRAFT[uid] = {"type": "set:broadcast"}
        return send_message(cid, "Send the announcement text. It will go to all users:")

    if data.startswith("ord:"):
        answer_cb(cb_id)
        return cb_order(cid, data[4:])
    if data.startswith("deliver:"):
        return deliver_order(cid, cb_id, data[8:])
    if data.startswith("reject:"):
        return reject_order(cid, cb_id, data[7:])
    if data.startswith("msg:"):
        answer_cb(cb_id)
        ADMIN_DRAFT[uid] = {"type": "msg", "orderId": data[4:]}
        return send_message(cid, "Send the message to forward to the user of order #" + data[4:] + ":")

    if data.startswith("aprod:"):
        answer_cb(cb_id)
        p = DATA["products"].get(data[6:])
        if p:
            return send_message(cid, prod_view(p), kb(prod_rows(p)))
    if data.startswith("aedit:name:"):
        answer_cb(cb_id)
        ADMIN_DRAFT[uid] = {"type": "rename", "productId": data[11:]}
        return send_message(cid, "Send new name:")
    if data.startswith("aedit:price:"):
        answer_cb(cb_id)
        ADMIN_DRAFT[uid] = {"type": "reprice", "productId": data[12:]}
        return send_message(cid, "Send new price (number only), e.g. 30:")
    if data.startswith("aedit:cat:"):
        answer_cb(cb_id)
        ADMIN_DRAFT[uid] = {"type": "recat", "productId": data[10:]}
        return send_message(cid, "Send new category, e.g. Blinkit or Shein:")
    if data.startswith("aedit:codes:"):
        answer_cb(cb_id)
        ADMIN_DRAFT[uid] = {"type": "codes", "productId": data[12:]}
        return send_message(cid, "Send codes to add - <b>one per line</b>:\n\nCODE1234\nCODE5678\nCODE9012")
    if data.startswith("aedit:redeem:"):
        answer_cb(cb_id)
        ADMIN_DRAFT[uid] = {"type": "redeem", "productId": data[13:]}
        return send_message(cid, "Send the <b>Redeem / How-to-use guide</b> for this product.\n"
                                 "Har step nayi line par likho, e.g.:\n\n"
                                 "1. Link kholo aur Spotify par login karo\n"
                                 "2. Code paste karo aur Confirm dabao\n"
                                 "3. 2 mahine ka free subscription activate ho jayega")
    if data.startswith("aedit:see:"):
        answer_cb(cb_id)
        p = DATA["products"].get(data[10:])
        if p:
            codes = p.get("codes", [])
            shown = esc("\n".join(codes[:10]))
            if len(codes) > 10:
                shown += "\n..."
            return send_message(cid, "<b>Codes of</b> {} - total: {}\n\n<code>{}</code>".format(
                esc(p.get("name", "")), len(codes), shown or "none yet"),
                kb([[btn("Back", "aprod:" + p["id"])]]))
    if data.startswith("aedit:del:"):
        answer_cb(cb_id)
        p = DATA["products"].get(data[10:])
        if p:
            return send_message(cid, "Delete <b>{}</b>? All its codes will be removed.".format(esc(p.get("name", ""))),
                                kb([[btn("YES, DELETE", "aedit:dely:" + p["id"], "danger", ICON_DANGER),
                                     btn("NO", "aprod:" + p["id"], "primary")]]))
    if data.startswith("aedit:dely:"):
        pid = data[11:]
        if pid in DATA["products"]:
            del DATA["products"][pid]
            save_data()
        answer_cb(cb_id, "Product deleted")
        return send_message(cid, "Deleted.", kb([[btn("Back", "ap:prods")]]))

    if data.startswith("as:"):
        answer_cb(cb_id)
        field = data[3:]
        ADMIN_DRAFT[uid] = {"type": "set:" + field}
        if field == "qr":
            return send_message(cid, "Send me a <b>photo</b> of your payment QR code. "
                                     "It will be shown to users at checkout.")
        label = {"brand": "brand name", "tagline": "tagline", "upi": "UPI ID",
                 "welcome": "welcome text", "support": "support contact", "terms": "Terms & Conditions"}.get(field, field)
        if field == "terms":
            return send_message(cid, "Send the new <b>Terms & Conditions</b> text. "
                                     "Har line ek point. Screen recording wali baat zaroor include karein:")
        return send_message(cid, "Send new <b>{}</b>:".format(label))

    answer_cb(cb_id)


# ============================================================
# TEXT & PHOTO (admin drafts)
# ============================================================
LAST_TEXT_REPLY = {}


def handle_text(upd):
    msg = upd.get("message")
    if not msg or "text" not in msg:
        return
    uid = msg["from"]["id"]
    cid = msg["chat"]["id"]
    text = msg["text"].strip()

    if text.startswith("/"):
        return

    qin = QTY_INPUT.get(uid)
    if qin:
        p = DATA["products"].get(qin.get("pid"))
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            send_message(cid, "❌ Sirf <b>number</b> type karo, e.g. <code>4</code>:")
            return
        qty = int(digits)
        if qty < 1 or qty > 50:
            send_message(cid, "❌ Qty <b>1 se 50</b> ke beech honi chahiye. Dobara type karo:")
            return
        if p is None or qty > stock(p):
            avail = stock(p) if p else 0
            send_message(cid,
                         "❌ <b>Mana kar diya</b> — sirf <b>{}</b> codes available hain.\n"
                         "Kam qty type karke try karo (ya /cancel).".format(avail))
            return
        del QTY_INPUT[uid]
        if qin.get("mid"):
            api_call("deleteMessage", {"chat_id": cid, "message_id": qin["mid"]})
        set_qty(uid, p["id"], qty)
        send_message(cid, "✅ Qty: <b>{}</b> set ho gayi! 👇".format(qty))
        return cb_pay(cid, uid, p["id"], None, None)

    draft = ADMIN_DRAFT.get(uid)
    if not (draft and is_admin(uid)):
        # anti-spam: reply at most once per 30 seconds per user
        now_t = time.time()
        if now_t - LAST_TEXT_REPLY.get(uid, 0) < 30:
            return
        LAST_TEXT_REPLY[uid] = now_t
        send_message(cid, "🛍️ Buttons use karke shopping karein:",
                     kb([[btn("🛍️ Shop", "shop", "primary", ICON_PRIMARY)]]))
        return

    ttype = draft.get("type")

    if ttype == "newname":
        if not text or len(text) > 60:
            send_message(cid, "Name must be 1-60 characters. Try again:")
            return
        ADMIN_DRAFT[uid] = {"type": "newprice", "name": text}
        return send_message(cid, "Name: <b>{}</b>\n\nNow send the <b>price</b>, e.g. 30:".format(esc(text)))

    if ttype == "newprice":
        price = "".join(ch for ch in text if ch.isdigit() or ch == ".")
        price = float(price) if price else 0
        if price <= 0:
            send_message(cid, "Invalid price. Send a number, e.g. 30:")
            return
        ADMIN_DRAFT[uid] = {"type": "newcat", "name": draft["name"], "price": price}
        return send_message(cid, "Price: <b>{}</b>\n\nNow send the <b>category</b> (e.g. Blinkit, Shein) "
                                 "or type /skip for General:".format(money(price)))

    if ttype == "newcat":
        cat = text if text and text.lower() != "skip" else "General"
        DATA["seq"]["product"] += 1
        pid = "P" + str(DATA["seq"]["product"])
        DATA["products"][pid] = {
            "id": pid, "name": draft["name"], "price": draft["price"],
            "category": cat, "codes": [], "at": int(time.time() * 1000)
        }
        save_data()
        del ADMIN_DRAFT[uid]
        return send_message(cid, "<b>Product created!</b>\n\n" + prod_view(DATA["products"][pid]),
                            kb(prod_rows(DATA["products"][pid])))

    if ttype in ("rename", "reprice", "recat", "codes", "redeem"):
        p = DATA["products"].get(draft.get("productId"))
        if not p:
            del ADMIN_DRAFT[uid]
            return
        if ttype == "rename":
            if not text or len(text) > 60:
                send_message(cid, "Name must be 1-60 characters. Try again:")
                return
            p["name"] = text
            msg = "Renamed to <b>{}</b>".format(esc(text))
        elif ttype == "reprice":
            price = "".join(ch for ch in text if ch.isdigit() or ch == ".")
            price = float(price) if price else 0
            if price <= 0:
                send_message(cid, "Invalid price. Send a number, e.g. 30:")
                return
            p["price"] = price
            msg = "Price updated to <b>{}</b>".format(money(price))
        elif ttype == "recat":
            p["category"] = text if text else "General"
            msg = "Category set to <b>{}</b>".format(esc(p["category"]))
        elif ttype == "redeem":
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if not lines:
                send_message(cid, "Redeem guide kuch nahi mila. Send steps, one per line:")
                return
            p["redeem"] = "\n".join(lines)
            msg = "Redeem guide set ho gaya!"
        else:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if not lines:
                send_message(cid, "No codes found. Send codes, one per line:")
                return
            p.setdefault("codes", []).extend(lines)
            msg = "Added <b>{}</b> codes. Stock is now: <b>{}</b>".format(len(lines), stock(p))
        save_data()
        del ADMIN_DRAFT[uid]
        return send_message(cid, msg + "\n\nDone!", kb([[btn("View product", "aprod:" + p["id"])]]))

    if ttype == "msg":
        o = next((x for x in DATA["orders"] if x["id"] == draft.get("orderId")), None)
        del ADMIN_DRAFT[uid]
        if not o:
            return send_message(cid, "Order not found.")
        ok = send_message(o["userId"], "<b>Admin</b> (order #{}):\n{}".format(o["id"], esc(text)))
        return send_message(cid, "Message sent" if ok else "Could not reach user.")

    if ttype.startswith("set:"):
        field = ttype[4:]
        s = setup()
        if field == "broadcast":
            ok = 0
            fail = 0
            for user_id in DATA["users"]:
                res = send_message(user_id, "<b>Announcement</b>\n\n" + esc(text))
                if res:
                    ok += 1
                else:
                    fail += 1
            del ADMIN_DRAFT[uid]
            return send_message(cid, "Broadcast sent to <b>{}</b> users ({} failed).".format(ok, fail))
        if field == "brand":
            s["brand"] = (text[:60] or s["brand"])
        elif field == "tagline":
            s["tagline"] = (text[:100] or s["tagline"])
        elif field == "upi":
            s["upi_id"] = text
        elif field == "welcome":
            s["welcome"] = text
        elif field == "support":
            s["support"] = text
        elif field == "terms":
            s["terms"] = text
        else:
            return
        save_data()
        del ADMIN_DRAFT[uid]
        return send_message(cid, "Updated!", kb([[btn("Back to panel", "admin")]]))

    del ADMIN_DRAFT[uid]


def handle_photo(upd):
    msg = upd.get("message")
    if not msg or "photo" not in msg:
        return
    uid = msg["from"]["id"]
    cid = msg["chat"]["id"]
    file_id = msg["photo"][-1]["file_id"]
    draft = ADMIN_DRAFT.get(uid)

    # admin: QR image set kar raha hai
    if draft and is_admin(uid) and draft.get("type") == "set:qr":
        setup()["qr_file_id"] = file_id
        save_data()
        del ADMIN_DRAFT[uid]
        return send_message(cid, "✅ QR image updated! Users will now see this QR when paying.",
                            kb([[btn("⚙️ Settings", "ap:settings")]]))

    # user: payment screenshot bhej raha hai
    oid = PENDING_SS.get(uid)
    if oid:
        o = next((x for x in DATA["orders"] if x["id"] == oid), None)
        PENDING_SS.pop(uid, None)
        if o and o["status"] == "pending":
            o["ss"] = file_id
            save_data()
            notify_paid(o, file_id)
            set_reaction(cid, msg["message_id"], "✅")
            return send_message(cid,
                                "📥 <b>Payment proof mil gaya!</b>\n"
                                "━━━━━━━━━━━━━━━━━\n"
                                "🆔 Order: <code>#{}</code>\n"
                                "💳 Amount: <b>{}</b>\n"
                                "━━━━━━━━━━━━━━━━━\n"
                                "👨‍💼 Admin abhi verify kar raha hai...\n"
                                "Amount match hote hi tumhe <b>codes + receipt</b> "
                                "mil jayenge! 🎁".format(o["id"], money(o["total"])),
                                kb([[btn("📦 My Orders", "myorders")], [btn("🏠 Home", "home")]]))
        return


def handle_command(msg, cmd, args):
    uid = msg["from"]["id"]
    cid = msg["chat"]["id"]
    if cmd == "start":
        key = str(uid)
        if key not in DATA["users"]:
            DATA["users"][key] = {"name": msg["from"].get("first_name", "user"), "at": int(time.time())}
            save_data()
        return send_home(cid)
    if cmd == "help":
        return send_message(cid,
                            "🛍️ <b>How to buy:</b>\n"
                            "1️⃣ Catalog kholo\n"
                            "2️⃣ Product + quantity chuno\n"
                            "3️⃣ Terms & Conditions accept karo\n"
                            "4️⃣ QR scan karke pay karo\n"
                            "5️⃣ 📸 Screenshot bhejo\n"
                            "6️⃣ Verify hote hi codes milte hain\n\n"
                            "⚠️ Screen recording ke bina <b>no refund/replacement</b>.\n\n"
                            "🆘 <b>Support:</b>\n" + esc(setup().get("support", "")),
                            kb([[btn("🛍️ Shop", "shop", "primary", ICON_PRIMARY)]]))
    if cmd == "panel" and is_admin(uid):
        return admin_panel(cid)
    if cmd == "cancel":
        ADMIN_DRAFT.pop(uid, None)
        if uid in QTY_INPUT:
            del QTY_INPUT[uid]
        return send_message(cid, "Cancelled.", kb([[btn("Back to menu", "home")]]))
    if cmd == "skip" and is_admin(uid):
        draft = ADMIN_DRAFT.get(uid)
        if draft and draft.get("type") == "newcat":
            handle_text({"message": {"from": msg["from"], "chat": msg["chat"], "text": ""}})


# ============================================================
# MAIN LOOP
# ============================================================
def _keepalive_http():
    """Railway/Hosting par PORT env diya ho to chhota HTTP server chalata hai
    taaki free plan par service sleep na ho (health check / ping se awake rehti hai)."""
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer
        port = int(os.environ.get("PORT", "0"))
        if port <= 0:
            return
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            def log_message(self, *a):
                pass
        HTTPServer(("0.0.0.0", port), H).serve_forever()
    except Exception:
        pass


def main():
    if TOKEN.startswith("PASTE"):
        print("Open viediet_shop.py and set TOKEN and ADMIN_ID first.")
        return
    threading.Thread(target=_keepalive_http, daemon=True).start()
    threading.Thread(target=payment_worker, daemon=True).start()
    print("Viediet Shop bot is running! (Ctrl+C to stop)")
    offset = DATA.get("poll_offset", 0)
    retry = 1
    while True:
        try:
            result = api_call("getUpdates", {
                "offset": offset + 1 if offset else None,
                "timeout": 30,
                "allowed_updates": ["message", "callback_query"]
            })
            if not result:
                time.sleep(retry)
                retry = min(retry * 2, 15)
                continue
            retry = 1
            for upd in result:
                offset = upd["update_id"]
                if "callback_query" in upd:
                    handle_callback(upd)
                elif "message" in upd:
                    msg = upd["message"]
                    if "text" in msg:
                        if msg["text"].startswith("/"):
                            parts = msg["text"].split()
                            cmd = parts[0][1:].split("@")[0]
                            args = parts[1:]
                            handle_command(msg, cmd, args)
                        else:
                            handle_text(upd)
                    elif "photo" in msg:
                        handle_photo(upd)
            DATA["poll_offset"] = offset
            save_data()
        except KeyboardInterrupt:
            print("\nStopped.")
            return
        except Exception as e:
            _print_error("poll", e)
            time.sleep(retry)
            retry = min(retry * 2, 15)


if __name__ == "__main__":
    main()
