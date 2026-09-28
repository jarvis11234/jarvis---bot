import os
import io
import sqlite3
import re
import threading
import random
from PIL import Image
from flask import Flask
from telegram import Update, ReactionTypeEmoji
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters
)

# Naya Gemini SDK
try:
    from google import genai
except ImportError:
    genai = None

# Optional Groq SDK
try:
    from groq import Groq
except ImportError:
    Groq = None

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
groq_client = Groq(api_key=GROQ_API_KEY) if (Groq and GROQ_API_KEY) else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if (genai and GEMINI_API_KEY) else None

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
    try:
        text_lower = text.lower() if text else ""
        if is_photo:
            reaction_emoji = random.choice(["👀", "👏", "🔥", "👍"])
        elif any(word in text_lower for word in ["hi", "hello", "hey", "hii"]):
            reaction_emoji = "👍"
        elif any(word in text_lower for word in ["haha", "lol", "joke", "funny"]):
            reaction_emoji = "😂"
        elif any(word in text_lower for word in ["bhai", "bro", "op", "great", "mast"]):
            reaction_emoji = "🔥"
        elif any(word in text_lower for word in ["thanks", "thank you", "shukriya"]):
            reaction_emoji = "❤️"
        else:
            if random.random() < 0.7:
                reaction_emoji = random.choice(["👍", "👌", "🔥"])
            else:
                return

        await update.message.set_reaction(reaction=[ReactionTypeEmoji(reaction_emoji)])
    except Exception as e:
        print(f"Reaction Warning: {e}")

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
    return "Male AI Companion Engine Active"

# ----------------------------------------------------
# SYSTEM PROMPT
# ----------------------------------------------------
MALE_AI_SYSTEM_PROMPT = (
    "You are a smart, confident, warm, and highly capable male AI companion. "
    "Your tone is strictly MALE (use Hindi/Hinglish male grammar like: 'mai kar dunga', 'mai dekh raha hu', 'bol bhai', 'mai samajh gaya').\n\n"
    "Key Personality Rules:\n"
    "1. Gender Tone: Always speak as a male buddy/brother/friend. Never use female verbs.\n"
    "2. Conversation Style: Relaxed, sharp, helpful, supportive, and natural. Speak like a cool guy friend.\n"
    "3. Respond to all questions directly, accurately, and naturally.\n"
    "4. Clean Formatting: NO LaTeX symbols, NO dollar signs ($), NO markdown asterisks (*). Plain clean text only."
)

# ----------------------------------------------------
# BOT HANDLERS
# ----------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    msg = f"Haan {user_name}! Kya haal hai bhai? 😊\n\nMain hoon tera AI buddy. Bata kya chal raha hai, bol main sun raha hoon! 👍"
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

    # Send Reaction
    await send_smart_reaction(update, text, is_photo=bool(photo))

    system_prompt = MALE_AI_SYSTEM_PROMPT
    if is_owner:
        system_prompt += f"\nNote: You are talking directly to your creator Gaurav Sir."
    else:
        system_prompt += f"\nNote: You are talking to user {user_name}."

    # 1. PHOTO HANDLER
    if photo:
        status_msg = await update.message.reply_text("Haan bhai, photo dekh raha hoon... 🔍")
        try:
            tg_file = await context.bot.get_file(photo[-1].file_id)
            img_bytes = await tg_file.download_as_bytearray()
            image = Image.open(io.BytesIO(img_bytes))
            
            if gemini_client:
                res = gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[image, f"{system_prompt}\nUser Query: {text}\nExplain this image clearly."]
                )
                await status_msg.delete()
                if res and res.text:
                    await update.message.reply_text(clean_response_text(res.text))
                    return
            
            await status_msg.delete()
            await update.message.reply_text("Bhai photo read karne ke liye GEMINI_API_KEY zaruri hai.")
            return
        except Exception as e:
            await status_msg.edit_text(f"Error aaya photo read karne me: {e}")
            return

    # 2. TEXT HANDLER
    if text:
        ai_reply = None

        # --- OPTION 1: GEMINI 2.5 FLASH (Primary API) ---
        if gemini_client:
            try:
                res = gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"{system_prompt}\nUser Query: {text}"
                )
                if res and res.text:
                    ai_reply = res.text
            except Exception as e:
                print(f"Gemini API Error: {e}")

        # --- OPTION 2: GROQ MULTI-MODEL FALLBACK LIST ---
        # Agar Gemini fail hua, toh ye 5 Groq models ek-ek karke try honge
        groq_models = [
            "llama-3.3-70b-versatile",    # Top Model
            "llama-3.1-8b-instant",       # High-speed Backup
            "mixtral-8x7b-32768",         # Stable Backup
            "gemma2-9b-it",               # Alternative
            "llama3-70b-8192"             # Final Backup
        ]

        if not ai_reply and groq_client:
            for model_name in groq_models:
                try:
                    completion = groq_client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text}
                        ],
                        model=model_name,
                        max_tokens=600,
                        temperature=0.6
                    )
                    if completion.choices and completion.choices[0].message.content:
                        ai_reply = completion.choices[0].message.content
                        print(f"Groq Success with Model: {model_name}")
                        break
                except Exception as e:
                    print(f"Groq Model Failed ({model_name}): {e}")
                    continue

        # --- FINAL RESPONSE DELIVERY ---
        if ai_reply:
            await update.message.reply_text(clean_response_text(ai_reply))
        else:
            # Smart Local Chatter Backup (Agar saare APIs fail bhi hon)
            t = text.lower().strip()
            if any(w in t for w in ["hi", "hello", "hey", "hii"]):
                await update.message.reply_text("Haan bhai! Aur bata, kya haal chaal?")
            elif "kaise ho" in t:
                await update.message.reply_text("Ekdam mast bhai! Tu bata, tera kya chal raha hai?")
            else:
                await update.message.reply_text("Haan bhai, bol main sun raha hoon!")

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
    
