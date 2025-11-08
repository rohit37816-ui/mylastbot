import os
import json
import logging
import bcrypt
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

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Data and user session management
DATA_DIR = Path("data")
USERS_FILE = Path("users.json")
DATA_DIR.mkdir(exist_ok=True)
if not USERS_FILE.exists():
    USERS_FILE.write_text("{}")

active_sessions = set()  # Keeps track of logged-in user IDs

# States for ConversationHandlers
LOGIN_USERNAME, LOGIN_PASSWORD = range(2)
REG_USERNAME, REG_PASSWORD = range(2, 4)
ADD_TITLE, ADD_TEXT = range(100, 102)

# In-memory storage for demonstration (replace with file storage per user)
user_sections = {}  # {user_id: [{id, title, text, created_at, updated_at}]}


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


# Decorators for access control
def requires_login(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in active_sessions:
            await update.message.reply_text(
                "⚠️ You must be logged in to use this command. Use /login or /register."
            )
            return
        return await func(update, context)

    return wrapper


def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != OWNER_ID:
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        return await func(update, context)

    return wrapper


# Command handlers

async def send_logged_in_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("➕ Add Section", callback_data="add_section")],
        [InlineKeyboardButton("📂 Show Sections", callback_data="show_sections")],
        [InlineKeyboardButton("🔍 Search Sections", callback_data="search_sections")],
        [InlineKeyboardButton("🗑️ Trash", callback_data="trash")],
        [InlineKeyboardButton("⭐ Favorites", callback_data="favorites")],
        [InlineKeyboardButton("📤 Export Sections", callback_data="export_sections")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats")],
        [InlineKeyboardButton("🚪 Logout", callback_data="logout")],
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    if update.message:
        await update.message.reply_text("Choose an option:", reply_markup=keyboard)
    elif update.callback_query:
        await update.callback_query.edit_message_text("Choose an option:", reply_markup=keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    greeting = f"Hello, {user.first_name}! Welcome to your Knowledge Manager Bot.\n\n"
    greeting += "Use /login or /register to get started."
    await update.message.reply_text(greeting)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commands_text = """
Available commands:
/start - Show welcome message
/help - Show this help message
/login - Login to your account
/logout - Logout your session
/register - Create a new account
/add - Add a section (requires login)
/show - Show your sections (requires login)
/edit - Edit a section (requires login)
/delete - Delete a section (requires login)
/trash - View trash items (requires login)
/search - Search your sections (requires login)
/export - Export your sections (requires login)
/backup - Backup your data (owner only)
/restore - Restore from backup (owner only)
/stats - Statistics (requires login)
/admin - Admin panel (owner only)
"""
    await update.message.reply_text(commands_text)


# Registration conversation handlers

async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please enter a username to register:")
    return REG_USERNAME


async def register_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    users = atomic_read_json(USERS_FILE) or {}

    if username in users:
        await update.message.reply_text("⚠️ Username already exists. Please try a different one:")
        return REG_USERNAME

    context.user_data["register_username"] = username
    await update.message.reply_text("Please enter a password:")
    return REG_PASSWORD


async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    username = context.user_data.get("register_username")
    users = atomic_read_json(USERS_FILE) or {}

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    users[username] = {
        "password": hashed,
        "created_at": datetime.utcnow().isoformat(),
        "settings": {}
    }
    atomic_write_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ Registration successful! You can now /login with username: {username}")
    return ConversationHandler.END


async def register_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration cancelled.")
    return ConversationHandler.END


# User authentication commands placeholders for login

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_sessions:
        await update.message.reply_text("⚠️ You are already logged in.")
        await send_logged_in_menu(update, context)
        return ConversationHandler.END
    await update.message.reply_text("Please enter your username:")
    return LOGIN_USERNAME


async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["login_username"] = update.message.text.strip()
    await update.message.reply_text("Please enter your password:")
    return LOGIN_PASSWORD


async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get("login_username")
    password = update.message.text.strip()

    users = atomic_read_json(USERS_FILE)
    if users is None:
        await update.message.reply_text(
            "User data corrupted, please try again later or contact admin."
        )
        return ConversationHandler.END

    user_info = users.get(username)
    if not user_info:
        await update.message.reply_text("Username not found. Please register first.")
        return ConversationHandler.END

    hashed = user_info.get("password", "").encode('utf-8')
    if bcrypt.checkpw(password.encode('utf-8'), hashed):
        active_sessions.add(update.effective_user.id)
        await update.message.reply_text(f"✅ Logged in as {username}")
        await send_logged_in_menu(update, context)
    else:
        await update.message.reply_text("❌ Incorrect password.")

    return ConversationHandler.END


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_sessions:
        active_sessions.remove(user_id)
        await update.message.reply_text("✅ Successfully logged out.")
    else:
        await update.message.reply_text("❌ You are not logged in.")


# Admin command placeholder
@owner_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("List All Users", callback_data="admin_list_users")],
        [InlineKeyboardButton("Backup All Data", callback_data="admin_backup")],
        [InlineKeyboardButton("Force Logout User", callback_data="admin_force_logout")],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Admin Panel:", reply_markup=reply_markup)


# Callback query handler for admin inline buttons and main menu

@owner_only
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "admin_list_users":
        users = atomic_read_json(USERS_FILE) or {}
        user_list = "\n".join(users.keys()) if users else "No users found."
        await query.edit_message_text(f"Registered Users:\n{user_list}")

    elif data == "admin_backup":
        await query.edit_message_text("Backup initiated (not implemented).")

    elif data == "admin_force_logout":
        await query.edit_message_text("Select user to force logout (not implemented).")

    else:
        await query.edit_message_text("Unknown admin command.")


async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()
    data = query.data

    if user_id not in active_sessions:
        await query.edit_message_text("⚠️ You must be logged in to use the menu.")
        return

    if data == "add_section":
        await query.edit_message_text("Send me the *title* of your new section:", parse_mode=ParseMode.MARKDOWN)
        return ADD_TITLE

    elif data == "show_sections":
        sections = user_sections.get(user_id, [])
        if not sections:
            await query.edit_message_text("You have no saved sections.")
            return
        msg = "📝 Your Sections:\n\n"
        for sec in sections:
            msg += f"• *{sec['title']}*\n\n{sec['text']}\n\n"
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)

    elif data == "logout":
        if user_id in active_sessions:
            active_sessions.remove(user_id)
            await query.edit_message_text("✅ Successfully logged out.")
        else:
            await query.edit_message_text("❌ You are not logged in.")

    else:
        await query.edit_message_text("Feature coming soon or unknown command.")


async def add_section_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_section_title"] = update.message.text.strip()
    await update.message.reply_text("Now send the *content* of the section:", parse_mode=ParseMode.MARKDOWN)
    return ADD_TEXT


async def add_section_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    title = context.user_data.get("new_section_title")
    text = update.message.text.strip()

    sections = user_sections.setdefault(user_id, [])
    section_id = len(sections) + 1
    now = datetime.utcnow().isoformat()

    sections.append({
        "id": section_id,
        "title": title,
        "text": text,
        "created_at": now,
        "updated_at": now,
    })

    await update.message.reply_text(f"✅ Section *{title}* added!", parse_mode=ParseMode.MARKDOWN)
    await send_logged_in_menu(update, context)
    return ConversationHandler.END


# Main function
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_username)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        },
        fallbacks=[],
    )

    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            REG_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_username)],
            REG_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
        },
        fallbacks=[CommandHandler("cancel", register_cancel)],
    )

    add_section_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback_handler, pattern='^add_section$')],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_section_title)],
            ADD_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_section_text)],
        },
        fallbacks=[],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(login_conv)
    application.add_handler(register_conv)
    application.add_handler(add_section_conv)
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(admin_callback_handler))
    application.add_handler(CallbackQueryHandler(menu_callback_handler))

    print("Bot started...")
    application.run_polling()


if __name__ == "__main__":
    main()
