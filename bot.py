import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import threading
import pytesseract
from PIL import Image
import io
import re

# ================== SETTINGS YAHAN CHANGE KARO ==================
TOKEN = '8328964087:AAFWAVsZyS6kEnfKBKStX4QsYZeh7dvJokg'          # BotFather se mila token
ADMIN_ID = 1364476174                               # Apna Telegram ID yahan daalo
QR_PHOTO = 'blob:https://web.telegram.org/f9e9770f-079e-4115-bfa8-c037ddb34fd9'                # Apna UPI QR link yahan daalo
TESSERACT_PATH = None  # Windows: 'C:/Program Files/Tesseract-OCR/tesseract.exe' (download from github.com/UB-Mannheim/tesseract/wiki)
# =================================================================

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

bot = telebot.TeleBot(TOKEN)

conn = sqlite3.connect('shop.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (id INTEGER PRIMARY KEY, name TEXT, price INTEGER, code TEXT, available INTEGER DEFAULT 1)''')
c.execute('''CREATE TABLE IF NOT EXISTS pending 
             (user_id INTEGER, product_id INTEGER, utr TEXT, screenshot_id TEXT)''')
conn.commit()

@bot.message_handler(commands=['start'])
def start(message):
    welcome_text = """
🔥 **Welcome to @SheinCouponShopbot** 🔥

Shein Gift Cards & Coupons Shop! 
🇮🇳 Fast Delivery | Instant Codes | Secure Payments

**Commands:**
/products - Available Shein coupons dekho
/help - Payment kaise karo?

Admin ho to /add se naya coupon add karo.
    """
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_msg(message):
    help_text = """
**🛒 Kaise Buy Karo:**
1. /products se coupon choose karo
2. QR pe pay karo (UPI/GPay)
3. UTR bhejo (12 digit)
4. Screenshot bhejo (payment proof)
5. Bot auto-verify karega → Code mil jaayega! ⚡

**Tips:** Clear screenshot bhejo (amount dikhna chahiye). Fake mat try karna, bot detect karega!
    """
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['add'])
def add_product(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Sirf admin (@admin) hi add kar sakta hai!")
        return
    bot.reply_to(message, "Shein coupon ka amount bhejo (jaise: 500 for ₹500 Gift Card)")
    bot.register_next_step_handler(message, get_amount)

def get_amount(message):
    try:
        amount = int(message.text)
        name = f"Shein ₹{amount} Gift Card"
        price = amount  # Selling price same as amount, ya change kar lo (jaise price = amount * 0.9)
        bot.reply_to(message, f"Name: {name}\nPrice: ₹{price}\n\nAb code paste karo (jaise: SG1234567890)")
        bot.register_next_step_handler(message, get_code, name, price)
    except:
        bot.reply_to(message, "❌ Number daalo bhai! Dobara /add karo.")

def get_code(message, name, price):
    code = message.text.strip()
    c.execute("INSERT INTO products (name, price, code, available) VALUES (?, ?, ?, 1)", (name, price, code))
    conn.commit()
    bot.reply_to(message, f"✅ Shein Coupon Added!\n{name}\nPrice: ₹{price}\nCode: {code[:10]}...")

@bot.message_handler(commands=['products'])
def show_products(message):
    c.execute("SELECT id, name, price FROM products WHERE available = 1")
    rows = c.fetchall()
    if not rows:
        bot.reply_to(message, "😔 Abhi koi Shein coupon available nahi. Admin ko batao!")
        return
    
    markup = InlineKeyboardMarkup(row_width=1)
    for row in rows:
        btn = InlineKeyboardButton(f"🛒 {row[1]} - ₹{row[2]}", callback_data=f"buy_{row[0]}")
        markup.add(btn)
    bot.send_message(message.chat.id, "🔥 **Available Shein Coupons** 🔥\n\nChoose karo aur pay karo!", reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def buy_product(call):
    product_id = int(call.data.split('_')[1])
    c.execute("SELECT name, price FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    if not product:
        bot.answer_callback_query(call.id, "❌ Coupon nahi mila!")
        return

    bot.answer_callback_query(call.id)
    caption = f"💸 **{product[0]}** ke liye ₹{product[1]} pay karo is QR pe!\n\nUTR ke baad screenshot bhejo for instant code. ⏱️"
    bot.send_photo(call.message.chat.id, QR_PHOTO, caption=caption, parse_mode='Markdown')
    
    bot.send_message(call.message.chat.id, "📝 UTR bhejo (12 digit number):")
    threading.Timer(1.0, lambda: bot.register_next_step_handler_by_chat_id(call.message.chat.id, process_utr, product_id, call.from_user.id)).start()

def process_utr(message, product_id, buyer_id):
    utr = message.text.strip()
    if len(utr) != 12 or not utr.isdigit():
        bot.reply_to(message, "❌ Invalid UTR! 12 digits daalo. Dobara try karo.")
        return
    
    bot.reply_to(message, "✅ UTR saved! Ab **payment screenshot bhejo** (UPI app se, amount + date clear ho). Bot 5 sec me verify karega! 📸")
    bot.register_next_step_handler(message, process_screenshot, product_id, buyer_id, utr)

def process_screenshot(message, product_id, buyer_id, utr):
    if not message.photo:
        bot.reply_to(message, "❌ Photo bhejo! Text nahi chalega. /products se dobara start karo.")
        return
    
    screenshot_id = message.photo[-1].file_id
    c.execute("INSERT INTO pending (user_id, product_id, utr, screenshot_id) VALUES (?, ?, ?, ?)", (buyer_id, product_id, utr, screenshot_id))
    conn.commit()
    
    try:
        file_info = bot.get_file(screenshot_id)
        downloaded_file = bot.download_file(file_info.file_path)
        image = Image.open(io.BytesIO(downloaded_file))
        text = pytesseract.image_to_string(image).lower()
        
        # Amount extract (₹500 ya 500.00 etc)
        amount_match = re.search(r'₹?(\d+(?:\.\d{2})?)', text)
        extracted_amount = float(amount_match.group(1)) if amount_match else 0
        
        c.execute("SELECT price, code, name FROM products WHERE id = ?", (product_id,))
        result = c.fetchone()
        expected_amount, code, name = result
        
        if abs(extracted_amount - expected_amount) <= 1:  # Tolerance for .00
            # Success! Code bhejo
            bot.send_message(buyer_id, f"✅ **Payment Verified Automatically!** 🎉\n\n**{name}**\n\n**Your Code:** `{code}`\n\nRedeem on Shein app/site. Enjoy shopping! ❤️\n\nShare bot: @SheinCouponShopbot", parse_mode='Markdown')
            
            # Admin notify
            try:
                user = bot.get_chat(buyer_id)
                username = f"@{user.username}" if user.username else f"ID: {buyer_id}"
            except:
                username = f"ID: {buyer_id}"
            bot.send_message(ADMIN_ID, f"🔔 **SALE!** {username}\nProduct: {name}\nUTR: {utr}\nAmount: ₹{extracted_amount}")
            
            c.execute("DELETE FROM pending WHERE user_id=? AND product_id=?", (buyer_id, product_id))
            conn.commit()
        else:
            bot.reply_to(message, f"❌ **Amount Mismatch!** Bot ne ₹{extracted_amount} padha, expected ₹{expected_amount}. Clear screenshot bhejo ya admin ping karo.")
            bot.send_message(ADMIN_ID, f"⚠️ **Verification Failed**\nUser: {buyer_id}\nUTR: {utr}\nExtracted: ₹{extracted_amount} (Expected: ₹{expected_amount})")
    
    except Exception as e:
        bot.reply_to(message, "❌ **Error in Verification!** Clear photo bhejo. Ya /start se try karo.")
        bot.send_message(ADMIN_ID, f"❌ **OCR Error** User: {buyer_id} | Error: {str(e)}")

# Mass Add for Bulk Shein Codes (Admin only)
@bot.message_handler(commands=['massadd'])
def mass_add(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.reply_to(message, "📁 Bulk add: codes.txt file bhejo (format: Amount|Code\nej: 500|SG1234567890)")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if message.from_user.id != ADMIN_ID:
        return
    if message.reply_to_message and 'bulk add' in message.reply_to_message.text.lower():
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            lines = downloaded_file.decode('utf-8').splitlines()
            added = 0
            for line in lines:
                if '|' in line:
                    amount, code = line.split('|', 1)
                    try:
                        amount = int(amount.strip())
                        name = f"Shein ₹{amount} Gift Card"
                        price = amount
                        c.execute("INSERT INTO products (name, price, code, available) VALUES (?, ?, ?, 1)", (name, price, code.strip()))
                        added += 1
                    except:
                        pass
            conn.commit()
            bot.reply_to(message, f"✅ **{added} Shein Coupons Added!** Bulk list dekho /products me.")
        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")

# Bot chalao
print("Shein Bot Started... @SheinCouponShopbot Live! 🔥")
bot.infinity_polling()
