import telebot
import requests
import os
import re
import sys
import io
import tempfile

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    print("Error: BOT_TOKEN environment variable is not set.")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

user_states = {}
user_data = {}

@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    reset_user(chat_id)
    bot.send_message(
        chat_id,
        "👋 Welcome!\n\n"
        "Please send me the URL of the large file you want to search."
    )

@bot.message_handler(commands=['reset'])
def handle_reset(message):
    chat_id = message.chat.id
    reset_user(chat_id)
    bot.send_message(chat_id, "🔄 Session reset! Send me a new file URL.")

def reset_user(chat_id):
    if chat_id in user_data and 'file_path' in user_data[chat_id]:
        try:
            os.remove(user_data[chat_id]['file_path'])
        except Exception:
            pass
    user_states[chat_id] = 'awaiting_url'
    user_data[chat_id] = {}

@bot.message_handler(func=lambda m: user_states.get(m.chat.id) == 'awaiting_url')
def handle_url(message):
    chat_id = message.chat.id
    url = message.text.strip()

    if not url.startswith(('http://', 'https://')):
        bot.send_message(chat_id, "⚠️ Invalid URL. Must start with http:// or https://")
        return

    try:
        bot.send_message(chat_id, "⏳ Downloading file... Please wait.")
        response = requests.get(url, stream=True, timeout=600)
        response.raise_for_status()

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        for chunk in response.iter_content(chunk_size=1024*1024):
            if chunk:
                temp_file.write(chunk)
        temp_file.close()

        # Store file path
        user_data[chat_id]['file_path'] = temp_file.name

        # Load file into memory (indexing)
        with open(temp_file.name, "r", encoding="utf-8", errors="ignore") as f:
            user_data[chat_id]['lines'] = f.readlines()

        user_states[chat_id] = 'awaiting_domain'
        bot.send_message(chat_id, "✅ File downloaded and indexed!\n\n"
                                  "🔍 Now send me a domain to search.")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Error downloading file: {e}")

def make_progress_bar(percent, size=20):
    """Creates a visual progress bar like ▓▓▓░░░ 50%"""
    filled = int(size * percent / 100)
    bar = "▓" * filled + "░" * (size - filled)
    return f"[{bar}] {percent}%"

@bot.message_handler(func=lambda m: user_states.get(m.chat.id) == 'awaiting_domain')
def handle_domain_and_search(message):
    chat_id = message.chat.id
    target_domain = message.text.strip()
    lines = user_data[chat_id].get('lines')

    if not lines:
        bot.send_message(chat_id, "⚠️ No file loaded. Use /start again.")
        return

    total_lines = len(lines)
    bot.send_message(chat_id, f"🔍 Searching for `{target_domain}` in {total_lines:,} lines...\n",
                     parse_mode="Markdown")

    found_lines_stream = io.BytesIO()
    found_lines_count = 0

    try:
        # Progress updates every 10%
        step = max(1, total_lines // 10)
        for i, line in enumerate(lines, start=1):
            if re.search(r'\b' + re.escape(target_domain) + r'\b', line, re.IGNORECASE):
                found_lines_stream.write(line.encode("utf-8"))
                found_lines_count += 1

            if i % step == 0:
                percent = int(i / total_lines * 100)
                progress_bar = make_progress_bar(percent)
                bot.send_message(chat_id, f"{progress_bar}\n"
                                          f"📊 Found so far: {found_lines_count}")

        if found_lines_count > 0:
            bot.send_message(chat_id, f"✅ Search complete!\n📄 Total matches: *{found_lines_count}*",
                             parse_mode="Markdown")

            found_lines_stream.seek(0)
            bot.send_document(
                chat_id,
                found_lines_stream,
                visible_file_name=f"search_results_{target_domain}.txt",
                caption=f"📄 Results for *{target_domain}*\n\n👉 You can send another domain.",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(chat_id, f"❌ No results for `{target_domain}`.\nTry another domain.",
                             parse_mode="Markdown")

        user_states[chat_id] = 'awaiting_domain'

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Error while searching: {e}")

    finally:
        found_lines_stream.close()

# Start the bot
if __name__ == '__main__':
    print("🤖 Bot is running...")
    bot.polling(none_stop=True)
