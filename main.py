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
OWNER_ID = 8298044480  # Gaurav Sir ID
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

PRIMARY_MODEL = "openai/gpt-oss-20b"
SMART_MODEL = "openai/gpt-oss-120b"
BACKUP_MODEL = "qwen/qwen3.6-27b"

CHAT_MEMORY = {}

# ----------------------------------------------------
# CLEAN FORMATTING CONVERTER (No extra stars, Clean Bullets)
# ----------------------------------------------------
def clean_latex_formatting(text: str) -> str:
    if not text:
        return ""
    
    # 1. LaTeX Math Cleanup
    text = re.sub(r'\\times', '×', text)
    text = re.sub(r'\\div', '÷', text)
    text = re.sub(r'\\approx', '≈', text)
    text = re.sub(r'\\pm', '±', text)
    text = re.sub(r'\\gamma', 'γ', text)
    text = re.sub(r'\\alpha', 'α', text)
    text = re.sub(r'\\beta', 'β', text)
    text = re.sub(r'\\theta', 'θ', text)
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\mathbf\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1 / \2)', text)
    
    # Powers/Superscripts (10^{23} -> 10²³)
    superscript_map = {'0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', '+': '⁺', '-': '⁻'}
    def replace_power(match):
        power_str = match.group(1)
        return "".join(superscript_map.get(char, char) for char in power_str)

    text = re.sub(r'\^{?([0-9+-]+)}?', replace_power, text)
    
    # 2. Remove raw markdown headers and excess bold stars
    text = re.sub(r'###\s*', '', text)
    text = re.sub(r'##\s*', '', text)
    text = text.replace('**', '')  # Extra stars hatane ke liye
    text = text.replace('$$', '\n').replace('$', '')

    # 3. Standardize Bullet Points to simple '•'
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('* ') or stripped.startswith('- '):
            cleaned_lines.append("• " + stripped[2:])
        else:
            cleaned_lines.append(line)
            
    return "\n".join(cleaned_lines).strip()

# ----------------------------------------------------
# HELPER: TELEGRAM LONG MESSAGE SPLITTER
# ----------------------------------------------------
async def send_large_message(update: Update, text: str):
    clean_text = clean_latex_formatting(text)
    max_length = 4000
    
    if len(clean_text) <= max_length:
        await update.message.reply_text(clean_text)
        return

    for i in range(0, len(clean_text), max_length):
        chunk = clean_text[i:i + max_length]
        await update.message.reply_text(chunk)

# ----------------------------------------------------
# KEEP ALIVE & DB FUNCTIONS
# ----------------------------------------------------
def keep_alive():
    time.sleep(30)
    while True:
        try:
            req = urllib.request.Request(RENDER_APP_URL, headers={'User-Agent': 'Mozilla/5.0'})
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
        time.sleep(300)

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
    if cursor.fetchone():
        cursor.execute("UPDATE users SET is_vip = ? WHERE user_id = ?", (is_vip, user_id))
    else:
        cursor.execute("INSERT INTO users (user_id, username, first_name, is_vip) VALUES (?, 'Owner', 'Gaurav', ?)", (user_id, is_vip))
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
        cursor.execute("INSERT INTO users (user_id, username, first_name, is_vip, msg_count, last_reset) VALUES (?, ?, ?, ?, 1, CURRENT_DATE)",
                       (user_id, username or "N/A", first_name or "User", user_is_vip))
        conn.commit()
        conn.close()
        return True, 1, user_is_vip

    is_vip, msg_count, last_reset = row

    if is_owner or is_vip == 1:
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

    cursor.execute("UPDATE users SET msg_count = msg_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True, msg_count + 1, is_vip

# ----------------------------------------------------
# FLASK WEB SERVER
# ----------------------------------------------------
@app.route('/')
def home():
    return "Jarvis AI Active!"

# ----------------------------------------------------
# BOT COMMANDS
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    check_user_limit(user.id, user.username, user.first_name)
    welcome_msg = (
        "Jarvis AI Engine Active!\n\n"
        "At your service, Sir! Developed by Gaurav Sir.\n\n"
        "• Send photo for doubt solving\n"
        "• /think <question> for step-by-step logic\n"
        "• /web <link> for website summary"
    )
    await update.message.reply_text(welcome_msg)

async def think_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    allowed, count, is_vip = check_user_limit(user.id, user.username, user.first_name)
    if not allowed:
        await update.message.reply_text("Daily limit reached, Sir! Upgrade to VIP.")
        return

    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: /think <your question>")
        return

    status_msg = await update.message.reply_text("Thinking...")
    
    try:
        completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Jarvis AI. Give direct solutions using clean bullet points (•). Do NOT include solution plans, thinking process, or stars (**) for bolding."},
                {"role": "user", "content": query}
            ],
            model=SMART_MODEL
        )
        reply = completion.choices[0].message.content
        await status_msg.delete()
        await send_large_message(update, reply)
    except Exception as e:
        await status_msg.edit_text(f"Error: {e}")

# ----------------------------------------------------
# VISION SOLVER ENGINE
# ----------------------------------------------------
def process_vision_query(image_bytes, user_text):
    prompt = (
        "Solve this question directly step-by-step.\n"
        "STRICT INSTRUCTIONS:\n"
        "1. Do NOT show solution plan or thinking logs.\n"
        "2. Do NOT use markdown stars (**) or raw LaTeX ($) tags.\n"
        "3. Use simple bullet points (•) and plain math characters (×, ², 10²³).\n"
        "4. Keep the output clean, short, and to the point."
    )
    if user_text:
        prompt += f"\nUser Instruction: {user_text}"

    if GEMINI_API_KEY:
        gemini_candidates = ["gemini-2.0-flash", "gemini-1.5-flash", "models/gemini-1.5-flash"]
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
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        try:
            completion = groq_client.chat.completions.create(
                model="llama-3.2-11b-vision-preview",
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
            pass

    return "System image read nahi kar paa raha hai, Sir. Please try again."

# ----------------------------------------------------
# MESSAGE ROUTER
# ----------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or update.message.caption or ""
    photo = update.message.photo

    allowed, count, is_vip = check_user_limit(user.id, user.username, user.first_name)
    if not allowed:
        await update.message.reply_text("Daily Limit Reached, Sir!")
        return

    # Handle Photo Doubts
    if photo:
        status_msg = await update.message.reply_text("Solving Question...")
        try:
            tg_file = await context.bot.get_file(photo[-1].file_id)
            image_bytes = await tg_file.download_as_bytearray()
            
            solution = process_vision_query(image_bytes, text)
            await status_msg.delete()
            await send_large_message(update, solution)
            return
        except Exception as e:
            await status_msg.edit_text(f"Error: {e}")
            return

    # Handle Text Input
    if text:
        try:
            completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are Jarvis AI created by Gaurav Sir. Answer in short, clean bullet points without extra stars or LaTeX tags."},
                    {"role": "user", "content": text}
                ],
                model=PRIMARY_MODEL
            )
            reply = completion.choices[0].message.content
            if reply:
                await send_large_message(update, reply)
        except Exception as e:
            await update.message.reply_text("Response generate nahi ho saka.")

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
    application.add_handler(CommandHandler("think", think_command))
    
    message_filter = (filters.TEXT | filters.PHOTO) & (~filters.COMMAND)
    application.add_handler(MessageHandler(message_filter, handle_message))

    application.run_polling()

if __name__ == "__main__":
    main()
    
