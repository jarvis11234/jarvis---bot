import os
import threading
from flask import Flask
from groq import Groq
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

app = Flask('')

@app.route('/')
def home():
    return "Jarvis is Online!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Groq Setup
GROQ_KEY = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=GROQ_KEY)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # Check if 'jarvis' is mentioned in the message
    is_jarvis_called = "jarvis" in user_text.lower()
    
    if is_jarvis_called:
        system_prompt = (
            "You are Jarvis, a highly intelligent AI assistant. "
            "Since the user specifically called you, ALWAYS start your response with: "
            "'At your service sir, ' followed by your response to their query."
        )
    else:
        system_prompt = (
            "You are Jarvis, a smart and helpful AI assistant. "
            "Answer the user's message accurately and politely."
        )

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_text
                }
            ],
            model="llama-3.1-8192"
        )
        
        reply = chat_completion.choices[0].message.content
        await update.message.reply_text(reply)
        
    except Exception as e:
        print(f"Error: {e}")
        await update.message.reply_text(f"Jarvis Error: {e}")

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
                     
