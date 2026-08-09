import os
import logging
import sqlite3
import threading
import requests
import hmac
import hashlib
import time
import traceback
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

DB_PATH = "users.db"
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    raise ValueError("❌ ENCRYPTION_KEY missing in .env")
cipher = Fernet(ENCRYPTION_KEY.encode())

# ------------------------- MULTI-LANGUAGE DICT -------------------------
LANG = {
    'en': {
        'welcome': "👋 Welcome, {name}! You are now registered.\nLanguage: {lang}\n\n📜 Please accept the Terms of Service with /accept",
        'already_registered': "🔐 You are already registered.",
        'terms_text': "📜 *Terms of Service*\n\nBy using this bot, you agree that:\n1. The bot charges an 8% fee on profits only.\n2. The fee is automatically withdrawn to the admin wallet.\n3. You are responsible for your own trading decisions.\n4. This bot is provided 'as is' – use at your own risk.\n\nTo accept, send: /accept",
        'terms_accepted': "✅ You have accepted the terms. You can now trade.",
        'accept_not_needed': "✅ You already accepted the terms.",
        'terms_required': "❌ Please accept the Terms of Service first with /accept.",
        'me': "📋 *Your Registration Info*\nID: `{id}`\nName: {name}\nLanguage: {lang}\nRegistered: {date}\nTerms Accepted: {terms}",
        'not_registered': "❌ You are not registered. Send /start first.",
        'ping': "🏓 Pong!",
        'lang_switched': "✅ Language switched to English.",
        'lang_current': "Current language: English.",
        'lang_usage': "Usage: /lang en  or  /lang fr",
        'lang_set': "✅ Language set to {lang}.",
        'connect_start': "🔑 Send me your **Binance API Key**.\n_(Your message will be deleted for security)_",
        'connect_secret': "🔒 Got it. Now send me your **Secret Key**.\n_(Your message will be deleted)_",
        'connect_success': "✅ Connected to Binance! Keys are encrypted and saved.\n\nYou can now use /balance, /price, etc.",
        'connect_invalid': "❌ Invalid API keys. Please start over with /connect.",
        'connect_only_binance': "❌ Only Binance is supported for now.",
        'connect_already': "🔐 You already have keys saved. Use /reconnect to update them.",
        'connect_testing': "⏳ Testing your keys with Binance...",
        'connect_fail': "❌ Binance returned an error: {}",
        'connect_usage': "Usage: /connect  (step‑by‑step wizard)",
        'balance': "💰 *Balance*\n{}",
        'balance_empty': "💰 Wallet is empty.",
        'balance_error': "❌ Could not fetch balance: {}",
        'price': "📈 *{}*: `${:.2f}`",
        'price_error': "❌ Could not fetch price for `{}`: {}",
        'no_keys': "❌ You haven't connected your Binance account. Use /connect first.",
        'buy_min': "❌ Minimum buy is $10.",
        'buy_max': "❌ Maximum buy is $1000 per order.",
        'buy_success': "✅ Bought {:.6f} {} @ ${:.2f} avg.",
        'buy_fill_zero': "⚠️ Order filled 0. Check balance / min notional.",
        'buy_failed': "❌ Buy failed: {}",
        'buy_usage': "❌ Usage: /buy <symbol> <amount>  e.g., /buy BTCUSDT 50",
        'sell_usage': "❌ Usage: /sell <symbol> <quantity>  e.g., /sell BTCUSDT 0.001",
        'sell_insufficient': "❌ Insufficient {}. You have {:.6f}.",
        'sell_success': "✅ Sold {:.6f} {} @ ${:.2f} avg.",
        'sell_zero': "⚠️ Sell filled 0.",
        'sell_failed': "❌ Sell failed: {}",
        'cooldown': "⏳ Please wait {} seconds between trades.",
        'daily_loss_exceeded': "❌ Daily loss limit of $50 exceeded. Trading paused until tomorrow.",
    },
    'fr': {
        'welcome': "👋 Bienvenue, {name}! Vous êtes enregistré.\nLangue: {lang}\n\n📜 Veuillez accepter les Conditions d'utilisation avec /accept",
        'already_registered': "🔐 Vous êtes déjà enregistré.",
        'terms_text': "📜 *Conditions d'utilisation*\n\nEn utilisant ce bot, vous acceptez que :\n1. Le bot prélève 8% de frais sur les bénéfices uniquement.\n2. Les frais sont automatiquement retirés vers le portefeuille de l'admin.\n3. Vous êtes seul responsable de vos décisions de trading.\n4. Ce bot est fourni 'en l'état' – utilisez-le à vos propres risques.\n\nPour accepter, envoyez : /accept",
        'terms_accepted': "✅ Vous avez accepté les conditions. Vous pouvez maintenant trader.",
        'accept_not_needed': "✅ Vous avez déjà accepté les conditions.",
        'terms_required': "❌ Veuillez d'abord accepter les Conditions d'utilisation avec /accept.",
        'me': "📋 *Vos infos d'enregistrement*\nID: `{id}`\nNom: {name}\nLangue: {lang}\nEnregistré le: {date}\nConditions acceptées: {terms}",
        'not_registered': "❌ Vous n'êtes pas enregistré. Envoyez /start d'abord.",
        'ping': "🏓 Pong!",
        'lang_switched': "✅ Langue changée en français.",
        'lang_current': "Langue actuelle : français.",
        'lang_usage': "Utilisation : /lang en  ou  /lang fr",
        'lang_set': "✅ Langue définie sur {lang}.",
        'connect_start': "🔑 Envoyez-moi votre **clé API Binance**.\n_(Votre message sera supprimé pour des raisons de sécurité)_",
        'connect_secret': "🔒 Reçu. Envoyez-moi maintenant votre **clé secrète**.\n_(Votre message sera supprimé)_",
        'connect_success': "✅ Connecté à Binance ! Vos clés sont chiffrées et sauvegardées.\n\nVous pouvez maintenant utiliser /balance, /price, etc.",
        'connect_invalid': "❌ Clés API invalides. Veuillez recommencer avec /connect.",
        'connect_only_binance': "❌ Seul Binance est pris en charge pour le moment.",
        'connect_already': "🔐 Vous avez déjà des clés sauvegardées. Utilisez /reconnect pour les mettre à jour.",
        'connect_testing': "⏳ Test de vos clés auprès de Binance...",
        'connect_fail': "❌ Binance a retourné une erreur : {}",
        'connect_usage': "Utilisation : /connect  (assistant étape par étape)",
        'balance': "💰 *Solde*\n{}",
        'balance_empty': "💰 Portefeuille vide.",
        'balance_error': "❌ Impossible de récupérer le solde : {}",
        'price': "📈 *{}*: `${:.2f}`",
        'price_error': "❌ Impossible de récupérer le prix pour `{}` : {}",
        'no_keys': "❌ Vous n'avez pas encore connecté votre compte Binance. Utilisez /connect d'abord.",
        'buy_min': "❌ L'achat minimum est de 10 $.",
        'buy_max': "❌ L'achat maximum est de 1000 $ par ordre.",
        'buy_success': "✅ Achat de {:.6f} {} à ${:.2f} en moyenne.",
        'buy_fill_zero': "⚠️ Ordre exécuté avec 0. Vérifiez votre solde / montant minimum.",
        'buy_failed': "❌ Échec de l'achat : {}",
        'buy_usage': "❌ Utilisation : /buy <symbole> <montant>  ex : /buy BTCUSDT 50",
        'sell_usage': "❌ Utilisation : /sell <symbole> <quantité>  ex : /sell BTCUSDT 0.001",
        'sell_insufficient': "❌ {0} insuffisant. Vous avez {1:.6f}.",
        'sell_success': "✅ Vente de {:.6f} {} à ${:.2f} en moyenne.",
        'sell_zero': "⚠️ Ordre de vente exécuté avec 0.",
        'sell_failed': "❌ Échec de la vente : {}",
        'cooldown': "⏳ Veuillez attendre {} secondes entre les transactions.",
        'daily_loss_exceeded': "❌ Limite de perte quotidienne de 50 $ dépassée. Trading suspendu jusqu'à demain.",
    }
}

def get_text(key, lang='en', **kwargs):
    msg = LANG.get(lang, LANG['en']).get(key, key)
    if kwargs:
        return msg.format(**kwargs)
    return msg

# ------------------------- DATABASE -------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            first_name TEXT,
            language TEXT,
            terms_accepted INTEGER DEFAULT 0,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            api_key TEXT,
            secret TEXT,
            daily_loss REAL DEFAULT 0,
            daily_loss_date TEXT
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("✅ Database initialized.")

def register_user(telegram_id, first_name, language):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT OR IGNORE INTO users (telegram_id, first_name, language)
        VALUES (?, ?, ?)
    ''', (telegram_id, first_name, language))
    conn.commit()
    conn.close()

def get_user(telegram_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'telegram_id': row[0],
            'first_name': row[1] if len(row) > 1 else None,
            'language': row[2] if len(row) > 2 else 'en',
            'terms_accepted': bool(row[3]) if len(row) > 3 else False,
            'registered_at': row[4] if len(row) > 4 else None,
            'api_key': row[5] if len(row) > 5 else None,
            'secret': row[6] if len(row) > 6 else None,
            'daily_loss': row[7] if len(row) > 7 else 0.0,
            'daily_loss_date': row[8] if len(row) > 8 else None,
        }
    return None

def set_user_language(telegram_id, lang):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET language = ? WHERE telegram_id = ?', (lang, telegram_id))
    conn.commit()
    conn.close()

def accept_terms(telegram_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET terms_accepted = 1 WHERE telegram_id = ?', (telegram_id,))
    conn.commit()
    conn.close()

def save_keys(telegram_id, api_key, secret):
    encrypted_api = cipher.encrypt(api_key.encode()).decode()
    encrypted_secret = cipher.encrypt(secret.encode()).decode()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET api_key = ?, secret = ? WHERE telegram_id = ?',
              (encrypted_api, encrypted_secret, telegram_id))
    conn.commit()
    conn.close()

def get_decrypted_keys(telegram_id):
    user = get_user(telegram_id)
    if not user or not user['api_key']:
        return None, None
    try:
        api_key = cipher.decrypt(user['api_key'].encode()).decode()
        secret = cipher.decrypt(user['secret'].encode()).decode()
        return api_key, secret
    except Exception as e:
        logging.error(f"Decryption error: {e}")
        return None, None

def reset_daily_loss(uid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET daily_loss = 0, daily_loss_date = ? WHERE telegram_id = ?',
              (datetime.now().isoformat(), uid))
    conn.commit()
    conn.close()

def update_daily_loss(uid, loss):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET daily_loss = daily_loss + ?, daily_loss_date = ? WHERE telegram_id = ?',
              (loss, datetime.now().isoformat(), uid))
    conn.commit()
    conn.close()

# ------------------------- BINANCE API HELPERS (with debug logs) -------------------------
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

    # DEBUG: log the first few chars of the secret and the full URL
    logging.info(f"🔑 Secret starts with: {secret[:4]}...")
    logging.info(f"📡 Full URL: {full_url[:200]}...")

    try:
        if method == 'GET':
            resp = requests.get(full_url, headers=headers, timeout=5)
        else:
            resp = requests.post(full_url, headers=headers, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logging.error("❌ Binance request timed out after 5 seconds.")
        raise
    except Exception as e:
        logging.error(f"❌ Binance request error: {e}")
        raise

def test_binance_keys(api_key, secret):
    try:
        binance_request(api_key, secret, '/api/v3/account')
        return True, "Valid."
    except requests.exceptions.Timeout:
        return False, "⏱️ Timeout: Binance API did not respond within 5 seconds. Check your internet or VPN."
    except requests.exceptions.ConnectionError:
        return False, "🌐 Connection error: Cannot reach Binance. Check your network."
    except Exception as e:
        logging.error(f"❌ Binance test failed: {e}")
        logging.error(traceback.format_exc())
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
    resp = requests.get(f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}', timeout=5)
    resp.raise_for_status()
    return float(resp.json()['price'])

def get_exchange_info(symbol):
    resp = requests.get(f'https://api.binance.com/api/v3/exchangeInfo?symbol={symbol}', timeout=5)
    resp.raise_for_status()
    for s in resp.json()['symbols']:
        if s['symbol'] == symbol:
            return s
    return None

def resolve_symbol(text_symbol):
    text_symbol = text_symbol.upper()
    if get_exchange_info(text_symbol):
        return text_symbol
    test = f"{text_symbol}USDT"
    if get_exchange_info(test):
        return test
    test = f"{text_symbol}BUSD"
    if get_exchange_info(test):
        return test
    return None

# ------------------------- FLASK DASHBOARD (with /ip and /outip) -------------------------
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    count = c.fetchone()[0]
    conn.close()
    return jsonify({"status": "Layer 6", "users": count, "message": "Trading active"})

@flask_app.route('/ip')
def get_ip():
    try:
        ip = requests.get('https://api.ipify.org', timeout=5).text
        return jsonify({"ip": ip})
    except Exception as e:
        return jsonify({"error": str(e)})

@flask_app.route('/outip')
def outip():
    try:
        ip = requests.get('https://api.ipify.org', timeout=5).text
        return jsonify({"outbound_ip": ip})
    except Exception as e:
        return jsonify({"error": str(e)})

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

# ------------------------- TELEGRAM DECORATORS -------------------------
def terms_required(func):
    async def wrapper(update, context, *args, **kwargs):
        uid = update.effective_user.id
        user = get_user(uid)
        if not user:
            lang = update.effective_user.language_code or 'en'
            await update.message.reply_text(get_text('not_registered', lang))
            return
        if not user['terms_accepted']:
            lang = user['language']
            await update.message.reply_text(get_text('terms_required', lang))
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def keys_required(func):
    async def wrapper(update, context, *args, **kwargs):
        uid = update.effective_user.id
        user = get_user(uid)
        if not user:
            lang = update.effective_user.language_code or 'en'
            await update.message.reply_text(get_text('not_registered', lang))
            return
        if not user['api_key']:
            lang = user.get('language', 'en')
            await update.message.reply_text(get_text('no_keys', lang))
            return
        api_key, secret = get_decrypted_keys(uid)
        if not api_key:
            lang = user.get('language', 'en')
            await update.message.reply_text("❌ Could not decrypt your keys. Please reconnect with /connect.")
            return
        return await func(update, context, user, api_key, secret, *args, **kwargs)
    return wrapper

# ------------------------- TELEGRAM HANDLERS -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    first_name = user.first_name or "User"
    lang = user.language_code or "en"

    existing = get_user(uid)
    if existing:
        lang = existing['language']
        await update.message.reply_text(get_text('already_registered', lang))
        if not existing['terms_accepted']:
            await update.message.reply_text(get_text('terms_text', lang), parse_mode='Markdown')
        return

    register_user(uid, first_name, lang)
    await update.message.reply_text(
        get_text('welcome', lang, name=first_name, lang=lang)
    )
    await update.message.reply_text(get_text('terms_text', lang), parse_mode='Markdown')

async def accept_terms_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        lang = update.effective_user.language_code or 'en'
        await update.message.reply_text(get_text('not_registered', lang))
        return
    lang = user['language']
    if user['terms_accepted']:
        await update.message.reply_text(get_text('accept_not_needed', lang))
        return
    accept_terms(uid)
    await update.message.reply_text(get_text('terms_accepted', lang))

async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data = get_user(uid)
    if not user_data:
        lang = update.effective_user.language_code or 'en'
        await update.message.reply_text(get_text('not_registered', lang))
        return
    lang = user_data['language']
    terms = "✅ Yes" if user_data['terms_accepted'] else "❌ No"
    await update.message.reply_text(
        get_text('me', lang,
                 id=user_data['telegram_id'],
                 name=user_data['first_name'],
                 date=user_data['registered_at'],
                 terms=terms),
        parse_mode='Markdown'
    )

@terms_required
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data = get_user(uid)
    lang = user_data['language'] if user_data else (update.effective_user.language_code or 'en')
    await update.message.reply_text(get_text('ping', lang))

async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    if not args or args[0].lower() not in ['en', 'fr']:
        user_data = get_user(uid)
        lang = user_data['language'] if user_data else 'en'
        await update.message.reply_text(get_text('lang_current', lang) + "\n" + get_text('lang_usage', lang))
        return

    new_lang = args[0].lower()
    set_user_language(uid, new_lang)
    await update.message.reply_text(get_text('lang_set', new_lang))

# ------------------------- CONNECT WIZARD -------------------------
async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        lang = update.effective_user.language_code or 'en'
        await update.message.reply_text(get_text('not_registered', lang))
        return
    lang = user['language']

    if user.get('api_key'):
        await update.message.reply_text(get_text('connect_already', lang))
    context.user_data['connect_state'] = 'awaiting_api'
    await update.message.reply_text(get_text('connect_start', lang))

async def handle_connect_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        return
    lang = user['language']
    state = context.user_data.get('connect_state')
    if not state:
        return

    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except:
        pass

    if state == 'awaiting_api':
        context.user_data['temp_api_key'] = update.message.text.strip()
        context.user_data['connect_state'] = 'awaiting_secret'
        await update.message.reply_text(get_text('connect_secret', lang))

    elif state == 'awaiting_secret':
        api_key = context.user_data.get('temp_api_key')
        secret = update.message.text.strip()
        if not api_key or not secret:
            context.user_data.clear()
            await update.message.reply_text(get_text('connect_invalid', lang))
            return

        await update.message.reply_text(get_text('connect_testing', lang))
        try:
            ok, msg = test_binance_keys(api_key, secret)
        except Exception as e:
            logging.error(f"❌ Unexpected error in connect wizard: {e}")
            logging.error(traceback.format_exc())
            context.user_data.clear()
            await update.message.reply_text(f"❌ Unexpected error: {e}")
            return

        if not ok:
            context.user_data.clear()
            await update.message.reply_text(get_text('connect_fail', lang).format(msg))
            return

        save_keys(uid, api_key, secret)
        context.user_data.clear()
        await update.message.reply_text(get_text('connect_success', lang))

# ------------------------- BALANCE & PRICE -------------------------
@terms_required
@keys_required
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE, user, api_key, secret):
    lang = user.get('language', 'en')
    try:
        balances = get_balance(api_key, secret)
        if not balances:
            await update.message.reply_text(get_text('balance_empty', lang))
            return
        lines = [f"• {k}: {v:.6f}" for k, v in list(balances.items())[:10]]
        reply = get_text('balance', lang).format("\n".join(lines))
        await update.message.reply_text(reply, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"❌ Balance error: {e}")
        logging.error(traceback.format_exc())
        await update.message.reply_text(get_text('balance_error', lang).format(str(e)))

@terms_required
@keys_required
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE, user, api_key, secret):
    lang = user.get('language', 'en')
    args = context.args
    if not args:
        await update.message.reply_text("❌ Usage: /price <symbol>  e.g., /price BTCUSDT")
        return
    symbol = args[0].upper()
    resolved = resolve_symbol(symbol)
    if not resolved:
        await update.message.reply_text(f"❌ Symbol '{symbol}' not found.")
        return
    try:
        price = get_price(resolved)
        await update.message.reply_text(get_text('price', lang).format(resolved, price), parse_mode='Markdown')
    except Exception as e:
        logging.error(f"❌ Price error: {e}")
        logging.error(traceback.format_exc())
        await update.message.reply_text(get_text('price_error', lang).format(symbol, str(e)))

# ------------------------- TRADING (Layer 6) -------------------------
@terms_required
@keys_required
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE, user, api_key, secret):
    lang = user.get('language', 'en')
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(get_text('buy_usage', lang))
        return

    symbol_raw = args[0].upper()
    try:
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text(get_text('buy_usage', lang))
        return

    symbol = resolve_symbol(symbol_raw)
    if not symbol:
        await update.message.reply_text(f"❌ Symbol '{symbol_raw}' not found.")
        return

    if amount < 10:
        await update.message.reply_text(get_text('buy_min', lang))
        return
    if amount > 1000:
        await update.message.reply_text(get_text('buy_max', lang))
        return

    last_trade = context.user_data.get('last_trade_time', 0)
    if time.time() - last_trade < 10:
        remaining = int(10 - (time.time() - last_trade))
        await update.message.reply_text(get_text('cooldown', lang).format(remaining))
        return

    today = datetime.now().isoformat()[:10]
    if user.get('daily_loss_date'):
        if user['daily_loss_date'][:10] != today:
            reset_daily_loss(user['telegram_id'])
            user['daily_loss'] = 0.0
    if abs(user['daily_loss']) >= 50:
        await update.message.reply_text(get_text('daily_loss_exceeded', lang))
        return

    try:
        order = binance_request(api_key, secret, '/api/v3/order',
                                {'symbol': symbol, 'side': 'BUY', 'type': 'MARKET', 'quoteOrderQty': amount},
                                method='POST')
        qty = float(order.get('executedQty', 0))
        if qty > 0:
            avg_price = float(order.get('cummulativeQuoteQty', 0)) / qty
            context.user_data['last_trade_time'] = time.time()
            await update.message.reply_text(get_text('buy_success', lang).format(qty, symbol, avg_price))
        else:
            await update.message.reply_text(get_text('buy_fill_zero', lang))
    except Exception as e:
        logging.error(f"❌ Buy error: {e}")
        logging.error(traceback.format_exc())
        await update.message.reply_text(get_text('buy_failed', lang).format(str(e)))

@terms_required
@keys_required
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE, user, api_key, secret):
    lang = user.get('language', 'en')
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(get_text('sell_usage', lang))
        return

    symbol_raw = args[0].upper()
    try:
        qty = float(args[1])
    except ValueError:
        await update.message.reply_text(get_text('sell_usage', lang))
        return

    symbol = resolve_symbol(symbol_raw)
    if not symbol:
        await update.message.reply_text(f"❌ Symbol '{symbol_raw}' not found.")
        return

    last_trade = context.user_data.get('last_trade_time', 0)
    if time.time() - last_trade < 10:
        remaining = int(10 - (time.time() - last_trade))
        await update.message.reply_text(get_text('cooldown', lang).format(remaining))
        return

    balances = get_balance(api_key, secret)
    base_asset = symbol.replace('USDT', '').replace('BUSD', '').replace('BTC', '').replace('ETH', '').replace('BNB', '')
    if balances.get(base_asset, 0) < qty:
        await update.message.reply_text(get_text('sell_insufficient', lang).format(base_asset, balances.get(base_asset, 0)))
        return

    try:
        order = binance_request(api_key, secret, '/api/v3/order',
                                {'symbol': symbol, 'side': 'SELL', 'type': 'MARKET', 'quantity': qty},
                                method='POST')
        filled = float(order.get('executedQty', 0))
        if filled > 0:
            avg_price = float(order.get('cummulativeQuoteQty', 0)) / filled
            context.user_data['last_trade_time'] = time.time()
            await update.message.reply_text(get_text('sell_success', lang).format(filled, symbol, avg_price))
        else:
            await update.message.reply_text(get_text('sell_zero', lang))
    except Exception as e:
        logging.error(f"❌ Sell error: {e}")
        logging.error(traceback.format_exc())
        await update.message.reply_text(get_text('sell_failed', lang).format(str(e)))

# ------------------------- ERROR HANDLER -------------------------
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"❌ Update {update} caused error: {context.error}")
    logging.error(traceback.format_exc())
    if update and update.effective_message:
        await update.effective_message.reply_text("⚠️ An unexpected error occurred. Please try again or contact support.")

# ------------------------- MAIN -------------------------
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        logging.error("❌ TELEGRAM_TOKEN missing.")
        return

    app = (
        Application.builder()
        .token(token)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(30)
        .pool_timeout(60)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("accept", accept_terms_handler))
    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("lang", lang_command))
    app.add_handler(CommandHandler("connect", connect))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("sell", sell))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_connect_input))

    # Add error handler
    app.add_error_handler(error_handler)

    logging.info("✅ Layer 6 started. Trading (Buy/Sell) active.")
    app.run_polling()

if __name__ == "__main__":
    main()
