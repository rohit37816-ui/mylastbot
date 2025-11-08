import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# States for ConversationHandler example (login)
LOGIN_USERNAME, LOGIN_PASSWORD = range(2)


# Utility functions for safe JSON read/write
def atomic_read_json(file_path: Path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read JSON {file_path}: {e}")
        # rename corrupted file for backup and safety
        corrupt_path = file_path.with_suffix(".corrupt.bak")
        os.rename(file_path, corrupt_path)
        return None


def atomic_write_json(file_path: Path, data: dict):
    tmp_file = file_path.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp_file, file_path)


# Decorator to restrict commands to logged-in users
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


# Decorator to restrict commands to owner/admin only
def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != OWNER_ID:
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        return await func(update, context)

    return wrapper


# Command handlers

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


# User authentication commands placeholders
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # Password should be checked here (using bcrypt in real code)
    if password == user_info.get("password"):  # Placeholder, replace with hashed check
        active_sessions.add(update.effective_user.id)
        await update.message.reply_text(f"✅ Logged in as {username}")
    else:
        await update.message.reply_text("❌ Incorrect password.")

    return ConversationHandler.END


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_sessions:
        active_sessions.remove(user_id)
        await update.message.reply_text("✅ Successfully logged out.")
    else:
        await update.message.reply_text("You are not logged in.")


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


# Callback query handler for admin inline buttons example
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
        # Placeholder for backup logic
        await query.edit_message_text("Backup initiated (not implemented).")

    elif data == "admin_force_logout":
        await query.edit_message_text("Select user to force logout (not implemented).")

    else:
        await query.edit_message_text("Unknown admin command.")


# Main function

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Conversation handler for login process
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_username)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        },
        fallbacks=[],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(login_conv)
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(admin_callback_handler))

    # Add more command handlers here (add, show, edit, delete, trash, etc.)

    print("Bot started...")
    application.run_polling()


if __name__ == "__main__":
    main()
