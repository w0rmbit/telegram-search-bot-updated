import telebot
import requests
import os
import re
import sys
import io
import tempfile
from telebot import types

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    print("Error: BOT_TOKEN environment variable is not set.")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# Store user states and data
user_states = {}
user_data = {}

# ---------------- MAIN MENU ----------------
def send_main_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_upload = types.InlineKeyboardButton("📤 Upload File", callback_data="upload_file")
    btn_search = types.InlineKeyboardButton("🔍 Search", callback_data="search")
    btn_delete = types.InlineKeyboardButton("🗑 Delete", callback_data="delete")
    markup.add(btn_upload, btn_search, btn_delete)
    bot.send_message(chat_id, "📌 Please choose an action:", reply_markup=markup)

# ---------------- START ----------------
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    reset_user(chat_id)
    send_main_menu(chat_id)

# ---------------- RESET ----------------
def reset_user(chat_id):
    # Remove all stored files
    if chat_id in user_data and 'files' in user_data[chat_id]:
        for path in user_data[chat_id]['files'].values():
            try:
                os.remove(path)
            except Exception:
                pass
    user_states[chat_id] = None
    user_data[chat_id] = {'files': {}}

# ---------------- CALLBACK HANDLER ----------------
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id

    if call.data == "upload_file":
        user_states[chat_id] = 'awaiting_url'
        bot.send_message(chat_id, "📤 Send me the file URL to upload.")

    elif call.data == "search":
        if user_data.get(chat_id, {}).get('files'):
            user_states[chat_id] = 'awaiting_search_file'
            choose_file_for_search(chat_id)
        else:
            bot.send_message(chat_id, "⚠️ No file uploaded yet.")
            send_main_menu(chat_id)

    elif call.data == "delete":
        files = user_data.get(chat_id, {}).get('files', {})
        if not files:
            bot.send_message(chat_id, "⚠️ No files to delete.")
            send_main_menu(chat_id)
        else:
            markup = types.InlineKeyboardMarkup()
            for fname in files.keys():
                markup.add(types.InlineKeyboardButton(f"🗑 {fname}", callback_data=f"delete_file:{fname}"))
            bot.send_message(chat_id, "Select a file to delete:", reply_markup=markup)

    elif call.data.startswith("delete_file:"):
        fname = call.data.split("delete_file:")[1]
        files = user_data.get(chat_id, {}).get('files', {})
        if fname in files:
            try:
                os.remove(files[fname])
            except Exception:
                pass
            del files[fname]
            bot.send_message(chat_id, f"✅ File `{fname}` deleted.", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, "⚠️ File not found.")
        send_main_menu(chat_id)

    elif call.data.startswith("search_file:"):
        fname = call.data.split("search_file:")[1]
        if fname in user_data[chat_id]['files']:
            user_states[chat_id] = f"awaiting_domain:{fname}"
            bot.send_message(chat_id, f"🔍 Send me the domain to search in `{fname}`", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, "⚠️ File not found.")
            send_main_menu(chat_id)

# ---------------- FILE UPLOAD ----------------
@bot.message_handler(func=lambda m: user_states.get(m.chat.id) == 'awaiting_url')
def handle_url(message):
    chat_id = message.chat.id
    url = message.text.strip()

    if not url.startswith(('http://', 'https://')):
        bot.send_message(chat_id, "⚠️ Invalid URL. Must start with http:// or https://")
        return

    try:
        bot.send_message(chat_id, "⏳ Downloading file... Please wait.")
        response = requests.get(url, stream=True, timeout=(10, 60))
        response.raise_for_status()

        file_name = os.path.basename(url.split("?")[0]) or f"file_{len(user_data[chat_id]['files'])+1}.txt"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        for chunk in response.iter_content(chunk_size=1024*1024):
            if chunk:
                temp_file.write(chunk)
        temp_file.close()

        # Store file path
        user_data[chat_id]['files'][file_name] = temp_file.name

        bot.send_message(chat_id, f"✅ File `{file_name}` downloaded and saved.", parse_mode="Markdown")
        send_main_menu(chat_id)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Error downloading file: {e}")
        send_main_menu(chat_id)

# ---------------- SEARCH ----------------
def choose_file_for_search(chat_id):
    markup = types.InlineKeyboardMarkup()
    for fname in user_data[chat_id]['files'].keys():
        markup.add(types.InlineKeyboardButton(f"🔍 {fname}", callback_data=f"search_file:{fname}"))
    bot.send_message(chat_id, "Select a file to search:", reply_markup=markup)

def make_progress_bar(percent, size=20):
    filled = int(size * percent / 100)
    bar = "▓" * filled + "░" * (size - filled)
    return f"[{bar}] {percent}%"

@bot.message_handler(func=lambda m: user_states.get(m.chat.id, "").startswith('awaiting_domain:'))
def handle_domain_and_search(message):
    chat_id = message.chat.id
    state = user_states[chat_id]
    fname = state.split("awaiting_domain:")[1]
    file_path = user_data[chat_id]['files'].get(fname)

    if not file_path:
        bot.send_message(chat_id, "⚠️ File not found.")
        send_main_menu(chat_id)
        return

    target_domain = message.text.strip()

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total_lines = len(lines)
        bot.send_message(chat_id, f"🔍 Searching for `{target_domain}` in `{fname}` ({total_lines:,} lines)...",
                         parse_mode="Markdown")

        found_lines_stream = io.BytesIO()
        found_lines_count = 0
        step = max(1, total_lines // 10)

        for i, line in enumerate(lines, start=1):
            if re.search(r'\b' + re.escape(target_domain) + r'\b', line, re.IGNORECASE):
                found_lines_stream.write(line.encode("utf-8"))
                found_lines_count += 1

            if i % step == 0:
                percent = int(i / total_lines * 100)
                progress_bar = make_progress_bar(percent)
                bot.send_message(chat_id, f"{progress_bar}\n📊 Found so far: {found_lines_count}")

        if found_lines_count > 0:
            bot.send_message(chat_id, f"✅ Search complete!\n📄 Total matches: *{found_lines_count}*",
                             parse_mode="Markdown")
            found_lines_stream.seek(0)
            bot.send_document(
                chat_id,
                found_lines_stream,
                visible_file_name=f"search_results_{target_domain}.txt",
                caption=f"📄 Results for *{target_domain}* in `{fname}`",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(chat_id, f"❌ No results for `{target_domain}` in `{fname}`.",
                             parse_mode="Markdown")

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Error while searching: {e}")

    finally:
        found_lines_stream.close()
        send_main_menu(chat_id)

# ---------------- RUN BOT ----------------
if __name__ == '__main__':
    print("🤖 Bot is running...")
    bot.polling(none_stop=True)
