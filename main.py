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

# List of active Groq models for fallback
AVAILABLE_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.2-11b-vision-preview",
    "llama3-8b-8192",
    "mixtral-8x7b-32768"
]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
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

    # Try models one by one until one works
    reply = None
    last_error = None

    for model_name in AVAILABLE_MODELS:
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                model=model_name
            )
            reply = chat_completion.choices[0].message.content
            break  # Stop loop if request succeeds
        except Exception as e:
            last_error = e
            continue  # Try next model

    if reply:
        await update.message.reply_text(reply)
    else:
        print(f"Error: {last_error}")
        await update.message.reply_text(f"Jarvis Error: {last_error}")

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
    
