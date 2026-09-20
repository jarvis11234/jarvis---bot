import os
import sqlite3
import urllib.request
import re
from flask import Flask
import google.generativeai as genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OWNER_ID = 8298044480  # Gaurav Sir
DB_FILE = "gemini_bot.db"

app = Flask(__name__)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ----------------------------------------------------
# TEXT & LATEX CLEANER (No Dollars, No Stars)
# ----------------------------------------------------
def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("$", "").replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "")
    text = text.replace("**", "").replace("#", "")
    return text.strip()

# ----------------------------------------------------
# DATABASE
# ----------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            msg_count INTEGER DEFAULT 0,
            last_reset DATE DEFAULT CURRENT_DATE
        )
    ''')
    conn.commit()
    conn.close()

def check_limit(user_id):
    if int(user_id) == int(OWNER_ID):
        return True
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT msg_count, last_reset FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, msg_count, last_reset) VALUES (?, 1, CURRENT_DATE)", (user_id,))
        conn.commit()
        conn.close()
        return True
    count, last_reset = row
    cursor.execute("SELECT CURRENT_DATE")
    today = cursor.fetchone()[0]
    if str(last_reset) != str(today):
        cursor.execute("UPDATE users SET msg_count = 1, last_reset = CURRENT_DATE WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    if count >= 15:
        conn.close()
        return False
    cursor.execute("UPDATE users SET msg_count = msg_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True

# ----------------------------------------------------
# FLASK SERVER
# ----------------------------------------------------
@app.route('/')
def home():
    return "Gemini Speed Bot Active!"

# ----------------------------------------------------
# BOT HANDLERS
# ----------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gemini AI Ready! Direct text ya photo bhejiye, turant short answer milega.")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_limit(user_id):
        await update.message.reply_text("Daily limit reached!")
        return

    text = update.message.text or update.message.caption or ""
    photo = update.message.photo

    system_prompt = (
        "You are Gemini AI. Give extremely short, crisp, direct answers. "
        "No long intro, no dollars ($), no stars (*), no latex syntax. Plain text bullet points only."
    )

    if photo:
        try:
            tg_file = await context.bot.get_file(photo[-1].file_id)
            img_bytes = await tg_file.download_as_bytearray()
            
            model = genai.GenerativeModel("gemini-1.5-flash")
            img_data = {"mime_type": "image/jpeg", "data": bytes(img_bytes)}
            prompt = system_prompt + "\nSolve this image directly in short steps:" + text
            
            res = model.generate_content([prompt, img_data])
            ans = clean_text(res.text) if res and res.text else "Nahi padh paya, image dobara bhejein."
            await update.message.reply_text(ans)
            return
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            return

    if text:
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            res = model.generate_content(f"{system_prompt}\nUser Query: {text}")
            ans = clean_text(res.text) if res and res.text else "Response nahi mila."
            await update.message.reply_text(ans)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

def main():
    init_db()
    
    import threading
    port = int(os.environ.get("PORT", 5000))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_msg))
    
    application.run_polling()

if __name__ == "__main__":
    main()
        
