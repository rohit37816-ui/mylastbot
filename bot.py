import os
import json
import logging
import bcrypt
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.constants import ParseMode as ParseModeConstant
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "6065778458"))

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

# Conversation states
LOGIN_USERNAME, LOGIN_PASSWORD = range(2)
REG_USERNAME, REG_PASSWORD = range(2, 4)
ADD_TITLE, ADD_CONTENT = range(100, 102)
SHOW_SECTION, EDIT_CHOICE, EDIT_TITLE, EDIT_CONTENT, DELETE_CONFIRM = range(102, 107)

# Utility functions
def atomic_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read {path}: {e}")
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
            await update.message.reply_text("⚠️ Please log in first (/login or /register).")
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

# --- MENU FUNCTIONS ---

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [
            InlineKeyboardButton("➕ Add Section", callback_data="add_section"),
            InlineKeyboardButton("📂 Show Sections", callback_data="show_sections"),
        ],
        [
            InlineKeyboardButton("🔍 Search Sections", callback_data="search_sections"),
            InlineKeyboardButton("🗑️ Trash", callback_data="trash"),
        ],
        [
            InlineKeyboardButton("⭐ Favorites", callback_data="favorites"),
            InlineKeyboardButton("📤 Export", callback_data="export"),
        ],
        [
            InlineKeyboardButton("📊 Stats", callback_data="stats"),
            InlineKeyboardButton("🚪 Logout", callback_data="logout"),
        ],
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    if update.message:
        await update.message.reply_text("Select an option:", reply_markup=keyboard)
    else:
        await update.callback_query.edit_message_text("Select an option:", reply_markup=keyboard)

# --- COMMAND HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Hello {update.effective_user.first_name}! Welcome to Knowledge Manager.\n"
        "Use /login or /register to get started."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
Commands:
/start - Welcome message
/help - This help
/login - Login to your account
/logout - Logout your session
/register - Create account
/add - Add new section (login required)
/show - Show your sections (login required)
/admin - Admin panel (owner only)
"""
    await update.message.reply_text(text)

# --- REGISTER CONVERSATION ---

async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter username:")
    return REG_USERNAME

async def register_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    users = atomic_read_json(USERS_FILE) or {}
    if username in users:
        await update.message.reply_text("Username exists, pick another:")
        return REG_USERNAME
    context.user_data["register_username"] = username
    await update.message.reply_text("Enter password:")
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

# --- LOGIN CONVERSATION ---

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in active_sessions:
        await update.message.reply_text("You are already logged in.")
        await send_main_menu(update, context)
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
    users = atomic_read_json(USERS_FILE) or {}

    user = users.get(username)
    if not user:
        await update.message.reply_text("User not found, please register.")
        return ConversationHandler.END

    if bcrypt.checkpw(password.encode(), user["password"].encode()):
        active_sessions.add(update.effective_user.id)
        await update.message.reply_text(f"Logged in as {username}.")
        await send_main_menu(update, context)
    else:
        await update.message.reply_text("Incorrect password.")
    return ConversationHandler.END

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_sessions:
        active_sessions.remove(user_id)
        await update.message.reply_text("Logged out.")
    else:
        await update.message.reply_text("You are not logged in.")

# --- ADD SECTION CONVERSATION ---

@requires_login
async def add_section_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send the *title* of the section:", parse_mode=ParseModeConstant.MARKDOWN)
    return ADD_TITLE

async def add_section_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["section_title"] = update.message.text.strip()
    await update.message.reply_text("Send the *content* of the section or upload a PDF:", parse_mode=ParseModeConstant.MARKDOWN)
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

    await update.message.reply_text(f"Added section *{title}*.", parse_mode=ParseModeConstant.MARKDOWN)
    await send_main_menu(update, context)
    return ConversationHandler.END

# --- SHOW SECTIONS AND SECTION ACTIONS ---

@requires_login
async def show_sections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sections = user_sections.get(user_id, [])
    if not sections:
        await update.message.reply_text("No sections found.")
        return

    buttons = [
        [InlineKeyboardButton(sec["title"], callback_data=f"section_{sec['id']}")]
        for sec in sections
    ]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    await update.message.reply_text("Your sections:", reply_markup=InlineKeyboardMarkup(buttons))

async def section_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()
    data = query.data

    if data.startswith("section_"):
        section_id = int(data.split("_")[1])
        sections = user_sections.get(user_id, [])
        section = next((s for s in sections if s["id"] == section_id), None)
        if not section:
            await query.edit_message_text("Section not found.")
            return

        text = f"*{section['title']}*\n\n{section['text']}"
        buttons = [
            [
                InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{section_id}"),
                InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{section_id}")
            ],
            [
                InlineKeyboardButton("⭐ Favorite", callback_data=f"fav_{section_id}"),
                InlineKeyboardButton("🔙 Back", callback_data="show_sections"),
            ]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseModeConstant.MARKDOWN)
        return

    if data == "show_sections":
        await show_sections(update, context)
        return

    if data == "back":
        await send_main_menu(update, context)
        return

    # Placeholder for edit, delete, favorite commands
    if data.startswith("edit_"):
        await query.edit_message_text("Edit feature coming soon.")
        return

    if data.startswith("delete_"):
        await query.edit_message_text("Delete feature coming soon.")
        return

    if data.startswith("fav_"):
        await query.edit_message_text("Favorite feature coming soon.")
        return

    if data == "logout":
        if user_id in active_sessions:
            active_sessions.remove(user_id)
            await query.edit_message_text("Logged out.")
        else:
            await query.edit_message_text("You are not logged in.")
        return

    await query.edit_message_text("Unknown command.")

# --- ADMIN PANEL ---

@owner_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("List Users", callback_data="admin_list_users")],
        [InlineKeyboardButton("Backup Data", callback_data="admin_backup")]
    ]
    await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup(buttons))

@owner_only
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "admin_list_users":
        users = atomic_read_json(USERS_FILE) or {}
        list_text = "\n".join(f"{u} (ID hidden)" for u in users.keys()) or "No users found."
        await query.edit_message_text(f"Registered Users:\n{list_text}")
        return

    if data == "admin_backup":
        await query.edit_message_text("Backup not implemented yet.")
        return

    await query.edit_message_text("Unknown admin command.")

# --- MAIN FUNCTION ---

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            REG_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_username)],
            REG_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
        },
        fallbacks=[CommandHandler("cancel", register_cancel)]
    )
    application.add_handler(register_conv)

    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_username)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        },
        fallbacks=[]
    )
    application.add_handler(login_conv)

    add_section_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback, pattern="^add_section$")],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_section_title)],
            ADD_CONTENT: [
                MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, add_section_content)
            ],
        },
        fallbacks=[]
    )
    application.add_handler(add_section_conv)

    application.add_handler(CommandHandler("logout", logout))

    # Callback query handlers
    application.add_handler(CallbackQueryHandler(menu_callback))
    application.add_handler(CallbackQueryHandler(section_callback, pattern="^section_"))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))

    application.add_handler(CommandHandler("admin", admin_panel))

    print("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
