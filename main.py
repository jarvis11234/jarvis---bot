import os
import time
import sqlite3
import threading
import urllib.request
from flask import Flask, render_template_string
from groq import Groq
from telegram import Update, LabeledPrice
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    PreCheckoutQueryHandler,
    filters
)

# ----------------------------------------------------
# CONFIGURATION & CONSTANTS
# ----------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OWNER_ID = 8298044480  # Hardcoded Numerical Owner ID
DB_FILE = "jarvis_bot.db"

RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "https://jarvis--bot.onrender.com")

app = Flask(__name__)
groq_client = Groq(api_key=GROQ_API_KEY)

PRIMARY_MODEL = "openai/gpt-oss-20b"
SMART_MODEL = "openai/gpt-oss-120b"
BACKUP_MODEL = "qwen/qwen3.6-27b"
VISION_MODEL = "llama-3.2-11b-vision-preview"

# Group Chat Context Memory
CHAT_MEMORY = {}

# ----------------------------------------------------
# SELF-PING AUTO KEEP ALIVE
# ----------------------------------------------------
def keep_alive():
    time.sleep(30)
    while True:
        try:
            req = urllib.request.Request(
                RENDER_APP_URL, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
        time.sleep(300)

# ----------------------------------------------------
# DATABASE FUNCTIONS (ID-Based Verification)
# ----------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_vip INTEGER DEFAULT 0,
            msg_count INTEGER DEFAULT 0,
            last_reset DATE DEFAULT CURRENT_DATE,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def set_vip_status(user_id, is_vip=1):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE users SET is_vip = ? WHERE user_id = ?", (is_vip, user_id))
    else:
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, is_vip, last_seen) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (user_id, "Owner", "Gaurav", is_vip)
        )
    conn.commit()
    conn.close()

def check_user_limit(user_id, username, first_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Strictly Check Numerical ID for Owner
    is_owner = (int(user_id) == int(OWNER_ID))
    user_is_vip = 1 if is_owner else 0

    cursor.execute("SELECT is_vip, msg_count, last_reset FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if not row:
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, is_vip, msg_count, last_reset) VALUES (?, ?, ?, ?, 1, CURRENT_DATE)",
            (user_id, username or "N/A", first_name or "User", user_is_vip)
        )
        conn.commit()
        conn.close()
        return True, 1, user_is_vip

    is_vip, msg_count, last_reset = row

    # Dynamic profile sync & VIP verification for Owner
    if is_owner:
        is_vip = 1
        cursor.execute(
            "UPDATE users SET is_vip = 1, username = ?, first_name = ?, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?",
            (username or "N/A", first_name or "Gaurav", user_id)
        )
        conn.commit()
        conn.close()
        return True, msg_count, 1

    if is_vip == 1:
        cursor.execute(
            "UPDATE users SET username = ?, first_name = ?, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?",
            (username or "N/A", first_name or "User", user_id)
        )
        conn.commit()
        conn.close()
        return True, msg_count, 1

    cursor.execute("SELECT CURRENT_DATE")
    today = cursor.fetchone()[0]

    if str(last_reset) != str(today):
        msg_count = 0
        cursor.execute("UPDATE users SET msg_count = 0, last_reset = CURRENT_DATE WHERE user_id = ?", (user_id,))

    if msg_count >= 10:
        conn.close()
        return False, msg_count, is_vip

    cursor.execute(
        "UPDATE users SET msg_count = msg_count + 1, username = ?, first_name = ?, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?",
        (username or "N/A", first_name or "User", user_id)
    )
    conn.commit()
    conn.close()
    return True, msg_count + 1, is_vip

# ----------------------------------------------------
# FLASK WEB SERVER
# ----------------------------------------------------
@app.route('/')
def home():
    return "Jarvis AI Web Server is Alive & Running!"

@app.route('/miniapp')
def mini_app():
    html_code = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Jarvis AI VIP</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body { background-color: #0f172a; color: #f8fafc; font-family: sans-serif; padding: 20px; display: flex; justify-content: center; }
            .card { background-color: #1e293b; border-radius: 16px; padding: 24px; text-align: center; max-width: 350px; }
            .badge { background: #0284c7; padding: 4px 12px; border-radius: 20px; font-size: 12px; }
            .btn { background: #f59e0b; color: #0f172a; border: none; padding: 14px; border-radius: 10px; width: 100%; font-weight: bold; cursor: pointer; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>Jarvis AI Assistant</h2>
            <span class="badge">Daily Limit: 10 Messages</span>
            <p style="margin-top:10px;">Upgrade to VIP for unlimited access and image doubt solving.</p>
            <div style="font-size: 24px; color: #f59e0b; margin: 15px 0;">⭐ 50 Stars</div>
            <button class="btn" onclick="Telegram.WebApp.sendData('/buyvip'); Telegram.WebApp.close();">Upgrade to VIP</button>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_code)

# ----------------------------------------------------
# BOT COMMANDS & HANDLERS
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    check_user_limit(user.id, user.username, user.first_name)
    welcome_msg = (
        f"🤖 **At your service, Sir!**\n\n"
        f"Main **Jarvis AI Assistant** hu, created and owned by **Gaurav** Sir.\n"
        f"💡 Main Text + Photo Doubts aur Group Chat memory support karta hu.\n\n"
        f"📊 **Free Limit**: 10 Messages/Day\n"
        f"⭐ **VIP Pass**: Unlimited Access for 50 Telegram Stars!"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Explicit Numerical Verification for Owner ID
    if int(user_id) != int(OWNER_ID):
        await update.message.reply_text("⛔ Access Denied! Sirf Owner (Gaurav Sir) hi is command ko run kar sakte hain.")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, first_name, is_vip, msg_count FROM users")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text("Database me abhi koi user saved nahi hai, Sir.")
            return

        msg = "📊 **Registered Users List (Gaurav Sir Access Only):**\n\n"
        for r in rows:
            uid, uname, fname, is_vip, count = r
            status = "⭐ [VIP/Owner]" if (is_vip == 1 or int(uid) == int(OWNER_ID)) else f"Free ({count}/10 msgs)"
            msg += f"• **{fname}** (@{uname or 'N/A'}) - `{uid}` | {status}\n"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ DB Fetch Error: {e}")

async def buyvip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_invoice(
        chat_id=chat_id,
        title="Jarvis AI VIP Upgrade",
        description="Lifetime Unlimited Access & Vision Doubt Solving",
        payload="jarvis_vip_pass",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice("VIP Access", 50)]
    )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload != "jarvis_vip_pass":
        await query.answer(ok=False, error_message="Payment validation failed.")
    else:
        await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    set_vip_status(user_id, is_vip=1)
    await update.message.reply_text("🎉 **Payment Successful!** Aapka VIP status active ho chuka hai, Sir!")

def save_chat_memory(chat_id, user_name, text):
    if chat_id not in CHAT_MEMORY:
        CHAT_MEMORY[chat_id] = []
    CHAT_MEMORY[chat_id].append(f"{user_name}: {text}")
    if len(CHAT_MEMORY[chat_id]) > 10:
        CHAT_MEMORY[chat_id].pop(0)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    text = update.message.text or update.message.caption or ""
    photo = update.message.photo

    if text == "/buyvip":
        await buyvip_command(update, context)
        return

    save_chat_memory(chat_id, user.first_name, text or "[Sent Photo]")

    chat_type = update.effective_chat.type
    bot_username = context.bot.username.lower() if context.bot.username else ""
    user_msg_lower = text.lower()

    if chat_type in ["group", "supergroup"]:
        is_mentioned = f"@{bot_username}" in user_msg_lower
        has_jarvis = "jarvis" in user_msg_lower
        is_reply_to_bot = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
        
        if not (is_mentioned or has_jarvis or is_reply_to_bot or photo):
            return

    allowed, count, is_vip = check_user_limit(user.id, user.username, user.first_name)

    if not allowed:
        await update.message.reply_text(
            "⚠️ **Daily Limit Reached, Sir!**\n\n"
            "Aaj ki 10 free limit complete ho chuki hai. VIP Pass upgrade karein 🚀",
            parse_mode="Markdown"
        )
        return

    jarvis_system_prompt = (
        "You are Jarvis, a highly intelligent, loyal, and classy AI assistant created by Gaurav (Telegram ID: 8298044480). "
        "ALWAYS address the user respectfully as 'Sir' or 'Boss' in natural Hinglish. "
        "Use group memory context provided to clear doubts accurately."
    )

    context_str = "\n".join(CHAT_MEMORY.get(chat_id, []))
    full_user_prompt = f"Recent Chat Memory:\n{context_str}\n\nCurrent Input: {text}"

    reply = None

    if photo:
        try:
            file = await context.bot.get_file(photo[-1].file_id)
            file_url = file.file_path

            completion = groq_client.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {"role": "system", "content": jarvis_system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": full_user_prompt or "Solve this image doubt, Sir."},
                            {"type": "image_url", "image_url": {"url": file_url}}
                        ]
                    }
                ]
            )
            reply = completion.choices[0].message.content
        except Exception as e:
            reply = f"⚠️ Image doubt processing error: {e}"

    if not reply and text:
        models_to_try = [PRIMARY_MODEL, SMART_MODEL, BACKUP_MODEL]
        for m in models_to_try:
            try:
                chat_completion = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": jarvis_system_prompt},
                        {"role": "user", "content": full_user_prompt}
                    ],
                    model=m
                )
                reply = chat_completion.choices[0].message.content
                if reply:
                    break
            except Exception:
                continue

    if reply:
        await update.message.reply_text(reply)
    else:
        await update.message.reply_text("⚠️ System issue, Sir. Request complete nahi ho sakti.")

# ----------------------------------------------------
# MAIN EXECUTION
# ----------------------------------------------------
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def main():
    init_db()
    set_vip_status(OWNER_ID, is_vip=1)

    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("buyvip", buyvip_command))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & (~filters.COMMAND), handle_message))

    application.run_polling()

if __name__ == "__main__":
    main()
