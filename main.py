import os
import time
import sqlite3
import threading
import urllib.request
import base64
import re
from flask import Flask, render_template_string
from groq import Groq
import google.generativeai as genai
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OWNER_ID = 8298044480  # Backend Only Owner ID (Gaurav)
DB_FILE = "jarvis_bot.db"

RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "https://jarvis--bot.onrender.com")

app = Flask(__name__)

# Clients Setup
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Init Warning: {e}")

# Groq Active Text Models Stack
PRIMARY_MODEL = "openai/gpt-oss-20b"
SMART_MODEL = "openai/gpt-oss-120b"
BACKUP_MODEL = "qwen/qwen3.6-27b"

# Group Chat Memory
CHAT_MEMORY = {}

# ----------------------------------------------------
# CLEAN FORMATTING CONVERTER FOR TELEGRAM
# ----------------------------------------------------
def clean_latex_formatting(text: str) -> str:
    if not text:
        return ""
    
    # Math symbols & LaTeX Cleanup
    text = re.sub(r'\\times', '×', text)
    text = re.sub(r'\\div', '÷', text)
    text = re.sub(r'\\approx', '≈', text)
    text = re.sub(r'\\pm', '±', text)
    text = re.sub(r'\\gamma', 'γ', text)
    text = re.sub(r'\\alpha', 'α', text)
    text = re.sub(r'\\beta', 'β', text)
    text = re.sub(r'\\theta', 'θ', text)
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\msg_count\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1 / \2)', text)
    
    # Powers/Superscripts (10^{23} -> 10²³)
    superscript_map = {'0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', '+': '⁺', '-': '⁻'}
    def replace_power(match):
        power_str = match.group(1)
        return "".join(superscript_map.get(char, char) for char in power_str)

    text = re.sub(r'\^{?([0-9+-]+)}?', replace_power, text)

    # Clean Headers (### Header -> *Header*)
    text = re.sub(r'###\s*(.*)', r'*\1*', text)
    text = re.sub(r'##\s*(.*)', r'*\1*', text)
    text = re.sub(r'#\s*(.*)', r'*\1*', text)

    # Bullet points formatting (🔹)
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('* ') or stripped.startswith('- '):
            cleaned_lines.append("🔹 " + stripped[2:])
        else:
            cleaned_lines.append(line)
            
    return "\n".join(cleaned_lines).strip()

# ----------------------------------------------------
# HELPER: TELEGRAM LONG MESSAGE SPLITTER (WITH MARKDOWN)
# ----------------------------------------------------
async def send_large_message(update: Update, text: str):
    clean_text = clean_latex_formatting(text)
    max_length = 4000
    
    if len(clean_text) <= max_length:
        try:
            await update.message.reply_text(clean_text, parse_mode='Markdown')
        except Exception:
            await update.message.reply_text(clean_text)
        return

    for i in range(0, len(clean_text), max_length):
        chunk = clean_text[i:i + max_length]
        try:
            await update.message.reply_text(chunk, parse_mode='Markdown')
        except Exception:
            await update.message.reply_text(chunk)

# ----------------------------------------------------
# SELF-PING AUTO KEEP ALIVE
# ----------------------------------------------------
def keep_alive():
    time.sleep(30)
    while True:
        try:
            req = urllib.request.Request(
                RENDER_APP_URL, 
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
        time.sleep(300)

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
            (user_id, "Owner", "Gaurav", is_vip)
        )
    conn.commit()
    conn.close()

def check_user_limit(user_id, username, first_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
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

    if is_owner:
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
    return "Jarvis v2.0 AI Engine Active!"

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
            <h2>Jarvis AI Assistant v2.0</h2>
            <span class="badge">Daily Limit: 10 Messages</span>
            <p style="margin-top:10px;">Upgrade to VIP for unlimited access, Vision Doubt Solving & Deep Reasoning Mode.</p>
            <div style="font-size: 24px; color: #f59e0b; margin: 15px 0;">⭐ 50 Stars</div>
            <button class="btn" onclick="Telegram.WebApp.sendData('/buyvip'); Telegram.WebApp.close();">Upgrade to VIP</button>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_code)

# ----------------------------------------------------
# BOT COMMANDS
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    check_user_limit(user.id, user.username, user.first_name)
    welcome_msg = (
        f"🤖 *Jarvis v2.0 AI Engine Active!*\n\n"
        f"At your service, Sir! Developed and owned by *Gaurav* Sir.\n\n"
        f"⚡ *Features Loaded:*\n"
        f"🔹 Image Doubt Solver (Send Photo)\n"
        f"🔹 `/think <question>` (Deep Reasoning Mode)\n"
        f"🔹 `/web <link>` (Web Link Summarizer)\n"
        f"🔹 Group Chat Context Memory\n\n"
        f"📊 *Free Limit*: 10 Messages/Day\n"
        f"⭐ *VIP Pass*: Unlimited Access for 50 Stars!"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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

        msg = "📊 *Registered Users List (Gaurav Sir Access Only):*\n\n"
        for r in rows:
            uid, uname, fname, is_vip, count = r
            status = "⭐ [VIP/Owner]" if (is_vip == 1 or int(uid) == int(OWNER_ID)) else f"Free ({count}/10 msgs)"
            msg += f"🔹 *{fname}* (@{uname or 'N/A'}) - `{uid}` | {status}\n"

        await send_large_message(update, msg)
    except Exception as e:
        await update.message.reply_text(f"⚠️ DB Fetch Error: {e}")

async def think_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    allowed, count, is_vip = check_user_limit(user.id, user.username, user.first_name)
    if not allowed:
        await update.message.reply_text("⚠️ Daily Limit Reached, Sir! Upgrade to VIP.")
        return

    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("💡 Usage: `/think How does quantum computing work?`", parse_mode="Markdown")
        return

    thinking_msg = await update.message.reply_text("🧠 *Analyzing with Deep Logic, Sir...*", parse_mode="Markdown")
    
    prompt = f"Provide a step-by-step deep logical explanation with detailed reasoning for: {query}"
    try:
        completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Jarvis Deep Reasoner. Structure output using clean bold key terms, paragraphs, and bullet points (🔹)."},
                {"role": "user", "content": prompt}
            ],
            model=SMART_MODEL
        )
        reply = completion.choices[0].message.content
        await thinking_msg.delete()
        await send_large_message(update, reply)
    except Exception as e:
        await thinking_msg.edit_text(f"⚠️ Reasoning Error: {e}")

async def web_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    allowed, count, is_vip = check_user_limit(user.id, user.username, user.first_name)
    if not allowed:
        await update.message.reply_text("⚠️ Daily Limit Reached, Sir!")
        return

    if not context.args:
        await update.message.reply_text("💡 Usage: `/web https://example.com`", parse_mode="Markdown")
        return

    url = context.args[0]
    status_msg = await update.message.reply_text("🌐 *Fetching & Summarizing Web Content...*", parse_mode="Markdown")

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html_data = urllib.request.urlopen(req, timeout=10).read().decode('utf-8', errors='ignore')
        clean_text = re.sub('<[^<]+?>', '', html_data)[:3000]

        completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Jarvis. Summarize this web content into key insights using bold terms and clean bullet points (🔹)."},
                {"role": "user", "content": clean_text}
            ],
            model=PRIMARY_MODEL
        )
        summary = completion.choices[0].message.content
        await status_msg.delete()
        await send_large_message(update, f"📖 *Web Summary for:* `{url}`\n\n{summary}")
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Failed to read web link: {e}")

async def buyvip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_invoice(
        chat_id=chat_id,
        title="Jarvis AI VIP Upgrade",
        description="Lifetime Unlimited Access, Vision & Reasoning Features",
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
    await update.message.reply_text("🎉 *Payment Successful!* VIP status active ho chuka hai, Sir!", parse_mode="Markdown")

def save_chat_memory(chat_id, user_name, text):
    if chat_id not in CHAT_MEMORY:
        CHAT_MEMORY[chat_id] = []
    CHAT_MEMORY[chat_id].append(f"{user_name}: {text}")
    if len(CHAT_MEMORY[chat_id]) > 15:
        CHAT_MEMORY[chat_id].pop(0)

# ----------------------------------------------------
# VISION SOLVER ENGINE
# ----------------------------------------------------
def process_vision_query(image_bytes, user_text):
    prompt = user_text or "Solve this question or explain this image step-by-step in detail in natural Hinglish, Sir."

    if GEMINI_API_KEY:
        gemini_candidates = [
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "models/gemini-1.5-flash",
            "models/gemini-2.0-flash"
        ]
        
        try:
            discovered = [
                m.name for m in genai.list_models() 
                if 'generateContent' in m.supported_generation_methods
            ]
            gemini_candidates = discovered + gemini_candidates
        except Exception:
            pass

        image_data = [{"mime_type": "image/jpeg", "data": bytes(image_bytes)}]

        for m_name in gemini_candidates:
            try:
                g_model = genai.GenerativeModel(m_name)
                res = g_model.generate_content([prompt, image_data[0]])
                if res and res.text:
                    return res.text
            except Exception:
                continue

    if groq_client:
        groq_vision_candidates = [
            "llama-3.2-11b-vision-preview",
            "llama-3.2-90b-vision-preview"
        ]
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        for gv_model in groq_vision_candidates:
            try:
                completion = groq_client.chat.completions.create(
                    model=gv_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                            ]
                        }
                    ]
                )
                if completion.choices[0].message.content:
                    return completion.choices[0].message.content
            except Exception:
                continue

    return "⚠️ System abhi image read nahi kar pa raha hai, Sir. Kripya image ki clarity check karke dobara bhejein."

# ----------------------------------------------------
# MESSAGE ROUTER
# ----------------------------------------------------
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
            "⚠️ *Daily Limit Reached, Sir!* Upgrade to VIP 🚀",
            parse_mode="Markdown"
        )
        return

    jarvis_system_prompt = (
        "You are Jarvis v2.0, a highly intelligent and respectful AI assistant owned by Gaurav Sir. "
        "Always structure your output neatly using bold text for key terms, clean bullet points (🔹), "
        "and clear paragraph breaks. Address the user politely as Sir or Boss."
    )

    context_str = "\n".join(CHAT_MEMORY.get(chat_id, []))
    full_user_prompt = f"Recent Chat Memory:\n{context_str}\n\nCurrent Input: {text}"

    # Handle Photo Doubts
    if photo:
        status_msg = await update.message.reply_text("📸 *Solving Question, Sir...*", parse_mode="Markdown")
        try:
            tg_file = await context.bot.get_file(photo[-1].file_id)
            image_bytes = await tg_file.download_as_bytearray()
            
            solution = process_vision_query(image_bytes, text)
            await status_msg.delete()
            await send_large_message(update, solution)
            return
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Image Download Error: {e}")
            return

    # Handle Text Input
    reply = None
    if text:
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
        await send_large_message(update, reply)
    else:
        await update.message.reply_text("⚠️ System response generate nahi kar pa raha hai, Sir.")

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
    application.add_handler(CommandHandler("think", think_command))
    application.add_handler(CommandHandler("web", web_command))
    application.add_handler(CommandHandler("buyvip", buyvip_command))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # Corrected filter handling with exact closed parentheses
    message_filter = (filters.TEXT | filters.PHOTO) & (~filters.COMMAND)
    application.add_handler(MessageHandler(message_filter, handle_message))

    application.run_polling()

if __name__ == "__main__":
    # ----------------------------------------------------
# MAIN EXECUTION (FIXED FOR DEPLOYMENT)
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
    application.add_handler(CommandHandler("think", think_command))
    application.add_handler(CommandHandler("web", web_command))
    application.add_handler(CommandHandler("buyvip", buyvip_command))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    
    # SUCCESSFUL PAYMENT HANDLER FIX
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # MESSAGE HANDLER FIX
    message_filter = (filters.TEXT | filters.PHOTO) & (~filters.COMMAND)
    application.add_handler(MessageHandler(message_filter, handle_message))

    application.run_polling()

if __name__ == "__main__":
    # ----------------------------------------------------
# MAIN EXECUTION (FIXED FOR DEPLOYMENT)
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
    application.add_handler(CommandHandler("think", think_command))
    application.add_handler(CommandHandler("web", web_command))
    application.add_handler(CommandHandler("buyvip", buyvip_command))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    
    # SUCCESSFUL PAYMENT HANDLER FIX
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # MESSAGE HANDLER FIX
    message_filter = (filters.TEXT | filters.PHOTO) & (~filters.COMMAND)
    application.add_handler(MessageHandler(message_filter, handle_message))

    application.run_polling()

if __name__ == "__main__":
    main()

            
            
