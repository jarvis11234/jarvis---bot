import os
import re
import random
import sqlite3
import threading
import time
import urllib.request
import asyncio
from datetime import datetime
from flask import Flask
from groq import Groq
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

app = Flask('')

@app.route('/')
def home():
    return "Jarvis is Online!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(url)
            print("Keep-alive ping sent successfully.")
        except Exception as e:
            print(f"Keep-alive ping failed: {e}")

# ==========================================
# DATABASE SETUP (SQLite)
# ==========================================
DB_FILE = "jarvis_users.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            last_seen TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def log_user(user):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, username, first_name, last_name, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            last_seen=excluded.last_seen
    ''', (
        user.id,
        user.username or "",
        user.first_name or "",
        user.last_name or "",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()

# Initialize Database on startup
init_db()

# Groq Setup
GROQ_KEY = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=GROQ_KEY)

AVAILABLE_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b"
]

SPECIAL_USERNAME = "kittykalia"

CAT_STICKERS = [
    "CAACAgUAAxkBAAER4G1qogV5bKhnyA39dcUNvy76xCXFVAACpSIAAgcVEVUntMLvaF-SsD0E",
]

CREATOR_INFO = "You were created, developed, and named by Gaurav Singh. Whenever someone asks who made you, who created you, who your owner/boss is, or who gave you your name, always proudly mention that Gaurav Singh is your creator."

def clean_thinking_process(text: str) -> str:
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return cleaned.strip()

# Admin command to view all logged users
async def get_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, last_seen FROM users")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("No users found in database.")
        return

    msg = "<b>Registered Jarvis Users:</b>\n\n"
    for row in rows:
        u_id, u_name, f_name, l_seen = row
        username_str = f"@{u_name}" if u_name else "No Username"
        msg += f"• <b>{f_name}</b> ({username_str})\n  ID: <code>{u_id}</code> | Last Seen: {l_seen}\n\n"

    await update.message.reply_text(msg, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return

    # Log user details to database automatically
    sender = update.message.from_user
    log_user(sender)

    is_private_chat = (update.message.chat.type == "private")
    if not is_private_chat and ("jarvis" not in user_text.lower()):
        return

    sender_username = sender.username if sender.username else ""
    first_name = sender.first_name if sender.first_name else ""
    last_name = sender.last_name if sender.last_name else ""
    
    full_name = f"{first_name} {last_name}".strip()

    is_kitty = (sender_username.lower() == SPECIAL_USERNAME.lower())
    is_umrah = "umrah" in full_name.lower()

    if is_umrah:
        if CAT_STICKERS:
            try:
                await update.message.reply_sticker(sticker=random.choice(CAT_STICKERS))
            except Exception as e:
                print(f"Sticker Error: {e}")
        greeting_prefix = "Aadaab Umrah jaan, "

    elif is_kitty:
        if CAT_STICKERS:
            try:
                await update.message.reply_sticker(sticker=random.choice(CAT_STICKERS))
            except Exception as e:
                print(f"Sticker Error: {e}")
        greeting_prefix = "Hello meow, "

    else:
        greeting_prefix = "At your service sir, "

    system_prompt = (
        f"You are Jarvis, an intelligent, respectful, and polite AI assistant. {CREATOR_INFO}\n\n"
        f"CRITICAL INSTRUCTIONS:\n"
        f"1. You MUST ALWAYS start your response exactly with the text: '{greeting_prefix}'.\n"
        f"2. After '{greeting_prefix}', answer their question accurately, politely, and intelligently."
    )

    reply = None
    last_error = None

    for model_name in AVAILABLE_MODELS:
        for attempt in range(2):
            try:
                loop = asyncio.get_event_loop()
                chat_completion = await loop.run_in_executor(
                    None,
                    lambda m=model_name: client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_text}
                        ],
                        model=m,
                        timeout=15.0
                    )
                )
                raw_reply = chat_completion.choices[0].message.content
                reply = clean_thinking_process(raw_reply)
                break
            except Exception as e:
                last_error = e
                await asyncio.sleep(1)
        if reply:
            break

    if reply:
        await update.message.reply_text(reply)
    else:
        print(f"Error: {last_error}")
        await update.message.reply_text(f"Jarvis Error: {last_error}")

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("users", get_users_list))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
    
