import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from google import genai

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BOT_TRIGGER_NAME = os.environ.get("BOT_TRIGGER_NAME", "jarvis").lower()

ai_client = genai.Client(api_key=GEMINI_API_KEY)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    chat_type = update.message.chat.type

    if chat_type == "private" or BOT_TRIGGER_NAME in text.lower():
        prompt = f"You are Jarvis, a smart AI assistant. Reply helpfully to: {text}"
        
        try:
            response = ai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            reply_text = response.text
        except Exception as e:
            reply_text = "Sorry, I am facing an issue right now."

        await update.message.reply_text(reply_text)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Jarvis Bot Started Successfully!")
    app.run_polling()

if __name__ == '__main__':
    main()
