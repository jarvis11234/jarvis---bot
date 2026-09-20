import os
import io
import sqlite3
import re
import threading
from PIL import Image
from flask import Flask
from google import genai
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OWNER_ID = 8298044480  # Gaurav Sir
DB_FILE = "jarvis_official.db"

app = Flask(__name__)

# Initialize Official Google GenAI Client
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ----------------------------------------------------
# STRICT TEXT & LATEX CLEANER
# Zero Dollars ($), Zero Asterisks (*), Plain Text Only
# ----------------------------------------------------
def clean_response_text(text: str) -> str:
    if not text:
        return ""
    # Remove Dollar signs & LaTeX delimiters
    text = text.replace("$", "").replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "")
    
    # Replace LaTeX operators
    text = re.sub(r'\\times', '×', text)
    text = re.sub(r'\\div', '÷', text)
    text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1 / \2)', text)
    
    # Remove markdown headers and stars
    text = re.sub(r'#+\s*', '', text)
    text = text.replace("**", "").replace("*", "")
    
    # Clean list bullet points
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
# DATABASE & LIMIT CONTROL
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
        return True  # Unlimited for Gaurav Sir
        
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
    return "Jarvis AI Official Core Online"

# ----------------------------------------------------
# BOT HANDLERS & JARVIS PERSONA
# ----------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    msg = (
        f"Online and ready, {user_name}!\n\n"
        f"I am Jarvis AI, created and owned by Gaurav Sir.\n\n"
        f"🔹 Direct NEET/JEE Doubt Solver\n"
        f"🔹 Instant High-Accuracy Image Reading\n\n"
        f"Bataiye, aaj kya solve karna hai?"
    )
    await update.message.reply_text(msg)

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    if not check_user_limit(user_id):
        await update.message.reply_text("Aapka daily limit (20 messages) khatam ho gaya hai. Kal dubara try karein!")
        return

    text = update.message.text or update.message.caption or ""
    photo = update.message.photo

    is_owner = (int(user_id) == int(OWNER_ID))
    boss_title = "Gaurav Sir" if is_owner else user_name

    system_instruction = (
        f"You are Jarvis AI, created and owned by Gaurav Sir. "
        f"You are speaking with {boss_title}. "
        f"Tone: Intelligent, sharp, respectful, and direct.\n"
        f"Rules:\n"
        f"1. Give direct answers immediately without fluff.\n"
        f"2. Absolutely NO dollar signs ($) or LaTeX math syntax.\n"
        f"3. Absolutely NO markdown asterisks (*).\n"
        f"4. Use plain text and simple bullet points (🔹)."
    )

    if not client:
        await update.message.reply_text("GEMINI_API_KEY missing hai Render environment variables me.")
        return

    # 1. PHOTO HANDLER (OFFICIAL GOOGLE-GENAI SDK + PILLOW)
    if photo:
        status_msg = await update.message.reply_text("Scanning image...")
        try:
            tg_file = await context.bot.get_file(photo[-1].file_id)
            img_bytes = await tg_file.download_as_bytearray()
            
            # PIL Image Conversion (Prevents crash)
            image = Image.open(io.BytesIO(img_bytes))
            
            prompt = f"{system_instruction}\nUser Query: {text}\nSolve this image directly in brief."
            
            # Official GenAI SDK Method
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt, image]
            )
            
            ans = clean_response_text(response.text) if response and response.text else "Image clear nahi hai, dobara bhejein."
            
            await status_msg.delete()
            await update.message.reply_text(ans)
            return
        except Exception as e:
            # Fallback to 2.0-flash if needed
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[prompt, image]
                )
                ans = clean_response_text(response.text)
                await status_msg.delete()
                await update.message.reply_text(ans)
                return
            except Exception as err:
                await status_msg.edit_text(f"Vision Error: {err}")
                return

    # 2. TEXT HANDLER (OFFICIAL GOOGLE-GENAI SDK)
    if text:
        try:
            full_prompt = f"{system_instruction}\nUser Query: {text}"
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=full_prompt
            )
            
            ans = clean_response_text(response.text) if response and response.text else "Response generate nahi ho paaya."
            await update.message.reply_text(ans)
        except Exception as e:
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=full_prompt
                )
                ans = clean_response_text(response.text)
                await update.message.reply_text(ans)
            except Exception as err:
                await update.message.reply_text(f"System Error: {err}")

# ----------------------------------------------------
# MAIN EXECUTION
# ----------------------------------------------------
# ----------------------------------------------------
# FIXED MAIN EXECUTION (No Processing Hang)
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

    
    
