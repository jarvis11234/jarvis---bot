import os
import sqlite3
import threading
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
OWNER_ID = 8298044480  # Hardcoded Owner ID (Gaurav)
DB_FILE = "jarvis_bot.db"

# Flask & Groq Initialization
app = Flask(__name__)
groq_client = Groq(api_key=GROQ_API_KEY)

# New Active Groq Models (2026 Active List)
PRIMARY_MODEL = "openai/gpt-oss-20b"
SMART_MODEL = "openai/gpt-oss-120b"
BACKUP_MODEL = "qwen/qwen3.6-27b"

# ----------------------------------------------------
# DATABASE FUNCTIONS
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
            (user_id, "Owner", "Gaurav Singh", is_vip)
        )
    conn.commit()
    conn.close()

def check_user_limit(user_id, username, first_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_vip, msg_count, last_reset FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    user_is_vip = 1 if user_id == OWNER_ID else 0

    if not row:
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, is_vip, msg_count, last_reset) VALUES (?, ?, ?, ?, 1, CURRENT_DATE)",
            (user_id, username, first_name, user_is_vip)
        )
        conn.commit()
        conn.close()
        return True, 1, user_is_vip

    is_vip, msg_count, last_reset = row

    if user_id == OWNER_ID and is_vip == 0:
        is_vip = 1
        cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (user_id,))
        conn.commit()

    if is_vip == 1:
        cursor.execute("UPDATE users SET username=?, first_name=?, last_seen=CURRENT_TIMESTAMP WHERE user_id=?", (username, first_name, user_id))
        conn.commit()
        conn.close()
        return True, msg_count, is_vip

    cursor.execute("SELECT CURRENT_DATE")
    today = cursor.fetchone()[0]

    if str(last_reset) != str(today):
        msg_count = 0
        cursor.execute("UPDATE users SET msg_count = 0, last_reset = CURRENT_DATE WHERE user_id = ?", (user_id,))

    if msg_count >= 10:
        conn.close()
        return False, msg_count, is_vip

    cursor.execute(
        "UPDATE users SET msg_count = msg_count + 1, username=?, first_name=?, last_seen=CURRENT_TIMESTAMP WHERE user_id = ?",
        (username, first_name, user_id)
    )
    conn.commit()
    conn.close()
    return True, msg_count + 1, is_vip

# ----------------------------------------------------
# FLASK WEB SERVER & MINI APP
# ----------------------------------------------------
@app.route('/')
def home():
    return "Jarvis AI Web Server is Running!"

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
            body {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                margin: 0;
                padding: 20px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 90vh;
            }
            .card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 16px;
                padding: 24px;
                width: 100%;
                max-width: 350px;
                box-shadow: 0 10px 25px rgba(0,0,0,0.5);
                text-align: center;
            }
            .avatar {
                width: 80px;
                height: 80px;
                border-radius: 50%;
                background: linear-gradient(135deg, #38bdf8, #8b5cf6);
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 16px auto;
                font-size: 32px;
            }
            h2 { margin: 0 0 8px 0; color: #38bdf8; }
            p { color: #94a3b8; font-size: 14px; margin-bottom: 20px; line-height: 1.4; }
            .badge {
                background: #0284c7;
                color: #fff;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: bold;
            }
            .price { font-size: 28px; font-weight: bold; margin: 16px 0; color: #f59e0b; }
            .btn {
                background: #f59e0b;
                color: #0f172a;
                border: none;
                padding: 14px 20px;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
                width: 100%;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="avatar">🚀</div>
            <h2>Jarvis AI Assistant</h2>
            <span class="badge">Daily Limit: 10 Messages</span>
            <p style="margin-top: 12px;">Get unlimited instant access, code generation, and priority AI responses by upgrading to VIP.</p>
            <div class="price">⭐ 50 Stars</div>
            <button class="btn" onclick="buyVip()">Upgrade to VIP</button>
        </div>

        <script>
            const tg = window.Telegram.WebApp;
            function buyVip() {
                tg.sendData("/buyvip");
                tg.close();
            }
        </script>
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
        f"Main **Jarvis AI Assistant** hu, developed and owned by **Gaurav** Sir.\n"
        f"💡 Aap mujhse koi bhi sawal, coding, ya task pooch sakte hain.\n\n"
        f"📊 **Free Limit**: 10 Messages/Day\n"
        f"⭐ **VIP Pass**: Unlimited Access for 50 Telegram Stars!"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("⛔ Sirf Owner (Gaurav Sir) hi is command ko use kar sakte hain.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, is_vip, msg_count FROM users")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Abhi tak koi user DB me registered nahi hai.")
        return

    msg = "📊 **Registered Users List:**\n\n"
    for r in rows:
        uid, uname, fname, is_vip, count = r
        status = "⭐ [VIP]" if (is_vip == 1 or uid == OWNER_ID) else f"Free ({count}/10 msgs)"
        msg += f"• **{fname}** (@{uname or 'N/A'}) - `{uid}` | {status}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def buyvip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_invoice(
        chat_id=chat_id,
        title="Jarvis AI VIP Upgrade",
        description="Lifetime Unlimited Access to Jarvis AI Assistant",
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    if text == "/buyvip":
        await buyvip_command(update, context)
        return

    allowed, count, is_vip = check_user_limit(user.id, user.username, user.first_name)

    if not allowed:
        await update.message.reply_text(
            "⚠️ **Daily Limit Reached, Sir!**\n\n"
            "Aapki aaj ki 10 free messages ki limit khatam ho chuki hai.\n"
            "Unlimited access ke liye **Open Jarvis 🚀** menu se VIP Pass upgrade karein!",
            parse_mode="Markdown"
        )
        return

    # Strict Identity + High-Tech Loyal Jarvis System Prompt
    jarvis_identity_prompt = (
        "You are Jarvis, a highly intelligent, loyal, and classy AI assistant inspired by Iron Man's AI. "
        "Your creator, developer, and owner is Gaurav (Telegram ID: 8298044480). "
        "If anyone asks who created, built, or owns you, ALWAYS answer proudly that Gaurav is your creator and owner. "
        "NEVER say you were made by OpenAI, Meta, or any other team. "
        "ALWAYS address the user respectfully as 'Sir' or 'Boss'. "
        "ALWAYS reply strictly in natural Hinglish (Hindi written using English/Roman script mixed with English technical terms). "
        "Keep your tone extremely polite, witty, loyal, and classy (e.g., 'At your service, Sir!')."
    )

    models_to_try = [PRIMARY_MODEL, SMART_MODEL, BACKUP_MODEL]
    reply = None
    last_err = ""

    for m in models_to_try:
        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": jarvis_identity_prompt},
                    {"role": "user", "content": text}
                ],
                model=m
            )
            reply = chat_completion.choices[0].message.content
            if reply:
                break
        except Exception as e:
            last_err = str(e)
            continue

    if reply:
        await update.message.reply_text(reply)
    else:
        await update.message.reply_text(f"⚠️ Groq API Error: {last_err}")

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

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("buyvip", buyvip_command))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    application.run_polling()

if __name__ == "__main__":
    main()
            
