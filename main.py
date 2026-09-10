import os
import re
import random
import threading
import time
import urllib.request
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

def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(url)
            print("Keep-alive ping sent successfully.")
        except Exception as e:
            print(f"Keep-alive ping failed: {e}")

# Groq Setup
GROQ_KEY = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=GROQ_KEY)

AVAILABLE_MODELS = [
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b"
]

SPECIAL_USERNAME = "kittykalia"

# MULTIPLE STICKERS
CAT_STICKERS = [
    "CAACAgUAAxkBAAER4G1qogV5bKhnyA39dcUNvy76xCXFVAACpSIAAgcVEVUntMLvaF-SsD0E",
]

# Base creator knowledge for Jarvis
CREATOR_INFO = "You were created, developed, and named by Gaurav Singh. Whenever someone asks who made you, who created you, who your owner/boss is, or who gave you your name, always proudly mention that Gaurav Singh is your creator."

def clean_thinking_process(text: str) -> str:
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return cleaned.strip()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return

    if "jarvis" not in user_text.lower():
        return

    sender = update.message.from_user
    sender_username = sender.username if sender.username else ""
    first_name = sender.first_name if sender.first_name else ""
    last_name = sender.last_name if sender.last_name else ""
    
    full_name = f"{first_name} {last_name}".lower()

    is_kitty = (sender_username.lower() == SPECIAL_USERNAME.lower())
    is_umrah = "umrah" in full_name

    # Umrah Specific Persona
    if is_umrah:
        if CAT_STICKERS:
            try:
                await update.message.reply_sticker(sticker=random.choice(CAT_STICKERS))
            except Exception as e:
                print(f"Sticker Error: {e}")

        system_prompt = (
            f"You are Jarvis, a deeply respectful, sweet, and affectionate AI assistant. {CREATOR_INFO} "
            "Since Umrah called you, ALWAYS start your response with: "
            "'Aadaab Umrah jaan, ' followed by a very polite, sweet, and caring response in gentle Hindustani/Urdu."
        )

    # Kittykalia Specific Persona
    elif is_kitty:
        if CAT_STICKERS:
            try:
                await update.message.reply_sticker(sticker=random.choice(CAT_STICKERS))
            except Exception as e:
                print(f"Sticker Error: {e}")

        system_prompt = (
            f"You are Jarvis, a sweet, playful and cute AI assistant. {CREATOR_INFO} "
            "Since the user specifically called you, ALWAYS start your response with: "
            "'Hello meow, ' followed by your response to their query."
        )

    # Standard Persona for everyone else
    else:
        system_prompt = (
            f"You are Jarvis, a highly intelligent AI assistant. {CREATOR_INFO} "
            "Since the user specifically called you, ALWAYS start your response with: "
            "'At your service sir, ' followed by your response to their query."
        )

    reply = None
    last_error = None

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
                raw_reply = chat_completion.choices[0].message.content
                reply = clean_thinking_process(raw_reply)
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
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()
    
