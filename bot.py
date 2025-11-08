import os
import json
import logging
import bcrypt
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
USERS_FILE = Path("users.json")
DATA_DIR.mkdir(exist_ok=True)
if not USERS_FILE.exists():
    USERS_FILE.write_text("{}")

active_sessions = set()
user_sections = {}

start_time = time.time()

# Conversation states
LOGIN_USERNAME, LOGIN_PASSWORD = range(2)
REG_USERNAME, REG_PASSWORD = range(2, 4)
ADD_TITLE, ADD_CONTENT = range(100, 102)
EDIT_TITLE, EDIT_CONTENT, DELETE_CONFIRM = range(102, 105)

# Utility functions
def atomic_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading {path}: {e}")
        corrupt_path = path.with_suffix(".corrupt.bak")
        os.rename(path, corrupt_path)
        return None

def atomic_write_json(path, data):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)

# Decorators
def requires_login(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in active_sessions:
            await update.message.reply_text("⚠️ Please /login or /register first.")
            return
        return await func(update, context)
    return wrapper

def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("❌ Unauthorized.")
            return
        return await func(update, context)
    return wrapper

# Commands

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /login or /register to get started.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Commands:\n"
        "/start - Start bot\n"
        "/help - Help message\n"
        "/login - Login\n"
        "/logout - Logout\n"
        "/register - Register\n"
        "/ping - Bot uptime\n"
        "/add - Add section\n"
        "/show - Show sections\n"
        "/admin - Admin panel (owner only)"
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = int(time.time() - start_time)
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)
    await update.message.reply_text(f"🏓 Pong! Uptime: {h}h {m}m {s}s")

# Registration
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Enter username:")
    return REG_USERNAME

async def register_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    users = atomic_read_json(USERS_FILE) or {}
    if username in users:
        await update.message.reply_text("❌ Username exists, try another:")
        return REG_USERNAME
    context.user_data["register_username"] = username
    await update.message.reply_text("🔑 Enter password:")
    return REG_PASSWORD

async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    username = context.user_data.get("register_username")
    users = atomic_read_json(USERS_FILE) or {}
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users[username] = {"password": hashed, "created_at": datetime.utcnow().isoformat()}
    atomic_write_json(USERS_FILE, users)
    await update.message.reply_text(f"✅ Registered *{username}*. Use /login.", parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def register_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration cancelled.")
    return ConversationHandler.END

# Login
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in active_sessions:
        await update.message.reply_text("⚠️ Already logged in.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    await update.message.reply_text("👤 Enter username:")
    return LOGIN_USERNAME

async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["login_username"] = update.message.text.strip()
    await update.message.reply_text("🔐 Enter password:")
    return LOGIN_PASSWORD

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get("login_username")
    password = update.message.text.strip()
    users = atomic_read_json(USERS_FILE) or {}
    user = users.get(username)
    if not user:
        await update.message.reply_text("❌ User not found. Please /register.")
        return ConversationHandler.END

    if bcrypt.checkpw(password.encode(), user["password"].encode()):
        active_sessions.add(update.effective_user.id)
        await update.message.reply_text(f"✅ Logged in as {username}.")
        await send_main_menu(update, context)
    else:
        await update.message.reply_text("❌ Incorrect password.")
    return ConversationHandler.END

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_sessions:
        active_sessions.remove(user_id)
        await update.message.reply_text("✅ Logged out successfully.")
    else:
        await update.message.reply_text("❌ You are not logged in.")

# Main menu buttons (3 per row)
async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [
            InlineKeyboardButton("➕ Add", callback_data="add_section"),
            InlineKeyboardButton("📂 Show", callback_data="show_sections"),
            InlineKeyboardButton("🔍 Search", callback_data="search_sections")
        ],
        [
            InlineKeyboardButton("🗑️ Trash", callback_data="trash"),
            InlineKeyboardButton("⭐ Favorites", callback_data="favorites"),
            InlineKeyboardButton("📤 Export", callback_data="export_sections")
        ],
        [
            InlineKeyboardButton("📊 Stats", callback_data="stats"),
            InlineKeyboardButton("🚪 Logout", callback_data="logout"),
            InlineKeyboardButton("ℹ️ Help", callback_data="help")
        ]
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    if update.message:
        await update.message.reply_text("Select an option:", reply_markup=keyboard)
    else:
        await update.callback_query.edit_message_text("Select an option:", reply_markup=keyboard)

# Menu callback handler
@requires_login
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    await query.answer()

    if data == "add_section":
        await query.edit_message_text("📝 Send section title:")
        return ADD_TITLE

    elif data == "show_sections":
        await show_sections(update, context)
        return

    elif data == "logout":
        if user_id in active_sessions:
            active_sessions.remove(user_id)
            await query.edit_message_text("✅ Logged out.")
        else:
            await query.edit_message_text("❌ You are not logged in.")
        return

    elif data == "help":
        await query.edit_message_text("Use /help for list of commands.")
        return

    else:
        await query.edit_message_text("❌ Unknown option.")

# Add section conversation
@requires_login
async def add_section_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["section_title"] = update.message.text.strip()
    await update.message.reply_text("Send section content or upload a PDF:")
    return ADD_CONTENT

async def add_section_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    title = context.user_data["section_title"]

    if update.message.document:
        file_id = update.message.document.file_id
        content = f"[PDF: {update.message.document.file_name}](https://t.me/file/{file_id})"
    else:
        content = update.message.text.strip()

    sections = user_sections.setdefault(user_id, [])
    new_id = len(sections) + 1
    sections.append({
        "id": new_id,
        "title": title,
        "text": content,
        "created_at": datetime.utcnow().isoformat()
    })
    await update.message.reply_text(f"✅ Added section *{title}*", parse_mode=ParseMode.MARKDOWN)
    await send_main_menu(update, context)
    return ConversationHandler.END

# Show sections with Back button (3 buttons per row)
@requires_login
async def show_sections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    sections = user_sections.get(user_id, [])
    if not sections:
        await query.edit_message_text("No sections saved yet.")
        return

    buttons = []
    row = []
    for sec in sections:
        row.append(InlineKeyboardButton(sec["title"], callback_data=f"section_{sec['id']}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")])
    await query.edit_message_text("Your sections:", reply_markup=InlineKeyboardMarkup(buttons))

# Section detail, edit, delete, favorite placeholders
@requires_login
async def section_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    await query.answer()

    if data.startswith("section_"):
        sec_id = int(data.split("_")[1])
        sections = user_sections.get(user_id, [])
        section = next((s for s in sections if s["id"] == sec_id), None)
        if not section:
            await query.edit_message_text("Section not found.")
            return

        buttons = [
            [
                InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{sec_id}"),
                InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{sec_id}"),
                InlineKeyboardButton("⭐ Favorite", callback_data=f"fav_{sec_id}")
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data="show_sections")
            ]
        ]
        text = f"*{section['title']}*\n\n{section['text']}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "show_sections" or data == "back_to_menu":
        await send_main_menu(update, context)
        return

    # TODO: implement edit, delete, favorite action handlers here with conversation flow

    await query.edit_message_text("Feature coming soon.")

# Admin panel
@owner_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("👥 List Users", callback_data="admin_list_users")],
        [InlineKeyboardButton("💾 Backup Data", callback_data="admin_backup")]
    ]
    await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup(buttons))

@owner_only
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "admin_list_users":
        users = atomic_read_json(USERS_FILE) or {}
        out = "\n".join(f"{u} (ID hidden)" for u in users.keys()) or "No users."
        await query.edit_message_text(f"Registered Users:\n{out}")
        return

    if data == "admin_backup":
        await query.edit_message_text("Backup not implemented.")
        return

    await query.edit_message_text("Unknown admin command.")

# Main app setup
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Conversations
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
        entry_points=[CallbackQueryHandler(menu_callback, pattern="^add_section$")],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_section_title)],
            ADD_CONTENT: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, add_section_content)],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))

    app.add_handler(register_conv)
    app.add_handler(login_conv)
    app.add_handler(add_section_conv)

    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("admin", admin_panel))

    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(menu_callback))
    app.add_handler(CallbackQueryHandler(section_callback, pattern="^section_"))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
