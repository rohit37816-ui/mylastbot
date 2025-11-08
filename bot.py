import os
import json
import logging
import bcrypt
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ParseMode
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

active_sessions = set()  # user IDs logged in

# States for Conversations
LOGIN_USERNAME, LOGIN_PASSWORD = range(2)
REG_USERNAME, REG_PASSWORD = range(2, 4)
ADD_TITLE, ADD_TEXT = range(100, 102)
EDIT_CHOICE, EDIT_TITLE, EDIT_TEXT = range(102, 105)
FILE_UPLOAD = 105
CONFIRM_DELETE = 106

# In-memory user sections: user_id -> list of dict sections
user_sections = {}  # Example: {123456: [{"id": 1, "title": "...", "text": "...", "file_id": None}]}

# Utility for atomic JSON read/write (users.json, etc.)

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

# === Decorators ===

def requires_login(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in active_sessions:
            await update.message.reply_text("⚠️ You must be logged in. Use /login or /register.")
            return
        return await func(update, context)
    return wrapper

def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        return await func(update, context)
    return wrapper

# === Main logged-in menu ===

async def send_logged_in_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("➕ Add Section", callback_data="add_section"),
         InlineKeyboardButton("📂 Show Sections", callback_data="show_sections")],
        [InlineKeyboardButton("🔍 Search Sections", callback_data="search_sections"),
         InlineKeyboardButton("🗑️ Trash", callback_data="trash")],
        [InlineKeyboardButton("⭐ Favorites", callback_data="favorites"),
         InlineKeyboardButton("📤 Export", callback_data="export_sections")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats"),
         InlineKeyboardButton("🚪 Logout", callback_data="logout")],
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    if update.message:
        await update.message.reply_text("Choose an option:", reply_markup=keyboard)
    elif update.callback_query:
        await update.callback_query.edit_message_text("Choose an option:", reply_markup=keyboard)

# === Command Handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Hello, {update.effective_user.first_name}! Welcome to your Knowledge Manager Bot.\n\n"
        "Use /login or /register to get started."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """
Available commands:
/start - Show welcome message
/help - Show this help message
/login - Login to your account
/logout - Logout your session
/register - Create a new account
""")

# === Registration ===

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
    users[username] = {"password": hashed, "created_at": datetime.utcnow().isoformat(), "settings": {}}
    atomic_write_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ Registration successful! You can now /login with username: {username}")
    return ConversationHandler.END

async def register_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration cancelled.")
    return ConversationHandler.END

# === Login ===

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in active_sessions:
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
        await update.message.reply_text("User data corrupted, please try later or contact admin.")
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

# === Logout ===

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_sessions:
        active_sessions.remove(user_id)
        await update.message.reply_text("✅ Successfully logged out.")
    else:
        await update.message.reply_text("❌ You are not logged in.")

# === Show sections with per-section buttons ===

@requires_login
async def show_sections_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sections = user_sections.get(user_id, [])
    if not sections:
        await update.message.reply_text("You have no saved sections.")
        return

    # List section titles as buttons to edit/view
    buttons = []
    for sec in sections:
        buttons.append([InlineKeyboardButton(sec["title"], callback_data=f"section_{sec['id']}")])

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")])
    markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Your Sections:", reply_markup=markup)

# === Handle section selection and actions ===

async def section_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()
    data = query.data

    if data.startswith("section_"):
        section_id = int(data.split("_")[1])
        sections = user_sections.get(user_id, [])
        section = next((s for s in sections if s["id"] == section_id), None)

        if section is None:
            await query.edit_message_text("Section not found.")
            return
        
        # Section detail with action buttons two per row
        text = f"*{section['title']}*\n\n{section['text']}"
        buttons = [
            [InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{section_id}"),
             InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{section_id}")],
            [InlineKeyboardButton("⭐ Favorite", callback_data=f"fav_{section_id}"),
             InlineKeyboardButton("🔙 Back", callback_data="show_sections")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "show_sections":
        await show_sections_list(update, context)
        return

    if data == "back_to_menu":
        await send_logged_in_menu(update, context)
        return

    # TODO: Implement actual edit, delete, favorite handlers
    if data.startswith("edit_"):
        await query.edit_message_text("Edit feature coming soon!")
        return

    if data.startswith("delete_"):
        await query.edit_message_text("Delete feature coming soon!")
        return

    if data.startswith("fav_"):
        await query.edit_message_text("Favorite feature coming soon!")
        return

    if data == "logout":
        if user_id in active_sessions:
            active_sessions.remove(user_id)
            await query.edit_message_text("✅ Successfully logged out.")
        else:
            await query.edit_message_text("❌ You are not logged in.")
        return

    # For other unknown commands
    await query.edit_message_text("Unknown command or feature coming soon.")

# === Add Section Conversation ===

@requires_login
async def add_section_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please send the *title* of your new section:", parse_mode=ParseMode.MARKDOWN)
    return ADD_TITLE


async def add_section_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_section_title"] = update.message.text.strip()
    await update.message.reply_text("Now send the *content* of the section. You can also upload a PDF:", parse_mode=ParseMode.MARKDOWN)
    return ADD_TEXT


async def add_section_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    title = context.user_data.get("new_section_title")

    # Support file upload or text
    if update.message.document:
        # User uploaded a file
        file_id = update.message.document.file_id
        text = f"[Document uploaded: {update.message.document.file_name}](https://t.me/your_bot?start=download_{file_id})"
    else:
        text = update.message.text.strip()

    sections = user_sections.setdefault(user_id, [])
    section_id = len(sections) + 1
    now = datetime.utcnow().isoformat()
    section = {
        "id": section_id,
        "title": title,
        "text": text,
        "created_at": now,
        "updated_at": now,
        "file_id": update.message.document.file_id if update.message.document else None,
    }
    sections.append(section)

    await update.message.reply_text(f"✅ Section *{title}* added!", parse_mode=ParseMode.MARKDOWN)
    await send_logged_in_menu(update, context)
    return ConversationHandler.END

# === Main ===
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_username)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        }, fallbacks=[],
    )

    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            REG_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_username)],
            REG_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
        }, fallbacks=[CommandHandler("cancel", register_cancel)],
    )

    add_section_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_section_start)],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_section_title)],
            ADD_TEXT: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, add_section_text)],
        }, fallbacks=[],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(login_conv)
    application.add_handler(register_conv)
    application.add_handler(add_section_conv)
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(menu_callback_handler))

    print("Bot started...")
    application.run_polling()


if __name__ == "__main__":
    main()
