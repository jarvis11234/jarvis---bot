import os
import re
import random
import sqlite3
import threading
import time
import urllib.request
import asyncio
from datetime import datetime
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

app = Flask('')

@app.route('/')
def home():
    return "Jarvis is Online!"

# ==========================================
# MINI APP WEB ROUTE (Added Here)
# ==========================================
@app.route('/miniapp')
def mini_app():
    html_code = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Jarvis AI Assistant</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            body { background-color: #0f172a; color: #f8fafc; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
            
            /* Header */
            .header { background: #1e293b; padding: 15px; text-align: center; font-weight: bold; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
            .header h1 { font-size: 1.1rem; color: #38bdf8; }
            .vip-btn { background: #f59e0b; border: none; padding: 6px 12px; border-radius: 20px; font-weight: bold; color: #0f172a; cursor: pointer; font-size: 0.8rem; }

            /* Chat Window */
            .chat-box { flex: 1; padding: 15px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
            .message { max-width: 80%; padding: 10px 14px; border-radius: 12px; font-size: 0.95rem; line-height: 1.4; }
            .user-msg { background: #0284c7; align-self: flex-end; border-bottom-right-radius: 2px; }
            .bot-msg { background: #334155; align-self: flex-start; border-bottom-left-radius: 2px; }

            /* Input Bar */
            .input-area { background: #1e293b; padding: 10px; display: flex; gap: 8px; border-top: 1px solid #334155; }
            input { flex: 1; background: #0f172a; border: 1px solid #334155; color: white; padding: 12px; border-radius: 8px; outline: none; }
            button.send-btn { background: #38bdf8; border: none; padding: 0 16px; border-radius: 8px; font-weight: bold; color: #0f172a; cursor: pointer; }
        </style>
    </head>
    <body>

        <div class="header">
            <h1>🚀 Jarvis AI</h1>
            <button class="vip-btn" onclick="buyVip()">⭐ Upgrade VIP</button>
        </div>

        <div class="chat-box" id="chatBox">
            <div class="message bot-msg">Hello Gaurav! Main Jarvis hu. Kaise help karu aapki?</div>
        </div>

        <div class="input-area">
            <input type="text" id="userInput" placeholder="Ask Jarvis anything..." onkeypress="handleEnter(event)">
            <button class="send-btn" onclick="sendMessage()">Send</button>
        </div>

        <script>
            const tg = window.Telegram.WebApp;
            tg.expand(); // Full Screen View Open Karega

            function sendMessage() {
                const input = document.getElementById("userInput");
                const text = input.value.trim();
                if(!text) return;

                const chatBox = document.getElementById("chatBox");
                
                const userDiv = document.createElement("div");
                userDiv.className = "message user-msg";
                userDiv.innerText = text;
                chatBox.appendChild(userDiv);

                input.value = "";
                chatBox.scrollTop = chatBox.scrollHeight;

                setTimeout(() => {
                    const botDiv = document.createElement("div");
                    botDiv.className = "message bot-msg";
                    botDiv.innerText = "Processing: " + text;
                    chatBox.appendChild(botDiv);
                    chatBox.scrollTop = chatBox.scrollHeight;
                }, 800);
            }

            function handleEnter(e) {
                if(e.key === 'Enter') sendMessage();
            }

            function buyVip() {
                tg.sendData("/buyvip");
                tg.close();
            }
        </script>
    </body>
    </html>
    """
    
    return render_template_string(html_code)

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
# DATABASE SETUP (SQLite User Tracking)
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
            is_vip INTEGER DEFAULT 0,
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

def set_vip_status(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Check agar user pehle se DB me hai
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row:
        cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (user_id,))
    else:
        # Agar user nahi hai toh naya VIP record bana do
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, is_vip, last_seen) VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)",
            (user_id, "Owner", "Gaurav Singh")
        )
    conn.commit()
    conn.close()
    

# Initialize Database
init_db()
OWNER_ID = 8298044480
set_vip_status(OWNER_ID)

# Groq Setup
GROQ_KEY = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=GROQ_KEY)

# Active Validated Groq Models
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

# ==========================================
# TELEGRAM STARS PAYMENT HANDLERS
# ==========================================
async def send_star_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    
    title = "Jarvis VIP Access"
    description = "Unlock 30 Days Premium Access to Jarvis AI!"
    payload = "jarvis_vip_subscription"
    currency = "XTR"
    
    prices = [LabeledPrice("VIP Pass", 50)]

    await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",
        currency=currency,
        prices=prices
    )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    set_vip_status(user.id)
    await update.message.reply_text(f"Thank you {user.first_name}! Your Jarvis VIP Access has been successfully activated. 🚀")

# ==========================================
# ADMIN & MESSAGE HANDLERS
# ==========================================
async def get_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, is_vip, last_seen FROM users")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("No users found in database.")
        return

    msg = "<b>Registered Jarvis Users:</b>\n\n"
    for row in rows:
        u_id, u_name, f_name, is_vip, l_seen = row
        username_str = f"@{u_name}" if u_name else "No Username"
        vip_tag = "⭐ VIP" if is_vip else "Free User"
        msg += f"• <b>{f_name}</b> ({username_str}) - [{vip_tag}]\n  ID: <code>{u_id}</code> | Last Seen: {l_seen}\n\n"

    await update.message.reply_text(msg, parse_mode="HTML")
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return

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
    
    application.add_handler(CommandHandler("users", get_users_list))
    application.add_handler(CommandHandler("buyvip", send_star_invoice))
    
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
    
