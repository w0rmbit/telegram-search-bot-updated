import telebot
import requests
import os
import re
import sys
import io
from urllib.parse import urlparse
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
    btn_upload = types.InlineKeyboardButton("📤 Add Link", callback_data="upload_file")
    btn_search = types.InlineKeyboardButton("🔍 Search", callback_data="search")
    btn_delete = types.InlineKeyboardButton("🗑 Delete", callback_data="delete")
    markup.add(btn_upload, btn_search, btn_delete)
    bot.send_message(chat_id, "📌 Choose an action:", reply_markup=markup)

# ---------------- START ----------------
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    reset_user(chat_id)
    send_main_menu(chat_id)

# ---------------- RESET ----------------
def reset_user(chat_id):
    user_states[chat_id] = None
    user_data[chat_id] = {'links': {}, 'temp_url': None}

# ---------------- CALLBACK HANDLER ----------------
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id

    if call.data == "upload_file":
        user_states[chat_id] = 'awaiting_url'
        bot.send_message(chat_id, "📤 Send me the file URL (.txt, MediaFire, or direct link).")

    elif call.data == "search":
        if user_data.get(chat_id, {}).get('links'):
            choose_file_for_search(chat_id)
        else:
            bot.send_message(chat_id, "⚠️ No links added yet.")
            send_main_menu(chat_id)

    elif call.data == "delete":
        links = user_data.get(chat_id, {}).get('links', {})
        if not links:
            bot.send_message(chat_id, "⚠️ No links to delete.")
            send_main_menu(chat_id)
        else:
            markup = types.InlineKeyboardMarkup()
            for fname in links.keys():
                markup.add(types.InlineKeyboardButton(f"🗑 {fname}", callback_data=f"delete_file:{fname}"))
            bot.send_message(chat_id, "Select a link to delete:", reply_markup=markup)

    elif call.data.startswith("delete_file:"):
        fname = call.data.split("delete_file:")[1]
        links = user_data.get(chat_id, {}).get('links', {})
        if fname in links:
            del links[fname]
            bot.send_message(chat_id, f"✅ Link `{fname}` removed.", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, "⚠️ Link not found.")
        send_main_menu(chat_id)

    elif call.data.startswith("search_file:"):
        fname = call.data.split("search_file:")[1]
        if fname in user_data[chat_id]['links']:
            user_states[chat_id] = f"awaiting_domain:{fname}"
            bot.send_message(chat_id, f"🔍 Send me the domain to search in `{fname}`", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, "⚠️ Link not found.")
            send_main_menu(chat_id)

# ---------------- FILE UPLOAD ----------------
@bot.message_handler(func=lambda m: user_states.get(m.chat.id) == 'awaiting_url')
def handle_url(message):
    chat_id = message.chat.id
    url = message.text.strip()

    if not url.startswith(('http://', 'https://')):
        bot.send_message(chat_id, "⚠️ Invalid URL. Must start with http:// or https://")
        return

    user_data[chat_id]['temp_url'] = url
    user_states[chat_id] = 'awaiting_filename'
    bot.send_message(chat_id, "✏️ What name do you want to give this file?")

@bot.message_handler(func=lambda m: user_states.get(m.chat.id) == 'awaiting_filename')
def handle_filename(message):
    chat_id = message.chat.id
    file_name = message.text.strip()

    if not file_name:
        bot.send_message(chat_id, "⚠️ Name cannot be empty. Please enter a valid name.")
        return

    url = user_data[chat_id].pop('temp_url', None)
    if not url:
        bot.send_message(chat_id, "⚠️ No URL found. Please try again.")
        send_main_menu(chat_id)
        return

    user_data[chat_id]['links'][file_name] = url
    bot.send_message(chat_id, f"✅ Link saved as `{file_name}`", parse_mode="Markdown")
    send_main_menu(chat_id)

# ---------------- SEARCH ----------------
def choose_file_for_search(chat_id):
    markup = types.InlineKeyboardMarkup()
    for fname in user_data[chat_id]['links'].keys():
        markup.add(types.InlineKeyboardButton(f"🔍 {fname}", callback_data=f"search_file:{fname}"))
    bot.send_message(chat_id, "Select a link to search:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_states.get(m.chat.id, "").startswith('awaiting_domain:'))
def handle_domain_and_search(message):
    chat_id = message.chat.id
    state = user_states[chat_id]
    fname = state.split("awaiting_domain:")[1]
    url = user_data[chat_id]['links'].get(fname)

    if not url:
        bot.send_message(chat_id, "⚠️ Link not found.")
        send_main_menu(chat_id)
        return

    target_domain = message.text.strip()
    stream_search_with_live_progress(chat_id, url, target_domain, fname)

# ---------------- LINK TYPE HANDLING ----------------
def resolve_mediafire(url):
    try:
        page = requests.get(url, timeout=15)
        page.raise_for_status()
        match = re.search(r'href="(https://download[^"]+)"', page.text)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"MediaFire error: {e}")
    return None

# ---------------- STREAM SEARCH ----------------
def stream_search_with_live_progress(chat_id, url, target_domain, fname):
    try:
        # Resolve MediaFire links
        if "mediafire.com" in url:
            bot.send_message(chat_id, "🔍 Resolving MediaFire link...")
            direct_url = resolve_mediafire(url)
            if not direct_url:
                bot.send_message(chat_id, "⚠️ Could not resolve MediaFire link.")
                send_main_menu(chat_id)
                return
            url = direct_url

        progress_msg = bot.send_message(chat_id, "⏳ Starting search...")

        response = requests.get(url, stream=True, timeout=(10, 60))
        response.raise_for_status()

        total_bytes = int(response.headers.get('Content-Length', 0))
        bytes_read = 0
        lines_processed = 0

        found_lines_stream = io.BytesIO()
        found_lines_count = 0
        pattern = re.compile(r'\b' + re.escape(target_domain) + r'\b', re.IGNORECASE)

        last_percent = 0
        for chunk in response.iter_lines(decode_unicode=True):
            if not chunk:
                continue
            lines_processed += 1
            bytes_read += len(chunk.encode('utf-8')) + 1

            if pattern.search(chunk):
                found_lines_stream.write((chunk + "\n").encode("utf-8"))
                found_lines_count += 1

            if total_bytes > 0:
                percent = int((bytes_read / total_bytes) * 100)
                if percent >= last_percent + 5:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=progress_msg.message_id,
                        text=f"📊 {percent}% done — found {found_lines_count}"
                    )
                    last_percent = percent
            else:
                if lines_processed % 5000 == 0:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=progress_msg.message_id,
                        text=f"📊 Processed {lines_processed:,} lines — found {found_lines_count}"
                    )

        bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_msg.message_id,
            text=f"✅ Search complete — found {found_lines_count} matches"
        )

        if found_lines_count > 0:
            found_lines_stream.seek(0)
            bot.send_document(
                chat_id,
                found_lines_stream,
                visible_file_name=f"search_results_{target_domain}.txt",
                caption=f"✅ Found {found_lines_count} matches for `{target_domain}` in `{fname}`",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(chat_id, f"❌ No results for `{target_domain}` in `{fname}`", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Error during search: {e}")
    finally:
        send_main_menu(chat_id)

# ---------------- RUN BOT ----------------
if __name__ == '__main__':
    print("🤖 Bot is running...")
    bot.polling(none_stop=True)
