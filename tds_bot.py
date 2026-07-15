import telebot
import requests
import json
import os
import threading
import time
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

TOKEN = os.getenv("TDS_BOT_TOKEN", "8446383056:AAHQAuUHXbC2AUPEHAg3AtB54rmeLm75O6Q")
CHECK_INTERVAL = 300
ADMIN_ID = 7640756072
PORT = int(os.getenv("PORT", 10000))
accounts_data = {}

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a):
        pass

def run_http():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logging.info(f"HTTP server on port {PORT}")
    server.serve_forever()

bot = telebot.TeleBot(TOKEN)
accounts_lock = threading.Lock()

def is_admin(uid):
    return uid == ADMIN_ID

def login_tds(username, password):
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    try:
        r = sess.post("https://traodoisub.com/scr/login.php", data={"username": username, "password": password}, timeout=15)
        data = r.json()
        if data.get("success"):
            r2 = sess.get("https://traodoisub.com/scr/user.php", timeout=15)
            return sess, r2.json()
    except Exception:
        pass
    return None, None

def check_balance(username, password):
    sess, data = login_tds(username, password)
    if sess is None:
        return None, "Login failed"
    xu = int(data.get("xu", 0))
    return xu, None

def add_single(cid, user, pwd):
    xu, err = check_balance(user, pwd)
    if err:
        return f"\u274c `{user}`: login failed"
    with accounts_lock:
        if cid not in accounts_data:
            accounts_data[cid] = {}
        accounts_data[cid][user] = {"password": pwd, "last_xu": xu}
    return f"\u2705 `{user}` - {xu} xu"

@bot.message_handler(commands=["start", "help"])
def send_help(message):
    if not is_admin(message.from_user.id):
        return
    text = (
        "\U0001F916 *TDS Balance Monitor Bot*\n\n"
        "Commands:\n"
        "/add <user> <pass> - Add one account\n"
        "/add user1 pass1 | user2 pass2 - Add multiple accounts (separate by |)\n"
        "/addlist (reply to a list or paste below) - Bulk add, each line: user|pass\n"
        "/del <user> - Remove an account\n"
        "/list - List all tracked accounts & balances\n"
        "/check - Force check all accounts now\n"
        "/interval <sec> - Set check interval (min 60)\n"
        "/help - This help"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=["add"])
def add_account(message):
    if not is_admin(message.from_user.id):
        return
    raw = message.text[len("/add "):].strip()
    if not raw:
        bot.reply_to(message, "Usage: /add <user> <pass> or /add user1 pass1 | user2 pass2")
        return
    cid = str(message.chat.id)
    parts = [p.strip() for p in raw.split("|")]
    results = []
    for entry in parts:
        tokens = entry.split()
        if len(tokens) >= 2:
            user, pwd = tokens[0], tokens[1]
            results.append(add_single(cid, user, pwd))
        else:
            results.append(f"\u26A0 Invalid entry: `{entry}`")
    bot.reply_to(message, "\n".join(results), parse_mode="Markdown")

@bot.message_handler(commands=["addlist"])
def add_list(message):
    if not is_admin(message.from_user.id):
        return
    cid = str(message.chat.id)
    text = message.text[len("/addlist "):].strip()
    if not text and message.reply_to_message:
        text = message.reply_to_message.text or message.reply_to_message.caption or ""
    if not text:
        bot.reply_to(message, "Paste list or reply to a message with:\nuser1|pass1\nuser2|pass2")
        return
    lines = text.strip().splitlines()
    results = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("/"):
            continue
        if "|" in line:
            user, pwd = line.split("|", 1)
            results.append(add_single(cid, user.strip(), pwd.strip()))
        else:
            tokens = line.split()
            if len(tokens) >= 2:
                results.append(add_single(cid, tokens[0], tokens[1]))
    if not results:
        bot.reply_to(message, "No valid accounts found.")
        return
    bot.reply_to(message, "\n".join(results), parse_mode="Markdown")

@bot.message_handler(commands=["del"])
def del_account(message):
    if not is_admin(message.from_user.id):
        return
    raw = message.text[len("/del "):].strip()
    if not raw:
        bot.reply_to(message, "Usage: /del <username>")
        return
    cid = str(message.chat.id)
    to_del = [u.strip() for u in raw.replace("|", " ").split()]
    results = []
    with accounts_lock:
        for user in to_del:
            if cid in accounts_data and user in accounts_data[cid]:
                del accounts_data[cid][user]
                if not accounts_data[cid]:
                    del accounts_data[cid]
                results.append(f"\u2705 Removed `{user}`")
            else:
                results.append(f"\u274c `{user}` not found")
    bot.reply_to(message, "\n".join(results), parse_mode="Markdown")

@bot.message_handler(commands=["list"])
def list_accounts(message):
    if not is_admin(message.from_user.id):
        return
    cid = str(message.chat.id)
    with accounts_lock:
        if cid not in accounts_data or not accounts_data[cid]:
            bot.reply_to(message, "No accounts tracked. Use /add to add one.")
            return
        lines = [f"*Your tracked accounts:*"]
        for user, info in accounts_data[cid].items():
            xu = info.get("last_xu", "?")
            lines.append(f"\U0001F464 `{user}` - {xu} xu")
        bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=["check"])
def force_check(message):
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(message, "\u23F3 Checking all accounts...")
    results = check_all()
    if results:
        for cid, alerts in results.items():
            for alert in alerts:
                try:
                    bot.send_message(cid, alert, parse_mode="Markdown")
                except:
                    pass

@bot.message_handler(commands=["interval"])
def set_interval(message):
    if not is_admin(message.from_user.id):
        return
    global CHECK_INTERVAL
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, f"Current interval: {CHECK_INTERVAL}s\nUsage: /interval <seconds> (min 60)")
        return
    try:
        val = int(parts[1])
        if val < 60:
            bot.reply_to(message, "Minimum interval is 60 seconds")
            return
        CHECK_INTERVAL = val
        bot.reply_to(message, f"Interval set to {CHECK_INTERVAL}s")
    except:
        bot.reply_to(message, "Invalid number")

def check_all():
    with accounts_lock:
        accs = {k: dict(v) for k, v in accounts_data.items()}
    results = {}
    for cid, accounts in accs.items():
        for user, info in accounts.items():
            pwd = info["password"]
            last_xu = info.get("last_xu", 0)
            xu, err = check_balance(user, pwd)
            time.sleep(5)
            if err:
                logging.warning(f"Check failed for {user}: {err}")
                continue
            with accounts_lock:
                if cid in accounts_data and user in accounts_data[cid]:
                    accounts_data[cid][user]["last_xu"] = xu
            if xu < last_xu:
                drop = last_xu - xu
                alert = (
                    f"\U0001F525 TDS \u0111ang qu\xe9t b\xe1n mau!\n"
                    f"\U0001F464 {user}, \u2747 {last_xu:,}, \u26A0 {xu:,}, \U0001F4A5 -{drop:,}"
                )
                results.setdefault(cid, []).append(alert)
                logging.info(f"ALERT: {user} dropped from {last_xu} to {xu} (-{drop})")
    return results

def periodic_check():
    while True:
        try:
            results = check_all()
            for cid, alerts in results.items():
                for alert in alerts:
                    try:
                        bot.send_message(cid, alert, parse_mode="Markdown")
                    except:
                        pass
        except Exception as e:
            logging.error(f"Check error: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    threading.Thread(target=run_http, daemon=True).start()
    threading.Thread(target=periodic_check, daemon=True).start()
    logging.info("Bot started")
    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(skip_pending=True, allowed_updates=["message"])
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(10)
