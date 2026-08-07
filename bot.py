import os
import logging
import sqlite3
import hmac
import hashlib
import time
import requests
import re
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from cryptography.fernet import Fernet
from flask import Flask, jsonify
from functools import wraps

load_dotenv()
logging.basicConfig(level=logging.INFO)

ADMIN_WALLET = os.getenv('ADMIN_WALLET')
ADMIN_ID = int(os.getenv('ADMIN_TELEGRAM_ID', 0)) if os.getenv('ADMIN_TELEGRAM_ID') else None
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY: raise ValueError("ENCRYPTION_KEY missing")
cipher = Fernet(ENCRYPTION_KEY.encode())
DB_PATH = "users.db"
db_lock = threading.Lock()

LANG = {
    'en': {
        'welcome': "👋 Welcome to MoussaBlvckLion Bot – your DeFi assistant.\nSend /connect to link your Binance account.",
        'already_registered': "🔐 You're already registered. Use /connect to update keys.",
        'connect_start': "🔑 Send me your **Binance API Key**.\n_(Your message will be deleted for security)_",
        'connect_secret': "🔒 Got it. Now send me your **Secret Key**.\n_(Your message will be deleted)_",
        'connect_success': "✅ Connected to Binance! Initial Net Worth: ${:.2f}",
        'connect_invalid': "❌ Invalid keys: {}. Please start over with /connect.",
        'connect_only_binance': "❌ Only Binance is supported for now.",
        'balance': "💰 Balance:\n{}",
        'balance_empty': "💰 Wallet is empty.",
        'networth': "📊 NW: ${:.2f}\nHWM: ${:.2f}\nUnrealized: ${:.2f}",
        'price': "📈 {}: ${:.2f}",
        'price_error': "❌ Symbol '{}' not found. Try BTCUSDT, ETHBUSD, etc.",
        'buy_min': "❌ Minimum spend is $10 (or equivalent).",
        'buy_max': "❌ Maximum spend is $1000 (safety limit).",
        'buy_success': "✅ Bought {:.6f} {} @ ${:.2f}",
        'buy_fill_zero': "⚠️ Order filled 0. Check balance / min notional.",
        'buy_failed': "❌ Buy failed: {}",
        'buy_usage': "❌ Usage: /buy <symbol> <amount> (e.g., /buy BTCUSDT 50)",
        'sell_usage': "❌ Usage: /sell <symbol> <quantity> (e.g., /sell BTCUSDT 0.001)",
        'sell_insufficient': "❌ Insufficient {}. Balance: {}",
        'sell_success': "✅ Sold {:.6f} {} @ ${:.2f}",
        'sell_zero': "⚠️ Sell filled 0.",
        'sell_failed': "❌ Sell failed: {}",
        'sell_fee_prompt': "💰 Profit: ${:.2f}. Fee: ${:.2f}.\nReply YES to auto‑withdraw, NO to decline.",
        'sell_no_fee': "✅ Sold {:.6f} {} @ ${:.2f}. No fee (profit < $1).",
        'fee_yes': "✅ Fee ${:.2f} sent! {}",
        'fee_no': "❌ Fee declined. Account PAUSED.",
        'fee_withdraw_fail': "❌ Withdrawal failed: {}\nAccount PAUSED.",
        'fee_admin_wallet_missing': "❌ Admin wallet not set.",
        'fee_pending': "⛔ Please resolve the pending fee (YES/NO) first.",
        'fee_unknown': "Reply YES or NO.",
        'bonus_scan': "⏳ Scanning (cached if <1hr)...",
        'bonus_done': "✅ Scan complete. Check DB for yields >5%.",
        'bonus_fail': "❌ Scan failed.",
        'scan_usage': "Usage: /scan <text>",
        'scan_threat': "🚨 Threat detected: '{}'",
        'scan_clean': "✅ Clean.",
        'checkwallet_usage': "Usage: /checkwallet <address>",
        'checkwallet_scam': "🚨 Scam!",
        'checkwallet_clean': "✅ Clean.",
        'reportwallet_usage': "Usage: /reportwallet <address>",
        'reportwallet_done': "✅ Reported.",
        'lockdown_done': "🔒 Lockdown engaged.",
        'admin_only': "⛔ Admin only.",
        'users_list': "📋 Users:\n{}",
        'users_empty': "No users.",
        'resume_usage': "Usage: /resume <id>",
        'resume_done': "✅ Resumed {}.",
        'reset_hwm_usage': "Usage: /reset_hwm <id>",
        'reset_hwm_done': "✅ HWM reset to ${:.2f} for {}.",
        'user_not_found': "User not found.",
        'about': (
            "🤖 *MoussaBlvckLion Bot – Your DeFi Command Center*\n\n"
            "I am a **High‑Water Mark (HWM) trading assistant** that:\n"
            "• Tracks your total Net Worth (USD value of all assets).\n"
            "• Charges **8% fee** only on *new all-time high profits* (never on losses).\n"
            "• **Auto‑withdraws** the fee to the admin wallet (with your approval).\n"
            "• **Scans Binance Earn** for high‑yield bonuses (up to 10%+ APY).\n"
            "• **Protects you** from scams: scans messages, checks wallet addresses.\n"
            "• Has an **emergency lockdown** to pause your account instantly.\n\n"
            "🔐 Your API keys are **encrypted** and your messages are **auto‑deleted** for privacy.\n\n"
            "Commands:\n"
            "/start – Welcome\n"
            "/connect – Connect your Binance account (step-by-step)\n"
            "/balance – Check your wallet\n"
            "/networth – Check total USD value (HWM)\n"
            "/price <symbol> – Get current price (e.g., /price BTCUSDT)\n"
            "/buy <symbol> <amount> – Buy (e.g., /buy BTCUSDT 50)\n"
            "/sell <symbol> <quantity> – Sell (e.g., /sell BTCUSDT 0.001)\n"
            "/bonuses – Scan Binance Earn promotions\n"
            "/scan <text> – Scan for scams\n"
            "/checkwallet <address> – Check scam status\n"
            "/lockdown – Emergency pause trading\n"
            "/lang – Switch language (English / Français)\n"
            "/about – This message"
        ),
        'lang_switched': "Language switched to English.",
        'lang_current': "Current language: English.",
    },
    'fr': {
        'welcome': "👋 Bienvenue sur MoussaBlvckLion Bot – votre assistant DeFi.\nEnvoyez /connect pour lier votre compte Binance.",
        'already_registered': "🔐 Vous êtes déjà enregistré. Utilisez /connect pour mettre à jour vos clés.",
        'connect_start': "🔑 Envoyez-moi votre **clé API Binance**.\n_(Votre message sera supprimé pour des raisons de sécurité)_",
        'connect_secret': "🔒 Reçu. Envoyez-moi maintenant votre **clé secrète**.\n_(Votre message sera supprimé)_",
        'connect_success': "✅ Connecté à Binance ! Valeur nette initiale : ${:.2f}",
        'connect_invalid': "❌ Clés invalides : {}. Veuillez recommencer avec /connect.",
        'connect_only_binance': "❌ Seul Binance est pris en charge pour le moment.",
        'balance': "💰 Solde :\n{}",
        'balance_empty': "💰 Portefeuille vide.",
        'networth': "📊 VN : ${:.2f}\nHWM : ${:.2f}\nNon réalisé : ${:.2f}",
        'price': "📈 {} : ${:.2f}",
        'price_error': "❌ Symbole '{}' introuvable. Essayez BTCUSDT, ETHBUSD, etc.",
        'buy_min': "❌ Le montant minimum est de 10 $ (ou équivalent).",
        'buy_max': "❌ Le montant maximum est de 1000 $ (limite de sécurité).",
        'buy_success': "✅ Achat de {:.6f} {} à ${:.2f}",
        'buy_fill_zero': "⚠️ Ordre exécuté avec 0. Vérifiez votre solde / montant minimum.",
        'buy_failed': "❌ Échec de l'achat : {}",
        'buy_usage': "❌ Utilisation : /buy <symbole> <montant> (ex : /buy BTCUSDT 50)",
        'sell_usage': "❌ Utilisation : /sell <symbole> <quantité> (ex : /sell BTCUSDT 0.001)",
        'sell_insufficient': "❌ Solde insuffisant de {}. Solde : {}",
        'sell_success': "✅ Vente de {:.6f} {} à ${:.2f}",
        'sell_zero': "⚠️ Ordre de vente exécuté avec 0.",
        'sell_failed': "❌ Échec de la vente : {}",
        'sell_fee_prompt': "💰 Profit : ${:.2f}. Frais (8%) : ${:.2f}.\nRépondez OUI pour auto‑prélèvement, NON pour refuser.",
        'sell_no_fee': "✅ Vente de {:.6f} {} à ${:.2f}. Aucun frais (profit < 1 $).",
        'fee_yes': "✅ Frais de ${:.2f} envoyés ! {}",
        'fee_no': "❌ Frais refusés. Compte SUSPENDU.",
        'fee_withdraw_fail': "❌ Échec du retrait : {}\nCompte SUSPENDU.",
        'fee_admin_wallet_missing': "❌ Portefeuille administrateur non défini.",
        'fee_pending': "⛔ Veuillez d'abord répondre à la demande de frais (OUI/NON).",
        'fee_unknown': "Répondez OUI ou NON.",
        'bonus_scan': "⏳ Analyse en cours (mise en cache si < 1h)...",
        'bonus_done': "✅ Analyse terminée. Consultez la base de données pour les rendements > 5 %.",
        'bonus_fail': "❌ Échec de l'analyse.",
        'scan_usage': "Utilisation : /scan <texte>",
        'scan_threat': "🚨 Menace détectée : '{}'",
        'scan_clean': "✅ Aucune menace.",
        'checkwallet_usage': "Utilisation : /checkwallet <adresse>",
        'checkwallet_scam': "🚨 Arnaque !",
        'checkwallet_clean': "✅ Propre.",
        'reportwallet_usage': "Utilisation : /reportwallet <adresse>",
        'reportwallet_done': "✅ Signalé.",
        'lockdown_done': "🔒 Verrouillage activé.",
        'admin_only': "⛔ Réservé à l'administrateur.",
        'users_list': "📋 Utilisateurs :\n{}",
        'users_empty': "Aucun utilisateur.",
        'resume_usage': "Utilisation : /resume <id>",
        'resume_done': "✅ Utilisateur {} réactivé.",
        'reset_hwm_usage': "Utilisation : /reset_hwm <id>",
        'reset_hwm_done': "✅ HWM réinitialisé à ${:.2f} pour {}.",
        'user_not_found': "Utilisateur introuvable.",
        'about': (
            "🤖 *MoussaBlvckLion Bot – Votre Centre de Commandes DeFi*\n\n"
            "Je suis un assistant de trading à **High‑Water Mark (HWM)** qui :\n"
            "• Suit votre valeur nette totale (valeur USD de tous vos actifs).\n"
            "• Prélève **8% de frais** uniquement sur les *nouveaux bénéfices records* (jamais sur les pertes).\n"
            "• **Retire automatiquement** les frais vers le portefeuille de l'admin (avec votre approbation).\n"
            "• **Analyse Binance Earn** pour des bonus à haut rendement (jusqu'à 10%+ APY).\n"
            "• **Vous protège** contre les arnaques : scanne les messages, vérifie les adresses.\n"
            "• Dispose d'un **verrouillage d'urgence** pour suspendre instantanément votre compte.\n\n"
            "🔐 Vos clés API sont **chiffrées** et vos messages sont **supprimés automatiquement**.\n\n"
            "Commandes :\n"
            "/start – Accueil\n"
            "/connect – Connecter votre compte Binance (étape par étape)\n"
            "/balance – Voir votre solde\n"
            "/networth – Voir la valeur nette (HWM)\n"
            "/price <symbole> – Prix actuel (ex : /price BTCUSDT)\n"
            "/buy <symbole> <montant> – Acheter (ex : /buy BTCUSDT 50)\n"
            "/sell <symbole> <quantité> – Vendre (ex : /sell BTCUSDT 0.001)\n"
            "/bonuses – Analyser les promotions Binance Earn\n"
            "/scan <texte> – Analyser un message pour détecter une arnaque\n"
            "/checkwallet <adresse> – Vérifier une adresse\n"
            "/lockdown – Verrouillage d'urgence\n"
            "/lang – Changer de langue (English / Français)\n"
            "/about – Ce message"
        ),
        'lang_switched': "Langue changée en français.",
        'lang_current': "Langue actuelle : français.",
    }
}

def get_text(key, lang='en', *args):
    msg_dict = LANG.get(lang, LANG['en'])
    text = msg_dict.get(key, key)
    if args:
        return text.format(*args)
    return text

def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            exchange TEXT,
            api_key TEXT,
            secret TEXT,
            total_profit REAL DEFAULT 0,
            fee_paid REAL DEFAULT 0,
            high_water_mark REAL DEFAULT 0,
            last_net_worth REAL DEFAULT 0,
            trading_enabled INTEGER DEFAULT 1,
            language TEXT DEFAULT 'en',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            price REAL,
            quote_qty REAL,
            fee REAL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS scam_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT UNIQUE,
            chain TEXT,
            reported_by INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS bonuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product TEXT,
            apy REAL,
            min_amount REAL,
            asset TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS bonus_cache (
            key TEXT PRIMARY KEY,
            data TEXT,
            last_updated TIMESTAMP
        )''')
        conn.commit()
        conn.close()

def encrypt(t): return cipher.encrypt(t.encode()).decode()
def decrypt(t): return cipher.decrypt(t.encode()).decode()

def get_user(uid):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE telegram_id = ?', (uid,))
        row = c.fetchone()
        conn.close()
    if row:
        return {'telegram_id': row[0], 'exchange': row[1], 'api_key': decrypt(row[2]),
                'secret': decrypt(row[3]), 'total_profit': row[4], 'fee_paid': row[5],
                'high_water_mark': row[6], 'last_net_worth': row[7], 'trading_enabled': bool(row[8]),
                'language': row[9] if len(row) > 9 else 'en'}
    return None

def save_user(uid, exchange, api_key, secret, lang='en'):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO users (telegram_id, exchange, api_key, secret, language) VALUES (?, ?, ?, ?, ?)',
                  (uid, exchange, encrypt(api_key), encrypt(secret), lang))
        conn.commit()
        conn.close()

def update_user_stats(uid, profit, fee, hwm, net_worth):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET total_profit = total_profit + ?, fee_paid = fee_paid + ?, high_water_mark = ?, last_net_worth = ? WHERE telegram_id = ?',
                  (profit, fee, hwm, net_worth, uid))
        conn.commit()
        conn.close()

def update_net_worth(uid, net_worth):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET last_net_worth = ? WHERE telegram_id = ?', (net_worth, uid))
        conn.commit()
        conn.close()

def set_trading_enabled(uid, enabled):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET trading_enabled = ? WHERE telegram_id = ?', (1 if enabled else 0, uid))
        conn.commit()
        conn.close()

def set_user_language(uid, lang):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET language = ? WHERE telegram_id = ?', (lang, uid))
        conn.commit()
        conn.close()

def record_trade(uid, symbol, side, quantity, price, quote_qty, fee=0):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO trades (telegram_id, symbol, side, quantity, price, quote_qty, fee) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (uid, symbol, side, quantity, price, quote_qty, fee))
        conn.commit()
        conn.close()

def record_bonus(product, apy, min_amount, asset):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO bonuses (product, apy, min_amount, asset) VALUES (?, ?, ?, ?)',
                  (product, apy, min_amount, asset))
        conn.commit()
        conn.close()

def is_scam_wallet(address):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT 1 FROM scam_wallets WHERE address = ?', (address,))
        row = c.fetchone()
        conn.close()
    return row is not None

def report_scam_wallet(address, chain, reporter):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute('INSERT INTO scam_wallets (address, chain, reported_by) VALUES (?, ?, ?)', (address, chain, reporter))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        conn.close()

def get_cached_bonus():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT data, last_updated FROM bonus_cache WHERE key = "scan"')
        row = c.fetchone()
        conn.close()
    if row:
        timestamp = datetime.fromisoformat(row[1])
        if datetime.now() - timestamp < timedelta(hours=1):
            return row[0]
    return None

def set_cached_bonus(data):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO bonus_cache (key, data, last_updated) VALUES ("scan", ?, ?)',
                  (data, datetime.now().isoformat()))
        conn.commit()
        conn.close()

def get_price_binance(symbol='BTCUSDT'):
    resp = requests.get(f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}', timeout=8)
    resp.raise_for_status()
    return float(resp.json()['price'])

def get_price_coingecko(coin_id='bitcoin'):
    map_ids = {'BTC': 'bitcoin', 'ETH': 'ethereum', 'BNB': 'binancecoin', 'SOL': 'solana', 'XRP': 'ripple'}
    coin = map_ids.get(coin_id.upper(), 'bitcoin')
    url = f'https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd'
    resp = requests.get(url, timeout=8)
    resp.raise_for_status()
    data = resp.json()
    return data.get(coin, {}).get('usd', 0.0)

def get_price_with_fallback(symbol='BTCUSDT'):
    try:
        return get_price_binance(symbol)
    except Exception:
        return get_price_coingecko(symbol.replace('USDT', ''))

def get_all_prices_binance():
    resp = requests.get('https://api.binance.com/api/v3/ticker/price', timeout=8)
    resp.raise_for_status()
    return {item['symbol']: float(item['price']) for item in resp.json()}

def get_total_net_worth(api_key, secret):
    balances = get_balance(api_key, secret)
    prices = get_all_prices_binance()
    total = 0.0
    for asset, qty in balances.items():
        if qty <= 0: continue
        if asset == 'USDT':
            total += qty
            continue
        symbol = f"{asset}USDT"
        if symbol in prices:
            total += qty * prices[symbol]
        else:
            try: total += qty * get_price_coingecko(asset)
            except: pass
    return total

def binance_request(api_key, secret, endpoint, params=None, method='GET'):
    base_url = 'https://api.binance.com'
    timestamp = int(time.time() * 1000)
    if params is None: params = {}
    params['timestamp'] = timestamp
    params['recvWindow'] = 5000
    qs = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    headers = {'X-MBX-APIKEY': api_key}
    full_url = f"{base_url}{endpoint}?{qs}&signature={signature}"
    resp = requests.request(method, full_url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()

def test_binance_keys(api_key, secret):
    try:
        binance_request(api_key, secret, '/api/v3/account')
        return True, "Valid."
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

def get_exchange_info(symbol):
    try:
        resp = requests.get(f'https://api.binance.com/api/v3/exchangeInfo?symbol={symbol}', timeout=8)
        resp.raise_for_status()
        for s in resp.json()['symbols']:
            if s['symbol'] == symbol:
                return s
    except:
        pass
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

def get_best_withdrawal_network(api_key, secret):
    balances = get_balance(api_key, secret)
    if balances.get('BNB', 0) > 0.001: return 'BSC'
    if balances.get('ETH', 0) > 0.001: return 'ERC20'
    if balances.get('TRX', 0) > 0.001: return 'TRC20'
    return 'BSC'

def withdraw_fee_smart(api_key, secret, asset, amount_usd, address):
    try:
        balances = get_balance(api_key, secret)
        usdt_balance = balances.get('USDT', 0)
        if usdt_balance >= amount_usd:
            network = get_best_withdrawal_network(api_key, secret)
            resp = binance_request(api_key, secret, '/sapi/v1/withdraw',
                                   {'coin': asset, 'address': address, 'amount': amount_usd, 'network': network}, method='POST')
            return True, f"Withdrew {amount_usd} {asset} on {network}. ID: {resp.get('id', 'N/A')}"
        best_asset = None
        best_value = 0
        prices = get_all_prices_binance()
        for a, qty in balances.items():
            if a == 'USDT' or qty <= 0: continue
            val = qty * prices.get(f"{a}USDT", 0)
            if val > best_value:
                best_value = val
                best_asset = a
        if best_asset and best_value > amount_usd * 1.5:
            sell_amount_usd = amount_usd * 1.05
            symbol = f"{best_asset}USDT"
            price = prices.get(symbol, 0)
            if price > 0:
                qty_to_sell = sell_amount_usd / price
                binance_request(api_key, secret, '/api/v3/order',
                                {'symbol': symbol, 'side': 'SELL', 'type': 'MARKET', 'quantity': qty_to_sell}, method='POST')
                return withdraw_fee_smart(api_key, secret, asset, amount_usd, address)
        return False, "Insufficient USDT and failed to convert assets."
    except Exception as e:
        return False, str(e)

SCAM_PATTERNS = [
    r"(?i)validate your wallet", r"(?i)seed phrase", r"(?i)private key",
    r"(?i)connect wallet", r"(?i)free airdrop", r"(?i)claim your reward"
]

def scan_message(text):
    for pattern in SCAM_PATTERNS:
        if re.search(pattern, text):
            return pattern
    return None

def fetch_binance_bonuses():
    cached = get_cached_bonus()
    if cached: return True
    try:
        resp = requests.get('https://api.binance.com/sapi/v1/simple-earn/flexible/list', timeout=15)
        if resp.status_code == 200:
            for item in resp.json().get('rows', []):
                apy = float(item.get('latestAnnualPercentageRate', 0))
                if apy > 5.0:
                    record_bonus(f"Flexible {item['asset']}", apy, float(item.get('minPurchaseAmount', 0)), item['asset'])
        resp = requests.get('https://api.binance.com/sapi/v1/simple-earn/locked/list', timeout=15)
        if resp.status_code == 200:
            for item in resp.json().get('rows', []):
                apy = float(item.get('annualPercentageRate', 0))
                if apy > 10.0:
                    record_bonus(f"Locked {item['asset']}", apy, float(item.get('minPurchaseAmount', 0)), item['asset'])
        set_cached_bonus(str(datetime.now()))
        return True
    except Exception as e:
        logging.error(f"Bonus scan failed: {e}")
        return False

def user_required(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        uid = update.effective_user.id
        user = get_user(uid)
        if not user:
            lang = 'fr' if update.effective_user.language_code and update.effective_user.language_code.startswith('fr') else 'en'
            await update.message.reply_text(get_text('welcome', lang))
            return
        if not user['trading_enabled']:
            lang = user.get('language', 'en')
            await update.message.reply_text("⛔ " + get_text('fee_no', lang))
            return
        return await func(update, context, user, *args, **kwargs)
    return wrapper

async def start(update, context):
    uid = update.effective_user.id
    lang = 'fr' if update.effective_user.language_code and update.effective_user.language_code.startswith('fr') else 'en'
    user = get_user(uid)
    if user:
        await update.message.reply_text(get_text('already_registered', lang))
    else:
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('INSERT INTO users (telegram_id, language) VALUES (?, ?) ON CONFLICT(telegram_id) DO UPDATE SET language = ?', (uid, lang, lang))
            conn.commit()
            conn.close()
        await update.message.reply_text(get_text('welcome', lang))

async def lang_command(update, context):
    uid = update.effective_user.id
    args = context.args
    if args and args[0].lower() in ['fr', 'en']:
        lang = args[0].lower()
        set_user_language(uid, lang)
        await update.message.reply_text(get_text('lang_switched', lang))
    else:
        user = get_user(uid)
        lang = user.get('language', 'en') if user else 'en'
        await update.message.reply_text(get_text('lang_current', lang) + "\nUsage: /lang en  or  /lang fr")

async def connect(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    lang = user.get('language', 'en') if user else 'en'
    args = context.args
    if len(args) == 3:
        exchange, api_key, secret = args[0], args[1], args[2]
        if exchange.lower() != "binance":
            return await update.message.reply_text(get_text('connect_only_binance', lang))
        ok, msg = test_binance_keys(api_key, secret)
        if not ok:
            return await update.message.reply_text(get_text('connect_invalid', lang).format(msg[:100]))
        try: nw = get_total_net_worth(api_key, secret)
        except: nw = 0.0
        save_user(uid, exchange, api_key, secret, lang)
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('UPDATE users SET high_water_mark = ?, last_net_worth = ? WHERE telegram_id = ?', (nw, nw, uid))
            conn.commit()
            conn.close()
        await update.message.reply_text(get_text('connect_success', lang).format(nw))
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except: pass
        return
    context.user_data['connect_state'] = 'awaiting_api'
    await update.message.reply_text(get_text('connect_start', lang))

async def handle_connect_input(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    lang = user.get('language', 'en') if user else 'en'
    text = update.message.text.strip()
    state = context.user_data.get('connect_state')
    if not state: return
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except: pass
    if state == 'awaiting_api':
        context.user_data['temp_api_key'] = text
        context.user_data['connect_state'] = 'awaiting_secret'
        await update.message.reply_text(get_text('connect_secret', lang))
    elif state == 'awaiting_secret':
        api_key = context.user_data.get('temp_api_key')
        secret = text
        ok, msg = test_binance_keys(api_key, secret)
        if not ok:
            context.user_data.clear()
            await update.message.reply_text(get_text('connect_invalid', lang).format(msg[:100]))
            return
        try: nw = get_total_net_worth(api_key, secret)
        except: nw = 0.0
        save_user(uid, "Binance", api_key, secret, lang)
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('UPDATE users SET high_water_mark = ?, last_net_worth = ? WHERE telegram_id = ?', (nw, nw, uid))
            conn.commit()
            conn.close()
        await update.message.reply_text(get_text('connect_success', lang).format(nw))
        context.user_data.clear()

@user_required
async def balance(update, context, user):
    lang = user.get('language', 'en')
    bal = get_balance(user['api_key'], user['secret'])
    if not bal:
        await update.message.reply_text(get_text('balance_empty', lang))
        return
    lines = [f"{k}: {v}" for k, v in list(bal.items())[:10]]
    await update.message.reply_text(get_text('balance', lang).format("\n".join(lines)))

@user_required
async def networth(update, context, user):
    lang = user.get('language', 'en')
    try:
        nw = get_total_net_worth(user['api_key'], user['secret'])
        await update.message.reply_text(get_text('networth', lang).format(nw, user['high_water_mark'], nw - user['high_water_mark']))
    except Exception as e: await update.message.reply_text(f"❌ {str(e)[:100]}")

@user_required
async def sync(update, context, user):
    lang = user.get('language', 'en')
    try:
        nw = get_total_net_worth(user['api_key'], user['secret'])
        update_net_worth(user['telegram_id'], nw)
        await update.message.reply_text(f"✅ " + get_text('networth', lang).split('\n')[0].format(nw))
    except Exception as e: await update.message.reply_text(f"❌ {str(e)[:100]}")

async def price(update, context):
    parts = update.message.text.split()
    if len(parts) < 2:
        await update.message.reply_text("❌ Usage: /price <symbol> (e.g., /price BTCUSDT)")
        return
    raw_symbol = parts[1].upper()
    symbol = resolve_symbol(raw_symbol)
    uid = update.effective_user.id
    user = get_user(uid)
    lang = user.get('language', 'en') if user else 'en'
    if not symbol:
        await update.message.reply_text(get_text('price_error', lang).format(raw_symbol))
        return
    try:
        price = get_price_with_fallback(symbol)
        await update.message.reply_text(get_text('price', lang).format(symbol, price))
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

@user_required
async def buy(update, context, user):
    lang = user.get('language', 'en')
    if context.user_data.get('fee_lock'):
        return await update.message.reply_text(get_text('fee_pending', lang))
    parts = update.message.text.split()
    if len(parts) < 3:
        return await update.message.reply_text(get_text('buy_usage', lang))
    amount = None; raw_symbol = None
    for p in parts[1:]:
        try: amount = float(p)
        except ValueError: raw_symbol = p.upper()
    if amount is None or raw_symbol is None:
        return await update.message.reply_text(get_text('buy_usage', lang))
    symbol = resolve_symbol(raw_symbol)
    if not symbol:
        return await update.message.reply_text(get_text('price_error', lang).format(raw_symbol))
    if amount < 10: return await update.message.reply_text(get_text('buy_min', lang))
    if amount > 1000: return await update.message.reply_text(get_text('buy_max', lang))
    try:
        order = binance_request(user['api_key'], user['secret'], '/api/v3/order',
                                {'symbol': symbol, 'side': 'BUY', 'type': 'MARKET', 'quoteOrderQty': amount}, method='POST')
        qty = float(order.get('executedQty', 0))
        if qty > 0:
            price = float(order.get('cummulativeQuoteQty', 0)) / qty
            record_trade(user['telegram_id'], symbol, 'BUY', qty, price, amount)
            try:
                new_nw = get_total_net_worth(user['api_key'], user['secret'])
                update_net_worth(user['telegram_id'], new_nw)
                if new_nw > user['high_water_mark']:
                    with db_lock:
                        conn = sqlite3.connect(DB_PATH)
                        c = conn.cursor()
                        c.execute('UPDATE users SET high_water_mark = ? WHERE telegram_id = ?', (new_nw, user['telegram_id']))
                        conn.commit()
                        conn.close()
            except: pass
            await update.message.reply_text(get_text('buy_success', lang).format(qty, symbol, price))
        else: await update.message.reply_text(get_text('buy_fill_zero', lang))
    except Exception as e: await update.message.reply_text(get_text('buy_failed', lang).format(str(e)[:150]))

@user_required
async def sell(update, context, user):
    lang = user.get('language', 'en')
    if context.user_data.get('fee_lock'):
        return await update.message.reply_text(get_text('fee_pending', lang))
    parts = update.message.text.split()
    if len(parts) < 3:
        return await update.message.reply_text(get_text('sell_usage', lang))
    qty = None; raw_symbol = None
    for p in parts[1:]:
        try: qty = float(p)
        except ValueError: raw_symbol = p.upper()
    if qty is None or raw_symbol is None:
        return await update.message.reply_text(get_text('sell_usage', lang))
    if qty <= 0: return await update.message.reply_text("❌ Quantity must be positive.")
    symbol = resolve_symbol(raw_symbol)
    if not symbol:
        return await update.message.reply_text(get_text('price_error', lang).format(raw_symbol))
    try:
        bal = get_balance(user['api_key'], user['secret'])
        base_asset = symbol
        for quote in ['USDT', 'BUSD', 'BTC', 'ETH', 'BNB']:
            if symbol.endswith(quote):
                base_asset = symbol[:-len(quote)]
                break
        if bal.get(base_asset, 0) < qty:
            return await update.message.reply_text(get_text('sell_insufficient', lang).format(base_asset, bal.get(base_asset, 0)))
        order = binance_request(user['api_key'], user['secret'], '/api/v3/order',
                                {'symbol': symbol, 'side': 'SELL', 'type': 'MARKET', 'quantity': qty}, method='POST')
        filled = float(order.get('executedQty', 0))
        if filled <= 0: return await update.message.reply_text(get_text('sell_zero', lang))
        avg_price = float(order.get('cummulativeQuoteQty', 0)) / filled
        record_trade(user['telegram_id'], symbol, 'SELL', filled, avg_price, filled * avg_price)
        nw_after = get_total_net_worth(user['api_key'], user['secret'])
        profit = nw_after - user['high_water_mark']
        if profit > 1.0:
            fee = profit * 0.08
            context.user_data['fee_lock'] = True
            context.user_data['pending_fee'] = {'profit': profit, 'fee': fee, 'nw_after': nw_after, 'hwm': user['high_water_mark'], 'uid': user['telegram_id']}
            await update.message.reply_text(get_text('sell_fee_prompt', lang).format(profit, fee))
        else:
            update_net_worth(user['telegram_id'], nw_after)
            if nw_after > user['high_water_mark']:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute('UPDATE users SET high_water_mark = ? WHERE telegram_id = ?', (nw_after, user['telegram_id']))
                    conn.commit()
                    conn.close()
            await update.message.reply_text(get_text('sell_no_fee', lang).format(filled, symbol, avg_price))
    except Exception as e: await update.message.reply_text(get_text('sell_failed', lang).format(str(e)[:150]))

async def handle_fee_response(update, context):
    uid = update.effective_user.id
    if not context.user_data.get('fee_lock'): return
    pending = context.user_data.get('pending_fee')
    if not pending or pending.get('uid') != uid: return
    user = get_user(uid)
    lang = user.get('language', 'en') if user else 'en'
    text = update.message.text.lower()
    if text in ["yes", "oui"]:
        if not ADMIN_WALLET:
            return await update.message.reply_text(get_text('fee_admin_wallet_missing', lang))
        success, msg = withdraw_fee_smart(user['api_key'], user['secret'], 'USDT', pending['fee'], ADMIN_WALLET)
        if success:
            update_user_stats(uid, pending['profit'], pending['fee'], pending['nw_after'], pending['nw_after'])
            await update.message.reply_text(get_text('fee_yes', lang).format(pending['fee'], msg))
        else:
            set_trading_enabled(uid, False)
            await update.message.reply_text(get_text('fee_withdraw_fail', lang).format(msg))
            if ADMIN_ID: await context.bot.send_message(ADMIN_ID, f"⚠️ Withdrawal failed for {uid}")
        context.user_data['fee_lock'] = False
        context.user_data.pop('pending_fee', None)
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except: pass
    elif text in ["no", "non"]:
        set_trading_enabled(uid, False)
        await update.message.reply_text(get_text('fee_no', lang))
        if ADMIN_ID: await context.bot.send_message(ADMIN_ID, f"⚠️ User {uid} declined fee.")
        context.user_data['fee_lock'] = False
        context.user_data.pop('pending_fee', None)
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except: pass
    else: await update.message.reply_text(get_text('fee_unknown', lang))

@user_required
async def bonuses(update, context, user):
    lang = user.get('language', 'en')
    await update.message.reply_text(get_text('bonus_scan', lang))
    if fetch_binance_bonuses():
        await update.message.reply_text(get_text('bonus_done', lang))
    else:
        await update.message.reply_text(get_text('bonus_fail', lang))

@user_required
async def scan(update, context, user):
    lang = user.get('language', 'en')
    text = ' '.join(context.args)
    if not text: return await update.message.reply_text(get_text('scan_usage', lang))
    res = scan_message(text)
    if res: await update.message.reply_text(get_text('scan_threat', lang).format(res))
    else: await update.message.reply_text(get_text('scan_clean', lang))

@user_required
async def checkwallet(update, context, user):
    lang = user.get('language', 'en')
    addr = context.args[0] if context.args else None
    if not addr: return await update.message.reply_text(get_text('checkwallet_usage', lang))
    await update.message.reply_text(get_text('checkwallet_scam', lang) if is_scam_wallet(addr) else get_text('checkwallet_clean', lang))

@user_required
async def reportwallet(update, context, user):
    lang = user.get('language', 'en')
    addr = context.args[0] if context.args else None
    if not addr: return await update.message.reply_text(get_text('reportwallet_usage', lang))
    report_scam_wallet(addr, "Unknown", update.effective_user.id)
    await update.message.reply_text(get_text('reportwallet_done', lang))

@user_required
async def lockdown(update, context, user):
    lang = user.get('language', 'en')
    set_trading_enabled(user['telegram_id'], False)
    context.user_data.clear()
    await update.message.reply_text(get_text('lockdown_done', lang))
    if ADMIN_ID: await context.bot.send_message(ADMIN_ID, f"⚠️ User {user['telegram_id']} locked down.")

@user_required
async def about(update, context, user):
    lang = user.get('language', 'en')
    await update.message.reply_text(get_text('about', lang), parse_mode='Markdown')

async def users_list(update, context):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("⛔ Admin only.")
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT telegram_id, total_profit, fee_paid, trading_enabled FROM users')
        rows = c.fetchall()
        conn.close()
    if not rows:
        await update.message.reply_text("No users.")
        return
    reply = "📋 Users:\n" + "\n".join([f"ID {r[0]}: Profit ${r[1]:.2f}, Fee ${r[2]:.2f}, {'✅' if r[3] else '❌'}" for r in rows])
    await update.message.reply_text(reply)

async def resume_user(update, context):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID: return await update.message.reply_text("⛔ Admin only.")
    try:
        uid = int(context.args[0]); set_trading_enabled(uid, True)
        await update.message.reply_text(f"✅ Resumed {uid}.")
    except: await update.message.reply_text("Usage: /resume <id>")

async def reset_hwm(update, context):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID: return await update.message.reply_text("⛔ Admin only.")
    try:
        uid = int(context.args[0]); user = get_user(uid)
        if not user: return await update.message.reply_text("User not found.")
        nw = get_total_net_worth(user['api_key'], user['secret'])
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('UPDATE users SET high_water_mark = ?, last_net_worth = ? WHERE telegram_id = ?', (nw, nw, uid))
            conn.commit()
            conn.close()
        await update.message.reply_text(f"✅ HWM reset to ${nw:.2f} for {uid}.")
    except: await update.message.reply_text("Usage: /reset_hwm <id>")

flask_app = Flask(__name__)
@flask_app.route('/')
def dashboard():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        users = c.fetchone()[0]
        c.execute('SELECT SUM(fee_paid) FROM users')
        fees = c.fetchone()[0] or 0.0
        conn.close()
    return jsonify({"status": "MoussaBlvckLion LIVE", "users": users, "total_fees_collected_usd": round(fees, 2)})

def main():
    init_db()
    threading.Thread(target=lambda: flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000))), daemon=True).start()
    app = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).read_timeout(30).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lang", lang_command))
    app.add_handler(CommandHandler("connect", connect))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("networth", networth))
    app.add_handler(CommandHandler("sync", sync))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("bonuses", bonuses))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("checkwallet", checkwallet))
    app.add_handler(CommandHandler("reportwallet", reportwallet))
    app.add_handler(CommandHandler("lockdown", lockdown))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("users", users_list))
    app.add_handler(CommandHandler("resume", resume_user))
    app.add_handler(CommandHandler("reset_hwm", reset_hwm))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_connect_input))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fee_response))
    logging.info("✅ ULTIMATE BILINGUAL BOT STARTED (English/Français).")
    app.run_polling()

if __name__ == "__main__":
    import asyncio
    async def startup():
        if ADMIN_ID:
            try:
                import requests
                token = os.getenv('TELEGRAM_TOKEN')
                if token and ADMIN_ID:
                    masked = ADMIN_WALLET[:6] + "..." + ADMIN_WALLET[-4:] if ADMIN_WALLET else "Not Set"
                    url = f"https://api.telegram.org/bot{token}/sendMessage"
                    payload = {"chat_id": ADMIN_ID, "text": f"🚀 Bot is LIVE! Wallet: `{masked}`\nLangues: English / Français", "parse_mode": "Markdown"}
                    requests.post(url, json=payload)
            except Exception as e:
                logging.error(f"Startup health check failed: {e}")
    asyncio.run(startup())
    main()
