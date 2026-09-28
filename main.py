import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

# Logging setup (Render logs dekhne ke liye)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Render Environment Variables se keys retrieval
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Groq Client Initialization
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Male AI Personality Instructions for DAVID
SYSTEM_PROMPT = (
    "Aapka naam 'David' hai. Aap ek smart, confident, stylish, respectful aur energetic male AI assistant hain. "
    "Aap casual Hinglish me baat karte hain. Aapke replies clear, sharp, friendly aur engaging hote hain."
)

# Memory storage (per user chat history)
user_conversations = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_text = f"Hey {user_name}! Main **David** hoon. Batao aaj kya plan hai, kaise help karoon?"
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    # User ke history ka setup
    if user_id not in user_conversations:
        user_conversations[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # User message append karna
    user_conversations[user_id].append({"role": "user", "content": user_text})
    
    # Context window limit (last 10 messages) memory manage karne ke liye
    if len(user_conversations[user_id]) > 11:
        user_conversations[user_id] = [user_conversations[user_id][0]] + user_conversations[user_id][-10:]

    try:
        # Groq Llama-3 AI Model Call
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=user_conversations[user_id],
            temperature=0.7,
            max_tokens=500
        )
        
        reply = response.choices[0].message.content
        user_conversations[user_id].append({"role": "assistant", "content": reply})
        
        await update.message.reply_text(reply)

    except Exception as e:
        logging.error(f"Error: {e}")
        await update.message.reply_text("Bhai thoda issue aa gaya backend me, ek baar firse try karna!")

def main():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN missing in Environment Variables!")
        return

    # Telegram Bot App
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("David is Online and Ready!")
    app.run_polling()

if __name__ == "__main__":
    main()
