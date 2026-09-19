import os
import time
import sqlite3
import threading
import urllib.request
import base64
import re
from flask import Flask, render_template_string
from groq import Groq
import google.generativeai as genai
from telegram import Update, LabeledPrice
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    PreCheckoutQueryHandler,
    filters
)

# ----------------------------------------------------
# CONFIGURATION & CONSTANTS
# ----------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OWNER_ID = 8298044480  # Backend Only Owner ID (Gaurav)
DB_FILE = "jarvis_bot.db"

RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "https://jarvis--bot.onrender.com")

app = Flask(__name__)

# Clients Setup
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Init Warning: {e}")

# Groq Active Text Models Stack
PRIMARY_MODEL = "openai/gpt-oss-20b"
SMART_MODEL = "openai/gpt-oss-120b"
BACKUP_MODEL = "qwen/qwen3.6-27b"

# Group Chat Memory
CHAT_MEMORY = {}

# ----------------------------------------------------
# CLEAN FORMATTING CONVERTER FOR TELEGRAM
# ----------------------------------------------------
def clean_latex_formatting(text: str) -> str:
    if not text:
        return ""
    
    # Math symbols & LaTeX Cleanup
    text = re.sub(r'\\times', '×', text)
    text = re.sub(r'\\div', '÷', text)
    text = re.sub(r'\\approx', '≈', text)
    text = re.sub(r'\\pm', '±', text)
    text = re.sub(r'\\gamma', 'γ', text)
    text = re.sub(r'\\alpha', 'α', text)
    text = re.sub(r'\\beta', 'β', text)
    text = re.sub(r'\\theta', 'θ', text)
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\msg_count\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1 / \2)', text)
    
    # Powers/Superscripts (10^{23} -> 10²³)
    superscript_map = {'0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', '+': '⁺', '-': '⁻'}
    def replace_power(match):
        power_str = match.group(1)
        return "".join(superscript_map.get(char, char) for char in power_str)

    text = re.sub(r'\^{?([0-9+-]+)}?', replace_power, text)

    # Clean Headers (### Header -> *Header*)
    text = re.sub(r'###\s*(.*)', r'*\1*', text)
    text = re.sub(r'##\s*(.*)', r'*\1*', text)
    text = re.sub(r'#\s*(.*)', r'*\1*', text)

    # Bullet points formatting (🔹)
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('* ') or stripped.startswith('- '):
            cleaned_lines.append("🔹 " + stripped[2:])
        else:
            cleaned_lines.append(line)
            
    return "\n".join(cleaned_lines).strip()
            # ----------------------------------------------------
# HELPER: TELEGRAM LONG MESSAGE SPLITTER (WITH MARKDOWN)
# ----------------------------------------------------
async def send_large_message(update: Update, text: str):
    clean_text = clean_latex_formatting(text)
    max_length = 4000
    
    if len(clean_text) <= max_length:
        try:
            await update.message.reply_text(clean_text, parse_mode='Markdown')
        except Exception:
            await update.message.reply_text(clean_text)
        return

    for i in range(0, len(clean_text), max_length):
        chunk = clean_text[i:i + max_length]
        try:
            await update.message.reply_text(chunk, parse_mode='Markdown')
        except Exception:
            await update.message.reply_text(chunk)

# ----------------------------------------------------
# SELF-PING AUTO KEEP ALIVE
# ----------------------------------------------------
def keep_alive():
    time.sleep(30)
    while True:
        try:
            req = urllib.request.Request(
                RENDER_APP_URL, 
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
        time.sleep(300)

# ----------------------------------------------------
# DATABASE FUNCTIONS
# ----------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_vip INTEGER DEFAULT 0,
            msg_count INTEGER DEFAULT 0,
            last_reset DATE DEFAULT CURRENT_DATE,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def set_vip_status(user_id, is_vip=1):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE users SET is_vip = ? WHERE user_id = ?", (is_vip, user_id))
    else:
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, is_vip, last_seen) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (user_id, "Owner", "Gaurav", is_vip)
        )
    conn.commit()
    conn.close()

def check_user_limit(user_id, username, first_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    is_owner = (int(user_id) == int(OWNER_ID))
    user_is_vip = 1 if is_owner else 0

    cursor.execute("SELECT is_vip, msg_count, last_reset FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if not row:
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, is_vip, msg_count, last_reset) VALUES (?, ?, ?, ?, 1, CURRENT_DATE)",
            (user_id, username or "N/A", first_name or "User", user_is_vip)
        )
        conn.commit()
        conn.close()
        return True, 1, user_is_vip

    is_vip, msg_count, last_reset = row

    if is_owner:
        cursor.execute(
            "UPDATE users SET is_vip = 1, username = ?, first_name = ?, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?",
            (username or "N/A", first_name or "Gaurav", user_id)
        )
        conn.commit()
        conn.close()
        return True, msg_count, 1

    if is_vip == 1:
        cursor.execute(
            "UPDATE users SET username = ?, first_name = ?, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?",
            (username or "N/A", first_name or "User", user_id)
        )
        conn.commit()
        conn.close()
        return True, msg_count, 1

    cursor.execute("SELECT CURRENT_DATE")
    today = cursor.fetchone()[0]

    if str(last_reset) != str(today):
        msg_count = 0
        cursor.execute("UPDATE users SET msg_count = 0, last_reset = CURRENT_DATE WHERE user_id = ?", (user_id,))

    if msg_count >= 10:
        conn.close()
        return False, msg_count, is_vip

    cursor.execute(
        "UPDATE users SET msg_count = msg_count + 1, username = ?, first_name = ?, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?",
        (username or "N/A", first_name or "User", user_id)
    )
    conn.commit()
    conn.close()
    return True, msg_count + 1, is_vip
    
