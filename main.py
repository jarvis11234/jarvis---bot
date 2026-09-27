import os
import io
import sqlite3
import re
import threading
from PIL import Image
from flask import Flask
from groq import Groq
import google.generativeai as genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters
)

# ----------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OWNER_ID = 8298044480  # Gaurav Sir
DB_FILE = "jarvis_mira.db"

app = Flask(__name__)

# Clients Setup
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Init Warning: {e}")

# ----------------------------------------------------
# FORMAT CLEANER (No Dollars, No Stars)
# ----------------------------------------------------
def clean_response_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("$", "").replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "")
    text = re.sub(r'\\times', '×', text)
    text = re.sub(r'\\div', '÷', text)
    text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1 / \2)', text)
    text = re.sub(r'#+\s*', '', text)
    text = text.replace("**", "").replace("*", "")
    
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('- ') or stripped.startswith('• '):
            cleaned_lines.append("🔹 " + stripped[2:])
        else:
            cleaned_lines.append(line)
            
    return "\n".join(cleaned_lines).strip()

# ----------------------------------------------------
# DATABASE & LIMITS
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

def check_user_limit(user_id):
    if int(user_id) == int(OWNER_ID):
        return True  # Unlimited access for Gaurav Sir
        
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
        
    if count >= 20:
        conn.close()
        return False
        
    cursor.execute("UPDATE users SET msg_count = msg_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True

# ----------------------------------------------------
# FLASK WEB SERVER
# ----------------------------------------------------
@app.route('/')
def home():
    return "Mira Engine Online (Groq + Gemini Vision)"

# ----------------------------------------------------
# BOT HANDLERS & PERSONA
# ----------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    msg = (
        f"Namaste {user_name}! Main Mira AI hoon, Gaurav Sir dwara manage kiya gaya.\n\n"
        f"🔹 Lightning-Fast Text Answers (Powered by Groq)\n"
        f"🔹 High-Accuracy Image Reading (Powered by Gemini Vision)\n\n"
        f"Aap apna koi bhi sawaal ya photo bhej sakte hain!"
    )
    await update.message.reply_text(msg)

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    if not check_user_limit(user_id):
        await update.message.reply_text("Daily limit (20 messages) finished! Kal try karein.")
        return

    text = update.message.text or update.message.caption or ""
    photo = update.message.photo

    is_owner = (int(user_id) == int(OWNER_ID))
    boss_title = "Gaurav Sir" if is_owner else user_name

    system_prompt = (
        f"You are Mira AI, created and owned by Gaurav Sir. You are speaking with {boss_title}. "
        f"Give direct, short, accurate answers. "
        f"Strict Rules: NO dollar signs ($), NO LaTeX, NO markdown asterisks (*). Plain text bullet points (🔹) only."
    )

    # 1. PHOTO HANDLER (GEMINI VISION VIA PIL)
    if photo:
        status_msg = await update.message.reply_text("📸 Scanning image...")
        try:
            tg_file = await context.bot.get_file(photo[-1].file_id)
            img_bytes = await tg_file.download_as_bytearray()
            image = Image.open(io.BytesIO(img_bytes))
            
            prompt = f"{system_prompt}\nUser Query: {text}\nSolve this image directly step-by-step."
            
            # Multi-model fallback for Gemini Vision
            response_text = None
            for m_name in ["models/gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-2.0-flash"]:
                try:
                    model = genai.GenerativeModel(m_name)
                    res = model.generate_content([prompt, image])
                    if res and res.text:
                        response_text = res.text
                        break
                except Exception:
                    continue

            await status_msg.delete()
            if response_text:
                await update.message.reply_text(clean_response_text(response_text))
            else:
                await update.message.reply_text("Image read nahi ho paayi, dobara photo bhejein.")
            return
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Vision Error: {e}")
            return

    # 2. TEXT HANDLER (GROQ FAST ENGINE WITH GEMINI FALLBACK)
    if text:
        if groq_client:
            try:
                completion = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ],
                    model="llama-3.3-70b-versatile",
                    max_tokens=600
                )
                reply = completion.choices[0].message.content
                await update.message.reply_text(clean_response_text(reply))
                return
            except Exception as e:
                print(f"Groq Text Error: {e}")

        # Fallback to Gemini for text if Groq fails
        response_text = None
        for m_name in ["models/gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-2.0-flash"]:
            try:
                model = genai.GenerativeModel(m_name)
                res = model.generate_content(f"{system_prompt}\nUser Query: {text}")
                if res and res.text:
                    response_text = res.text
                    break
            except Exception:
                continue

        if response_text:
            await update.message.reply_text(clean_response_text(response_text))
        else:
            await update.message.reply_text("System Error: Response generate nahi ho paaya.")

# ----------------------------------------------------
# MAIN EXECUTION (NON-BLOCKING FLASK + TELEGRAM)
# ----------------------------------------------------
def run_flask_app():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

def main():
    init_db()
    
    # Daemon thread for Flask server
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()

    # Telegram Bot setup
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_msg))
    
    # Start Polling
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
