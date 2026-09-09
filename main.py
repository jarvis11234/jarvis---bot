import os
import threading
import time
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

AVAILABLE_MODELS = [
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b"
]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return

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

    reply = None
    last_error = None

    # Retry loop with fallback models
    for model_name in AVAILABLE_MODELS:
        for attempt in range(2):
            try:
                chat_completion = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text}
                    ],
                    model=model_name,
                    timeout=15.0
                )
                reply = chat_completion.choices[0].message.content
                break
            except Exception as e:
                last_error = e
                time.sleep(1)
        if reply:
            break

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
