import os
import io
import sqlite3
import re
import threading
import random
from PIL import Image
from flask import Flask
from groq import Groq
from google import genai
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
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

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
# SMART LOCAL CHAT FALLBACK (NO API DEPENDENCY)
# ----------------------------------------------------
def get_local_smart_reply(text: str) -> str:
    """Agar API response na de, toh ye local reply karega taaki bot 'bahera' na lage."""
    t = text.lower().strip()
    
    if t in ["hi", "hello", "hey", "hii", "helo", "hlo"]:
        return random.choice([
            "Haan bhai! Bol kya haal chaal?",
            "Haan ji, bataiye kya chal raha hai?",
            "Hello bhai! Bata kaise madad karun?"
        ])
    elif "kaise ho" in t or "kya haal" in t:
        return "Main badhiya hoon bhai! Tu bata, tera kya chal raha hai?"
    elif "kya kar rahe" in t or "kya kar raha" in t:
        return "Bas bhai, yahan tere messages ka wait kar raha hoon! Bata kya kaam hai?"
    elif "naam" in t:
        return "Main tera AI buddy hoon bhai!"
    elif "shukriya" in t or "thanks" in t or "thank you" in t:
        return "Arre koi baat nahi bhai, hamesha hazir hoon! 👍"
    
    return None

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
        elif any(word in text_lower for word in ["haha", "lol", "joke", "chutkula"]):
            reaction_emoji = "😂"
        elif any(word in text_lower for word in ["bhai", "bro", "op", "great", "mast"]):
            reaction_emoji = "🔥"
        elif any(word in text_lower for word in ["thanks", "thank you", "dhanyawad"]):
            reaction_emoji = "❤️"
        else:
            if random.random() < 0.7:
                reaction_emoji = random.choice(["👍", "👌", "🔥"])
            else:
                return

        await update.message.set_reaction(reaction=[ReactionTypeEmoji(reaction_emoji)])
    except Exception as e:
        print(f"Reaction Error: {e}")

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
    return "Male AI Companion Online"

# ----------------------------------------------------
# SYSTEM PROMPT
# ----------------------------------------------------
MALE_AI_SYSTEM_PROMPT = (
    "You are a smart, confident, warm, and highly capable male AI companion. "
    "Your tone is strictly MALE (use Hindi/Hinglish male grammar like: 'mai kar dunga', 'mai dekh raha hu', 'bol bhai', 'mai samajh gaya').\n\n"
    "Key Personality Rules:\n"
    "1. Gender Tone: Always speak as a male buddy/brother/friend. Never use female verbs.\n"
    "2. Conversation Style: Relaxed, sharp, helpful, supportive, and natural. Speak like a cool guy friend.\n"
    "3. Respond to casual greetings and chatter instantly and warmly in Hinglish.\n"
    "4. Clean Formatting: NO LaTeX symbols, NO dollar signs ($), NO markdown asterisks (*). Plain clean text only."
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
        system_prompt += f"\nNote: You are talking directly to Gaurav Sir."
    else:
        system_prompt += f"\nNote: You are talking to {user_name}."

    # 1. PHOTO HANDLER
    if photo:
        status_msg = await update.message.reply_text("Haan bhai, photo dekh raha hoon... ek second de 🔍")
        try:
            tg_file = await context.bot.get_file(photo[-1].file_id)
            img_bytes = await tg_file.download_as_bytearray()
            image = Image.open(io.BytesIO(img_bytes))
            
            if gemini_client:
                res = gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[image, f"{system_prompt}\nUser Query: {text}\nExplain this photo."]
                )
                await status_msg.delete()
                if res.text:
                    await update.message.reply_text(clean_response_text(res.text))
                    return
            
            await status_msg.delete()
            await update.message.reply_text("Bhai photo sahi se padh nahi paya, ek baar thodi clear photo bhej de.")
            return
        except Exception as e:
            await status_msg.edit_text(f"Error aaya bhai: {e}")
            return

    # TEXT HANDLER
    if text:
        reply = None

        # 1. Try Gemini First (Fastest & Free)
        if gemini_client:
            try:
                res = gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"{system_prompt}\nUser Query: {text}"
                )
                if res and res.text:
                    reply = res.text
            except Exception as e:
                print(f"Gemini Error: {e}")

        # 2. Try Groq as Backup
        if not reply and groq_client:
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
                if completion.choices:
                    reply = completion.choices[0].message.content
            except Exception as e:
                print(f"Groq Error: {e}")

        # 3. Final Output
        if reply:
            await update.message.reply_text(clean_response_text(reply))
        else:
            # Agar dono API temporary fail bhi hon, toh sensible response dega
            local_reply = get_local_smart_reply(text)
            if local_reply:
                await update.message.reply_text(local_reply)
            else:
                await update.message.reply_text("Haan bhai! Awaaz aa rahi hai, bol kya baat hai?")
    

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
