import os
import io
import sqlite3
import re
import threading
import random
from PIL import Image
from flask import Flask
from groq import Groq
import google.generativeai as genai
from telegram import Update, ReactionTypeEmoji
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
DB_FILE = "male_ai_buddy.db"

app = Flask(__name__)

# API Clients Initialization
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Init Warning: {e}")

# ----------------------------------------------------
# FORMAT CLEANER
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
# SMART MESSAGE REACTION FUNCTION
# ----------------------------------------------------
async def send_smart_reaction(update: Update, text: str, is_photo: bool):
    """Message par context ke hisab se emoji reaction deta hai."""
    try:
        # Standard Telegram Reactions
        reaction_emoji = "👍"  # Default
        
        text_lower = text.lower() if text else ""
        
        if is_photo:
            reaction_emoji = random.choice(["👀", "👏", "🔥", "👍"])
        elif any(word in text_lower for word in ["haha", "lol", "funny", "chutkule", "joke", "haha"]):
            reaction_emoji = "😂"
        elif any(word in text_lower for word in ["bhai", "bro", "dost", " मस्त", "op", "great", "awesome"]):
            reaction_emoji = "🔥"
        elif any(word in text_lower for word in ["thanks", "dhanyawad", "thank you", "shukriya"]):
            reaction_emoji = "❤️"
        elif any(word in text_lower for word in ["bye", "gn", "good night", "so raha hu"]):
            reaction_emoji = "🕊"
        else:
            # 70% chance to react on normal messages so it feels natural and not spammy
            if random.random() < 0.7:
                reaction_emoji = random.choice(["👍", "👌", "🔥", "🤔"])
            else:
                return

        await update.message.set_reaction(reaction=[ReactionTypeEmoji(reaction_emoji)])
    except Exception as e:
        print(f"Reaction Error (Non-critical): {e}")

# ----------------------------------------------------
# DATABASE & USAGE LIMITS
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
    return "Male AI Companion + Reaction Engine Online"

# ----------------------------------------------------
# SYSTEM PROMPT (MALE AI PERSONA - NOVA COUNTERPART)
# ----------------------------------------------------
MALE_AI_SYSTEM_PROMPT = (
    "You are a smart, confident, warm, and highly capable male AI companion (the male counterpart to Nova). "
    "Your tone is strictly MALE (use Hindi/Hinglish male grammar like: 'mai kar dunga', 'mai dekh raha hu', 'bol bhai', 'mai samajh gaya').\n\n"
    "Key Personality Rules:\n"
    "1. Gender Tone: Always speak as a male buddy/brother/friend. Never use female verbs.\n"
    "2. Conversation Style: Relaxed, sharp, helpful, supportive, and natural. Speak like a cool guy friend who is always there to help.\n"
    "3. Listener & Problem Solver: Listen carefully to what the user says and give direct, practical answers without robotic filler phrases.\n"
    "4. Clean Formatting: NO LaTeX symbols, NO dollar signs ($), NO markdown asterisks (*). Plain clean text and simple bullet points (🔹) only."
)

# ----------------------------------------------------
# BOT HANDLERS
# ----------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    msg = (
        f"Haan {user_name}! Kya haal hai bhai? 😊\n\n"
        f"Main hoon tera AI buddy. Bata kya chal raha hai, koi kaam ho ya waise hi baat karni ho, bol main sun raha hoon! 👍"
    )
    await update.message.reply_text(msg)

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    if not check_user_limit(user_id):
        await update.message.reply_text("Bhai aaj ke 20 messages poore ho gaye hain. Kal aaram se baat karte hain 👍")
        return

    text = update.message.text or update.message.caption or ""
    photo = update.message.photo

    is_owner = (int(user_id) == int(OWNER_ID))

    # Send Reaction in background
    await send_smart_reaction(update, text, is_photo=bool(photo))

    system_prompt = MALE_AI_SYSTEM_PROMPT
    if is_owner:
        system_prompt += f"\nNote: You are talking directly to your creator/owner Gaurav Sir."
    else:
        system_prompt += f"\nNote: You are talking to user named {user_name}."

    # 1. PHOTO HANDLER
    if photo:
        status_msg = await update.message.reply_text("Haan bhai, photo dekh raha hoon... ek second de 🔍")
        try:
            tg_file = await context.bot.get_file(photo[-1].file_id)
            img_bytes = await tg_file.download_as_bytearray()
            image = Image.open(io.BytesIO(img_bytes))
            
            prompt = f"{system_prompt}\nUser Query: {text}\nExplain or solve this photo in simple language with male tone."
            
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
                await update.message.reply_text("Bhai photo thodi clear nahi lag rahi, ek baar dobara saaf karke bhej de.")
            return
        except Exception as e:
            await status_msg.edit_text(f"Error aaya bhai: {e}")
            return

    # 2. TEXT HANDLER
    if text:
        if groq_client:
            try:
                completion = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ],
                    model="llama-3.3-70b-versatile",
                    max_tokens=600,
                    temperature=0.6
                )
                reply = completion.choices[0].message.content
                await update.message.reply_text(clean_response_text(reply))
                return
            except Exception as e:
                print(f"Groq Error: {e}")

        # Fallback to Gemini
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
            await update.message.reply_text("Ek baar dobara bolna bhai, samajh nahi aaya properly.")

# ----------------------------------------------------
# MAIN EXECUTION
# ----------------------------------------------------
def run_flask_app():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

def main():
    init_db()
    
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_msg))
    
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
    
