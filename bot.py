import os
import json
import logging
import bcrypt
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "6065778458"))

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Data and session management
DATA_DIR = Path("data")
USERS_FILE = Path("users.json")
DATA_DIR.mkdir(exist_ok=True)
if not USERS_FILE.exists():
    USERS_FILE.write_text("{}")

active_sessions = set()
user_sections = {}

# States
LOGIN_USERNAME, LOGIN_PASSWORD = range(2)
REG_USERNAME, REG_PASSWORD = range(2, 4)
ADD_TITLE, ADD_CONTENT = range(100, 102)
EDIT_TITLE, EDIT_CONTENT = range(102, 104)
CONFIRM_DELETE = 104

# Utility functions
def atomic_read_json(file_path: Path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read JSON {file_path}: {e}")
        corrupt_path = file_path.with_suffix(".corrupt.bak")
        os.rename(file_path, corrupt_path)
        return None

def atomic_write_json(file_path: Path, data: dict):
    tmp_file = file_path.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp_file, file_path)

# Decorators
def requires_login(func):
    async def inner(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in active_sessions:
            await update.message.reply_text("⚠️ You must be logged in. Use /login or /register.")
            return
        return await func(update, context)
    return inner

def owner_only(func):
    async def inner(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("❌ Not authorized.")
            return
        return await func(update, context)
    return inner

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /login or /register to begin.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start /help /login /logout /register /add /show /admin\nMore features coming soon!"
    )

# Registration
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter username to register:")
    return REG_USERNAME

async def register_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    users = atomic_read_json(USERS_FILE) or {}
    if username in users:
        await update.message.reply_text("Username exists, try another:")
        return REG_USERNAME
    context.user_data["register_username"] = username
    await update.message.reply_text("Enter a password:")
    return REG_PASSWORD

async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    username = context.user_data.get("register_username")
    users = atomic_read_json(USERS_FILE) or {}
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users[username] = {"password": hashed, "created_at": datetime.utcnow().isoformat()}
    atomic_write_json(USERS_FILE, users)
    await update.message.reply_text(f"Registered {username}! Use /login to sign in.")
    return ConversationHandler.END

async def register_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration cancelled.")
    return ConversationHandler.END

# Login
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_sessions:
        await update.message.reply_text("Already logged in.")
        await send_menu(update, context)
        return ConversationHandler.END
    await update.message.reply_text("Enter username:")
    return LOGIN_USERNAME

async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["login_username"] = update.message.text.strip()
    await update.message.reply_text("Enter password:")
    return LOGIN_PASSWORD

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get("login_username")
    password = update.message.text.strip()
    users = atomic_read_json(USERS_FILE)
    if not users or username not in users:
        await update.message.reply_text("Username not found. Please register first.")
        return ConversationHandler.END
    hashed = users[username]["password"].encode()
    if bcrypt.checkpw(password.encode(), hashed):
        active_sessions.add(update.effective_user.id)
        await update.message.reply_text(f"Logged in as {username}.")
        await send_menu(update, context)
    else:
        await update.message.reply_text("Incorrect password.")
    return ConversationHandler.END

# Logout
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_sessions:
        active_sessions.remove(user_id)
        await update.message.reply_text("Logged out.")
    else:
        await update.message.reply_text("You are not logged in.")

# Send menu with buttons two per row
async def send_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("➕ Add", callback_data="add"),
         InlineKeyboardButton("📂 Show", callback_data="show")],
        [InlineKeyboardButton("🔍 Search", callback_data="search"),
         InlineKeyboardButton("🗑️ Trash", callback_data="trash")],
        [InlineKeyboardButton("⭐ Favorite", callback_data="favorite"),
         InlineKeyboardButton("📤 Export", callback_data="export")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats"),
         InlineKeyboardButton("🚪 Logout", callback_data="logout")],
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    if update.message:
        await update.message.reply_text("Select option:", reply_markup=keyboard)
    else:
        await update.callback_query.edit_message_text("Select option:", reply_markup=keyboard)

# Callback query handler for menu buttons
@requires_login
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data == "add":
        await query.edit_message_text("Send title of the new section:")
        return ADD_TITLE
    elif data == "show":
        sections = user_sections.get(user_id, [])
        if not sections:
            await query.edit_message_text("No sections found.")
            return
        buttons = [[InlineKeyboardButton(sec["title"], callback_data=f"sec_{sec['id']}")] for sec in sections]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
        await query.edit_message_text("Your sections:", reply_markup=InlineKeyboardMarkup(buttons))
    elif data == "logout":
        if user_id in active_sessions:
            active_sessions.remove(user_id)
            await query.edit_message_text("Logged out successfully.")
        else:
            await query.edit_message_text("You are not logged in.")
    elif data == "back":
        await send_menu(update, context)
    else:
        await query.edit_message_text("Feature coming soon.")

# Add section conversation
async def add_section_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["section_title"] = update.message.text.strip()
    await update.message.reply_text("Send content or upload a PDF for this section:")
    return ADD_CONTENT

async def add_section_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    title = context.user_data["section_title"]
    if update.message.document:
        file_id = update.message.document.file_id
        content = f"[PDF document attached](https://t.me/file/{file_id})"
    else:
        content = update.message.text
    sections = user_sections.setdefault(user_id, [])
    new_id = len(sections) + 1
    sections.append({"id": new_id, "title": title, "text": content, "created_at": datetime.utcnow().isoformat()})
    await update.message.reply_text(f"Section '{title}' added.")
    await send_menu(update, context)
    return ConversationHandler.END

# Main function
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            REG_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_username)],
            REG_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
        },
        fallbacks=[CommandHandler("cancel", register_cancel)],
    )

    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_username)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        },
        fallbacks=[],
    )

    add_section_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback, pattern="^add$")],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_section_title)],
            ADD_CONTENT: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, add_section_content)],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(register_conv)
    app.add_handler(login_conv)
    app.add_handler(add_section_conv)
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CallbackQueryHandler(menu_callback))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
