import os
import logging
import sqlite3
import hmac
import hashlib
import time
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from cryptography.fernet import Fernet

load_dotenv()
logging.basicConfig(level=logging.INFO)

# --- Encryption ---
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    raise ValueError("❌ ENCRYPTION_KEY missing in .env")
cipher = Fernet(ENCRYPTION_KEY.encode())

# --- Admin ID (safe) ---
admin_str = os.getenv('ADMIN_TELEGRAM_ID')
if admin_str is None:
    print("⚠️ ADMIN_TELEGRAM_ID not set. Admin commands disabled.")
    ADMIN_ID = None
else:
    try:
        ADMIN_ID = int(admin_str)
    except ValueError:
        print("⚠️ ADMIN_TELEGRAM_ID is not a number. Admin commands disabled.")
        ADMIN_ID = None

# --- Database ---
DB_PATH = "users.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            exchange TEXT,
            api_key TEXT,
            secret TEXT,
            total_profit REAL DEFAULT 0,
            fee_paid REAL DEFAULT 0,
            trading_enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def encrypt(text):
    return cipher.encrypt(text.encode()).decode()

def decrypt(text):
    return cipher.decrypt(text.encode()).decode()

def get_user(telegram_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'telegram_id': row[0],
            'exchange': row[1],
            'api_key': decrypt(row[2]),
            'secret': decrypt(row[3]),
            'total_profit': row[4],
            'fee_paid': row[5],
            'trading_enabled': bool(row[6])
        }
    return None

def save_user(telegram_id, exchange, api_key, secret):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO users (telegram_id, exchange, api_key, secret)
        VALUES (?, ?, ?, ?)
    ''', (telegram_id, exchange, encrypt(api_key), encrypt(secret)))
    conn.commit()
    conn.close()

def update_profit(telegram_id, trade_pnl):
    """Update total_profit and fee_paid (8% fee)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET total_profit = total_profit + ?, fee_paid = fee_paid + ? WHERE telegram_id = ?',
              (trade_pnl, trade_pnl * 0.08, telegram_id))
    conn.commit()
    conn.close()

# --- Binance API ---
def binance_request(api_key, secret, endpoint, params=None, method='GET'):
    base_url = 'https://api.binance.com'
    url = base_url + endpoint
    timestamp = int(time.time() * 1000)
    if params is None:
        params = {}
    params['timestamp'] = timestamp
    params['recvWindow'] = 5000
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    headers = {'X-MBX-APIKEY': api_key}
    full_url = f"{url}?{query_string}&signature={signature}"
    if method == 'GET':
        resp = requests.get(full_url, headers=headers, timeout=30)
    else:
        resp = requests.post(full_url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()

def test_binance_keys(api_key, secret):
    try:
        binance_request(api_key, secret, '/api/v3/account')
        return True, "Keys are valid."
    except Exception as e:
        return False, str(e)

def get_balance(api_key, secret):
    data = binance_request(api_key, secret, '/api/v3/account')
    balances = {}
    for item in data['balances']:
        free = float(item['free'])
        locked = float(item['locked'])
        if free + locked > 0:
            balances[item['asset']] = free + locked
    return balances

def get_price(symbol='BTCUSDT'):
    resp = requests.get(f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}', timeout=30)
    resp.raise_for_status()
    return float(resp.json()['price'])

# --- Telegram Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if user:
        await update.message.reply_text("🔐 You're already registered. Send /connect to update keys.")
    else:
        await update.message.reply_text(
            "👋 Welcome to MoussaBlvckLionBot.\n\n"
            "To start trading, send:\n"
            "/connect Binance YOUR_API_KEY YOUR_SECRET\n\n"
            "⚠️ Your keys are encrypted before storage."
        )

async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    if len(args) != 3:
        await update.message.reply_text("❌ Usage: /connect <exchange> <api_key> <secret>")
        return
    exchange, api_key, secret = args[0], args[1], args[2]
    if exchange.lower() != "binance":
        await update.message.reply_text("❌ Only Binance is supported for now.")
        return
    ok, msg = test_binance_keys(api_key, secret)
    if not ok:
        await update.message.reply_text(f"❌ Invalid API keys: {msg[:100]}")
        return
    save_user(uid, exchange, api_key, secret)
    await update.message.reply_text(f"✅ Connected to {exchange}. Keys encrypted and saved.\n{msg}")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ You're not registered. Send /start first.")
        return
    if not user['trading_enabled']:
        await update.message.reply_text("⛔ Your account is paused. Contact admin.")
        return
    try:
        balances = get_balance(user['api_key'], user['secret'])
        if not balances:
            reply = "💰 Wallet is empty."
        else:
            reply = "💰 Balance:\n" + "\n".join([f"{k}: {v}" for k, v in list(balances.items())[:5]])
        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    words = text.split()
    symbol = "BTCUSDT"
    for w in words:
        clean = w.upper().replace('/USDT', '').replace('USDT', '')
        if clean in ["BTC", "ETH", "SOL", "TON", "LTC"]:
            symbol = f"{clean}USDT"
            break
    try:
        price = get_price(symbol)
        await update.message.reply_text(f"📈 {symbol}: ${price:.2f}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ You're not registered.")
        return
    if not user['trading_enabled']:
        await update.message.reply_text("⛔ Account paused.")
        return
    text = update.message.text.lower()
    words = text.split()
    try:
        amount = None
        symbol = "BTCUSDT"
        for w in words:
            if w.upper() in ["BTC", "ETH", "SOL"]:
                symbol = f"{w.upper()}USDT"
            else:
                try:
                    amount = float(w)
                except ValueError:
                    pass
        if amount is None:
            try:
                amount = float(words[-1])
            except ValueError:
                await update.message.reply_text("❌ Could not find amount. Use like: buy BTC 50")
                return
        price = get_price(symbol)
        crypto_qty = amount / price
        # --- Uncomment to execute real order ---
        # binance_request(user['api_key'], user['secret'], '/api/v3/order',
        #                 {'symbol': symbol, 'side': 'BUY', 'type': 'MARKET', 'quantity': crypto_qty},
        #                 method='POST')
        # After order, call update_profit(uid, trade_pnl) when trade is closed.
        await update.message.reply_text(
            f"🧠 Buy {symbol} for ${amount} = {crypto_qty:.6f} units.\n"
            f"⚠️ Simulated only. Uncomment order line in code to execute."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

async def bonuses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎁 Bonus Hunter: coming soon.\n"
        "We'll scan Binance Earn and promotions automatically."
    )

# --- Admin ---
async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID is None or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT telegram_id, exchange, total_profit, fee_paid, trading_enabled FROM users')
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No users yet.")
        return
    reply = "📋 *Registered Users:*\n\n"
    for row in rows:
        reply += f"ID: {row[0]}\nExchange: {row[1]}\nProfit: ${row[2]:.2f}\nFee Paid (8%): ${row[3]:.2f}\nEnabled: {'✅' if row[4] else '❌'}\n---\n"
    await update.message.reply_text(reply, parse_mode='Markdown')

# --- Main ---
def main():
    init_db()
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        print("❌ TELEGRAM_TOKEN missing in .env")
        return

    app = (
        Application.builder()
        .token(token)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(15)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("connect", connect))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("bonuses", bonuses))
    app.add_handler(CommandHandler("users", users_list))

    print("✅ MoussaBlvckLionBot is live. Keys are encrypted.")
    print("ℹ️  Admin commands available if ADMIN_TELEGRAM_ID is set.")
    app.run_polling()

if __name__ == "__main__":
    main()
