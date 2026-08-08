import os
import logging
import sqlite3
import hmac
import hashlib
import time
import requests
import re
import threading
import uuid
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from cryptography.fernet import Fernet
from flask import Flask, jsonify, render_template_string, request, Response

load_dotenv()
logging.basicConfig(level=logging.INFO)

# ------------------------- CONFIG -------------------------
ADMIN_WALLET = os.getenv('ADMIN_WALLET')
ADMIN_ID = int(os.getenv('ADMIN_TELEGRAM_ID', 0)) if os.getenv('ADMIN_TELEGRAM_ID') else None
CUSTOMER_CARE_ID = int(os.getenv('CUSTOMER_CARE_ID', 0)) if os.getenv('CUSTOMER_CARE_ID') else None
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY: raise ValueError("ENCRYPTION_KEY missing")
cipher = Fernet(ENCRYPTION_KEY.encode())
DB_PATH = "users.db"
db_lock = threading.Lock()
DAILY_LOSS_LIMIT = 50.0
MAX_ORDER_USD = 1000.0
TRADE_COOLDOWN = 10

FEE_API_KEY = os.getenv('FEE_API_KEY')
FEE_SECRET = os.getenv('FEE_SECRET')

DASHBOARD_USER = os.getenv('DASHBOARD_USER', 'admin')
DASHBOARD_PASS = os.getenv('DASHBOARD_PASS', 'changeme')

# ------------------------- MULTI-LANGUAGE DICT -------------------------
LANG = {
    'en': {
        'welcome': "👋 Welcome to MoussaBlvckLion Bot – your DeFi assistant.\nSend /connect to link your Binance account.",
        'already_registered': "🔐 You're already registered. Use /connect to update keys.",
        'connect_start': "🔑 Send me your **Binance API Key**.\n_(Your message will be deleted for security)_",
        'connect_secret': "🔒 Got it. Now send me your **Secret Key**.\n_(Your message will be deleted)_",
        'connect_success': "✅ Connected to Binance! Initial Net Worth: ${:.2f}\n\n⚠️ Please read and accept our terms by sending: /accept",
        'connect_invalid': "❌ Invalid keys: {}. Please start over with /connect.",
        'connect_only_binance': "❌ Only Binance is supported for now.",
        'balance': "💰 Balance:\n{}",
        'balance_empty': "💰 Wallet is empty.",
        'networth': "📊 NW: ${:.2f}\nHWM: ${:.2f}\nUnrealized: ${:.2f}",
        'price': "📈 {}: ${:.2f}",
        'price_error': "❌ Symbol '{}' not found. Try BTCUSDT, ETHBUSD, etc.",
        'buy_min': "❌ Minimum spend is $10 (or equivalent).",
        'buy_max': "❌ Maximum spend is ${} (safety limit).",
        'buy_success': "✅ Bought {:.6f} {} @ ${:.2f}",
        'buy_fill_zero': "⚠️ Order filled 0. Check balance / min notional.",
        'buy_failed': "❌ Buy failed: {}",
        'buy_usage': "❌ Usage: /buy <symbol> <amount> (e.g., /buy BTCUSDT 50)",
        'buy_terms_required': "❌ You must accept the terms first. Send /accept.",
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
        'customer_care_only': "⛔ Customer Care only.",
        'users_list': "📋 Users:\n{}",
        'users_empty': "No users.",
        'resume_usage': "Usage: /resume <id>",
        'resume_done': "✅ Resumed {}.",
        'reset_hwm_usage': "Usage: /reset_hwm <id>",
        'reset_hwm_done': "✅ HWM reset to ${:.2f} for {}.",
        'user_not_found': "User not found.",
        'terms_accepted': "✅ You have accepted the terms. Trading is now enabled.",
        'terms_text': "📜 *Terms of Service*\n\nBy using this bot, you agree that:\n1. MoussaBlvckLion Bot will charge an **8% fee** on **profits only** (High‑Water Mark model).\n2. The fee will be **automatically withdrawn** from your Binance account to the admin's wallet.\n3. You are responsible for your own trading decisions.\n4. This bot is provided \"as is\" – use at your own risk.\n\nTo accept, send: /accept",
        'history_header': "📜 *Last 10 Trades*\n",
        'history_empty': "No trades yet.",
        'history_line': "{}. {} {} {:.6f} @ ${:.2f} ({})",
        'daily_loss_exceeded': "❌ Daily loss limit of ${} exceeded. Trading paused until tomorrow.",
        'terms_required': "❌ You must accept the terms first. Send /accept.",
        'deposit_alert': "⚠️ *Large Net Worth spike detected for user {}*\n\nCurrent NW: ${:.2f}\nPrevious NW: ${:.2f}\nIncrease: ${:.2f} ({:.1f}%)\n\nThis may be a deposit. Click below to reset HWM if it's a deposit:",
        'deposit_reset_success': "✅ HWM reset to ${:.2f} for user {} (deposit detected).",
        'cooldown': "⏳ Please wait {} seconds between trades.",
        'referral_link': "🔗 *Your Referral Link*\n\nShare this link with friends:\n`{}`\n\nWhen they join and start trading, you earn **1% of all fees they pay**!\n\n💰 Total referral bonus earned: **${:.2f}**",
        'referral_joined': "🎉 You were referred by a friend! You both get bonuses.",
        'about': "🤖 *MoussaBlvckLion Bot – Your DeFi Command Center*\n\nI am a High‑Water Mark (HWM) trading assistant that tracks your total Net Worth, charges 8% fee only on new all-time high profits, auto‑withdraws the fee to the admin wallet (with your approval), scans Binance Earn for high‑yield bonuses, protects you from scams, and has an emergency lockdown.\n\nCommands:\n/start – Welcome\n/accept – Accept terms\n/connect – Connect your Binance account (step-by-step)\n/history – Last 10 trades\n/balance – Check your wallet\n/networth – Check total USD value (HWM)\n/price <symbol> – Get current price (default BTCUSDT)\n/buy <symbol> <amount> – Buy (e.g., /buy BTCUSDT 50)\n/sell <symbol> <quantity> – Sell (e.g., /sell BTCUSDT 0.001)\n/bonuses – Scan Binance Earn promotions\n/scan <text> – Scan for scams\n/checkwallet <address> – Check scam status\n/lockdown – Emergency pause trading\n/lang – Switch language (English / Français)\n/referral – Get your referral link\n/about – This message",
        'lang_switched': "Language switched to English.",
        'lang_current': "Current language: English.",
    },
    'fr': {
        'welcome': "👋 Bienvenue sur MoussaBlvckLion Bot – votre assistant DeFi.\nEnvoyez /connect pour lier votre compte Binance.",
        'already_registered': "🔐 Vous êtes déjà enregistré. Utilisez /connect pour mettre à jour vos clés.",
        'connect_start': "🔑 Envoyez-moi votre **clé API Binance**.\n_(Votre message sera supprimé pour des raisons de sécurité)_",
        'connect_secret': "🔒 Reçu. Envoyez-moi maintenant votre **clé secrète**.\n_(Votre message sera supprimé)_",
        'connect_success': "✅ Connecté à Binance ! Valeur nette initiale : ${:.2f}\n\n⚠️ Veuillez lire et accepter nos conditions en envoyant : /accept",
        'connect_invalid': "❌ Clés invalides : {}. Veuillez recommencer avec /connect.",
        'connect_only_binance': "❌ Seul Binance est pris en charge pour le moment.",
        'balance': "💰 Solde :\n{}",
        'balance_empty': "💰 Portefeuille vide.",
        'networth': "📊 VN : ${:.2f}\nHWM : ${:.2f}\nNon réalisé : ${:.2f}",
        'price': "📈 {} : ${:.2f}",
        'price_error': "❌ Symbole '{}' introuvable. Essayez BTCUSDT, ETHBUSD, etc.",
        'buy_min': "❌ Le montant minimum est de 10 $ (ou équivalent).",
        'buy_max': "❌ Le montant maximum est de ${} (limite de sécurité).",
        'buy_success': "✅ Achat de {:.6f} {} à ${:.2f}",
        'buy_fill_zero': "⚠️ Ordre exécuté avec 0. Vérifiez votre solde / montant minimum.",
        'buy_failed': "❌ Échec de l'achat : {}",
        'buy_usage': "❌ Utilisation : /buy <symbole> <montant> (ex : /buy BTCUSDT 50)",
        'buy_terms_required': "❌ Vous devez d'abord accepter les conditions. Envoyez /accept.",
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
        'customer_care_only': "⛔ Réservé au service client.",
        'users_list': "📋 Utilisateurs :\n{}",
        'users_empty': "Aucun utilisateur.",
        'resume_usage': "Utilisation : /resume <id>",
        'resume_done': "✅ Utilisateur {} réactivé.",
        'reset_hwm_usage': "Utilisation : /reset_hwm <id>",
        'reset_hwm_done': "✅ HWM réinitialisé à ${:.2f} pour {}.",
        'user_not_found': "Utilisateur introuvable.",
        'terms_accepted': "✅ Vous avez accepté les conditions. Le trading est maintenant activé.",
        'terms_text': "📜 *Conditions d'utilisation*\n\nEn utilisant ce bot, vous acceptez que :\n1. MoussaBlvckLion Bot prélèvera des **frais de 8%** sur les **bénéfices uniquement** (modèle High‑Water Mark).\n2. Les frais seront **automatiquement retirés** de votre compte Binance vers le portefeuille de l'administrateur.\n3. Vous êtes seul responsable de vos décisions de trading.\n4. Ce bot est fourni \"en l'état\" – utilisez-le à vos propres risques.\n\nPour accepter, envoyez : /accept",
        'history_header': "📜 *Dernières 10 transactions*\n",
        'history_empty': "Aucune transaction.",
        'history_line': "{}. {} {} {:.6f} @ ${:.2f} ({})",
        'daily_loss_exceeded': "❌ Limite de perte quotidienne de ${} dépassée. Trading suspendu jusqu'à demain.",
        'terms_required': "❌ Vous devez accepter les conditions. Envoyez /accept.",
        'deposit_alert': "⚠️ *Pic de valeur nette détecté pour l'utilisateur {}*\n\nVN actuelle : ${:.2f}\nVN précédente : ${:.2f}\nAugmentation : ${:.2f} ({:.1f}%)\n\nIl s'agit peut-être d'un dépôt. Cliquez ci-dessous pour réinitialiser le HWM si c'est un dépôt :",
        'deposit_reset_success': "✅ HWM réinitialisé à ${:.2f} pour l'utilisateur {} (dépôt détecté).",
        'cooldown': "⏳ Veuillez attendre {} secondes entre les transactions.",
        'referral_link': "🔗 *Votre lien de parrainage*\n\nPartagez ce lien avec vos amis :\n`{}`\n\nLorsqu'ils rejoignent et commencent à trader, vous gagnez **1% des frais qu'ils paient** !\n\n💰 Bonus de parrainage total : **${:.2f}**",
        'referral_joined': "🎉 Vous avez été parrainé par un ami ! Vous bénéficiez tous les deux de bonus.",
        'about': "🤖 *MoussaBlvckLion Bot – Votre Centre de Commandes DeFi*\n\nJe suis un assistant de trading à High‑Water Mark (HWM) qui suit votre valeur nette totale, prélève 8% de frais uniquement sur les nouveaux bénéfices records, retire automatiquement les frais vers le portefeuille de l'admin (avec votre approbation), analyse Binance Earn pour des bonus à haut rendement, vous protège contre les arnaques et dispose d'un verrouillage d'urgence.\n\nCommandes :\n/start – Accueil\n/accept – Accepter les conditions\n/connect – Connecter votre compte Binance (étape par étape)\n/history – Dernières 10 transactions\n/balance – Voir votre solde\n/networth – Voir la valeur nette (HWM)\n/price <symbole> – Prix actuel (défaut BTCUSDT)\n/buy <symbole> <montant> – Acheter (ex : /buy BTCUSDT 50)\n/sell <symbole> <quantité> – Vendre (ex : /sell BTCUSDT 0.001)\n/bonuses – Analyser les promotions Binance Earn\n/scan <texte> – Analyser un message pour détecter une arnaque\n/checkwallet <adresse> – Vérifier une adresse\n/lockdown – Verrouillage d'urgence\n/lang – Changer de langue (English / Français)\n/referral – Obtenir votre lien de parrainage\n/about – Ce message",
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

# ------------------------- DATABASE -------------------------
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
            terms_accepted INTEGER DEFAULT 0,
            daily_loss REAL DEFAULT 0,
            daily_loss_date TEXT,
            deposit_alert_sent INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            referral_bonus REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Add missing columns safely
        for col in ['terms_accepted', 'daily_loss', 'daily_loss_date', 'deposit_alert_sent', 'referral_code', 'referred_by', 'referral_bonus']:
            try:
                c.execute(f'ALTER TABLE users ADD COLUMN {col}')
            except sqlite3.OperationalError:
                pass
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
        return {
            'telegram_id': row[0], 'exchange': row[1],
            'api_key': decrypt(row[2]), 'secret': decrypt(row[3]),
            'total_profit': row[4], 'fee_paid': row[5],
            'high_water_mark': row[6], 'last_net_worth': row[7],
            'trading_enabled': bool(row[8]),
            'language': row[9] if len(row) > 9 else 'en',
            'terms_accepted': bool(row[10]) if len(row) > 10 else False,
            'daily_loss': row[11] if len(row) > 11 else 0.0,
            'daily_loss_date': row[12] if len(row) > 12 else None,
            'deposit_alert_sent': bool(row[13]) if len(row) > 13 else False,
            'referral_code': row[14] if len(row) > 14 else None,
            'referred_by': row[15] if len(row) > 15 else None,
            'referral_bonus': row[16] if len(row) > 16 else 0.0,
        }
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
        # --- Referral bonus (1% of fee) ---
        c.execute('SELECT referred_by FROM users WHERE telegram_id = ?', (uid,))
        row = c.fetchone()
        if row and row[0]:
            referrer_id = row[0]
            bonus = fee * 0.01
            if bonus > 0:
                c.execute('UPDATE users SET referral_bonus = referral_bonus + ? WHERE telegram_id = ?', (bonus, referrer_id))
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

def accept_terms(uid):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET terms_accepted = 1 WHERE telegram_id = ?', (uid,))
        conn.commit()
        conn.close()

def reset_daily_loss(uid):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET daily_loss = 0, daily_loss_date = ? WHERE telegram_id = ?', (datetime.now().isoformat(), uid))
        conn.commit()
        conn.close()

def update_daily_loss(uid, loss):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET daily_loss = daily_loss + ?, daily_loss_date = ? WHERE telegram_id = ?', (loss, datetime.now().isoformat(), uid))
        conn.commit()
        conn.close()

def reset_deposit_alert(uid):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET deposit_alert_sent = 0 WHERE telegram_id = ?', (uid,))
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

def get_trade_history(uid, limit=10):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT symbol, side, quantity, price, timestamp FROM trades WHERE telegram_id = ? ORDER BY timestamp DESC LIMIT ?', (uid, limit))
        rows = c.fetchall()
        conn.close()
    return rows

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

# ------------------------- BINANCE API -------------------------
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

def get_withdrawal_creds(user):
    if FEE_API_KEY or FEE_SECRET:
        if FEE_API_KEY and FEE_SECRET:
            return FEE_API_KEY, FEE_SECRET
        else:
            logging.critical("🚨 FEE_API_KEY or FEE_SECRET is missing! Withdrawals are DISABLED until fixed.")
            return None, None
    return user['api_key'], user['secret']

def get_best_withdrawal_network(api_key, secret):
    balances = get_balance(api_key, secret)
    if balances.get('BNB', 0) > 0.001: return 'BSC'
    if balances.get('ETH', 0) > 0.001: return 'ERC20'
    if balances.get('TRX', 0) > 0.001: return 'TRC20'
    return 'BSC'

def withdraw_fee_smart(user, amount_usd, address):
    api_key, secret = get_withdrawal_creds(user)
    if api_key is None or secret is None:
        return False, "Withdrawal keys are misconfigured. Contact admin."
    asset = 'USDT'
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
                return withdraw_fee_smart(user, amount_usd, address)
        return False, "Insufficient USDT and failed to convert assets."
    except Exception as e:
        return False, str(e)

# ------------------------- SECURITY -------------------------
SCAM_PATTERNS = [
    r"(?i)validate your wallet", r"(?i)seed phrase", r"(?i)private key",
    r"(?i)connect wallet", r"(?i)free airdrop", r"(?i)claim your reward"
]

def scan_message(text):
    for pattern in SCAM_PATTERNS:
        if re.search(pattern, text):
            return pattern
    return None

# ------------------------- BONUS HUNTER -------------------------
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

# ------------------------- TELEGRAM DECORATORS -------------------------
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
        if not user['terms_accepted']:
            lang = user.get('language', 'en')
            await update.message.reply_text(get_text('terms_required', lang))
            return
        return await func(update, context, user, *args, **kwargs)
    return wrapper

def admin_required(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ Admin only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def customer_care_or_admin_required(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        uid = update.effective_user.id
        if (ADMIN_ID and uid == ADMIN_ID) or (CUSTOMER_CARE_ID and uid == CUSTOMER_CARE_ID):
            return await func(update, context, *args, **kwargs)
        await update.message.reply_text("⛔ Unauthorized.")
        return
    return wrapper

# ------------------------- HANDLERS -------------------------
async def start(update, context):
    uid = update.effective_user.id
    lang = 'fr' if update.effective_user.language_code and update.effective_user.language_code.startswith('fr') else 'en'
    
    # Check for referral code
    ref_code = None
    if context.args and len(context.args) > 0:
        if context.args[0].startswith('ref_'):
            ref_code = context.args[0][4:]
    
    user = get_user(uid)
    if user:
        await update.message.reply_text(get_text('already_registered', lang))
        if not user['terms_accepted']:
            await update.message.reply_text(get_text('terms_text', lang), parse_mode='Markdown')
        return

    # Generate unique referral code
    new_code = uuid.uuid4().hex[:8].upper()
    
    # Find referrer
    referrer_id = None
    if ref_code:
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('SELECT telegram_id FROM users WHERE referral_code = ?', (ref_code,))
            row = c.fetchone()
            conn.close()
            if row:
                referrer_id = row[0]

    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO users (telegram_id, language, referral_code, referred_by) VALUES (?, ?, ?, ?)',
                  (uid, lang, new_code, referrer_id))
        conn.commit()
        conn.close()

    await update.message.reply_text(get_text('welcome', lang))
    if referrer_id:
        await update.message.reply_text(get_text('referral_joined', lang))
    await update.message.reply_text(get_text('terms_text', lang), parse_mode='Markdown')

async def accept_terms(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ Please register first with /start.")
        return
    if user['terms_accepted']:
        await update.message.reply_text("✅ You already accepted the terms.")
        return
    accept_terms(uid)
    lang = user.get('language', 'en')
    await update.message.reply_text(get_text('terms_accepted', lang))

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
        await update.message.reply_text(get_text('terms_text', lang), parse_mode='Markdown')
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
        await update.message.reply_text(get_text('terms_text', lang), parse_mode='Markdown')
        context.user_data.clear()

async def referral(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ Please register with /start first.")
        return
    lang = user.get('language', 'en')
    code = user.get('referral_code')
    if not code:
        code = uuid.uuid4().hex[:8].upper()
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('UPDATE users SET referral_code = ? WHERE telegram_id = ?', (code, uid))
            conn.commit()
            conn.close()
    bonus = user.get('referral_bonus', 0.0)
    link = f"https://t.me/{context.bot.username}?start=ref_{code}"
    await update.message.reply_text(get_text('referral_link', lang).format(link, bonus), parse_mode='Markdown')

async def history(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ Not registered.")
        return
    lang = user.get('language', 'en')
    trades = get_trade_history(uid, 10)
    if not trades:
        await update.message.reply_text(get_text('history_empty', lang))
        return
    lines = [get_text('history_line', lang, i+1, t[0], t[1].capitalize(), t[2], t[3], t[4][:10]) for i, t in enumerate(trades)]
    await update.message.reply_text(get_text('history_header', lang) + "\n".join(lines), parse_mode='Markdown')

async def balance(update, context, user):
    lang = user.get('language', 'en')
    bal = get_balance(user['api_key'], user['secret'])
    if not bal:
        await update.message.reply_text(get_text('balance_empty', lang))
        return
    lines = [f"{k}: {v}" for k, v in list(bal.items())[:10]]
    await update.message.reply_text(get_text('balance', lang).format("\n".join(lines)))

async def networth(update, context, user):
    lang = user.get('language', 'en')
    try:
        nw = get_total_net_worth(user['api_key'], user['secret'])
        prev_nw = user['last_net_worth']
        hwm = user['high_water_mark']

        if prev_nw > 0 and nw > prev_nw * 1.2 and nw > hwm and not user['deposit_alert_sent']:
            increase = nw - prev_nw
            pct = (increase / prev_nw) * 100
            admin_msg = get_text('deposit_alert', 'en', user['telegram_id'], nw, prev_nw, increase, pct)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Reset HWM (Deposit)", callback_data=f"reset_hwm_{user['telegram_id']}")]
            ])
            if ADMIN_ID:
                await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, reply_markup=keyboard, parse_mode='Markdown')
            with db_lock:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute('UPDATE users SET deposit_alert_sent = 1 WHERE telegram_id = ?', (user['telegram_id'],))
                conn.commit()
                conn.close()

        await update.message.reply_text(get_text('networth', lang).format(nw, hwm, nw - hwm))
    except Exception as e: await update.message.reply_text(f"❌ {str(e)[:100]}")

async def sync(update, context, user):
    lang = user.get('language', 'en')
    try:
        nw = get_total_net_worth(user['api_key'], user['secret'])
        update_net_worth(user['telegram_id'], nw)
        await update.message.reply_text(f"✅ " + get_text('networth', lang).split('\n')[0].format(nw))
    except Exception as e: await update.message.reply_text(f"❌ {str(e)[:100]}")

async def price(update, context):
    parts = update.message.text.split()
    raw_symbol = "BTCUSDT"
    if len(parts) >= 2:
        raw_symbol = parts[1].upper()
    uid = update.effective_user.id
    user = get_user(uid)
    lang = user.get('language', 'en') if user else 'en'
    try:
        price = get_price_with_fallback(raw_symbol)
        await update.message.reply_text(get_text('price', lang).format(raw_symbol, price))
    except Exception:
        symbol = resolve_symbol(raw_symbol)
        if not symbol:
            await update.message.reply_text(get_text('price_error', lang).format(raw_symbol))
            return
        try:
            price = get_price_with_fallback(symbol)
            await update.message.reply_text(get_text('price', lang).format(symbol, price))
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

async def buy(update, context, user):
    lang = user.get('language', 'en')
    if context.user_data.get('fee_lock'):
        return await update.message.reply_text(get_text('fee_pending', lang))
    last = context.user_data.get('last_trade_time', 0)
    if time.time() - last < TRADE_COOLDOWN:
        remaining = int(TRADE_COOLDOWN - (time.time() - last))
        return await update.message.reply_text(get_text('cooldown', lang).format(remaining))
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
    if amount > MAX_ORDER_USD: return await update.message.reply_text(get_text('buy_max', lang).format(MAX_ORDER_USD))
    today = datetime.now().isoformat()[:10]
    if user['daily_loss_date'] and user['daily_loss_date'][:10] != today:
        reset_daily_loss(user['telegram_id'])
        user['daily_loss'] = 0.0
    if abs(user['daily_loss']) >= DAILY_LOSS_LIMIT:
        return await update.message.reply_text(get_text('daily_loss_exceeded', lang).format(DAILY_LOSS_LIMIT))
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
            context.user_data['last_trade_time'] = time.time()
            await update.message.reply_text(get_text('buy_success', lang).format(qty, symbol, price))
        else: await update.message.reply_text(get_text('buy_fill_zero', lang))
    except Exception as e: await update.message.reply_text(get_text('buy_failed', lang).format(str(e)[:150]))

async def sell(update, context, user):
    lang = user.get('language', 'en')
    if context.user_data.get('fee_lock'):
        return await update.message.reply_text(get_text('fee_pending', lang))
    last = context.user_data.get('last_trade_time', 0)
    if time.time() - last < TRADE_COOLDOWN:
        remaining = int(TRADE_COOLDOWN - (time.time() - last))
        return await update.message.reply_text(get_text('cooldown', lang).format(remaining))
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
        nw_before = get_total_net_worth(user['api_key'], user['secret'])
        order = binance_request(user['api_key'], user['secret'], '/api/v3/order',
                                {'symbol': symbol, 'side': 'SELL', 'type': 'MARKET', 'quantity': qty}, method='POST')
        filled = float(order.get('executedQty', 0))
        if filled <= 0: return await update.message.reply_text(get_text('sell_zero', lang))
        avg_price = float(order.get('cummulativeQuoteQty', 0)) / filled
        record_trade(user['telegram_id'], symbol, 'SELL', filled, avg_price, filled * avg_price)
        nw_after = get_total_net_worth(user['api_key'], user['secret'])
        profit = nw_after - user['high_water_mark']
        if nw_after < nw_before:
            loss = nw_before - nw_after
            update_daily_loss(user['telegram_id'], loss)
            user = get_user(user['telegram_id'])
            if abs(user['daily_loss']) >= DAILY_LOSS_LIMIT:
                await update.message.reply_text(get_text('daily_loss_exceeded', lang).format(DAILY_LOSS_LIMIT))
        context.user_data['last_trade_time'] = time.time()
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
        success, msg = withdraw_fee_smart(user, pending['fee'], ADMIN_WALLET)
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

# ------------------------- ADMIN / CUSTOMER CARE -------------------------
@customer_care_or_admin_required
async def users_list(update, context):
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

@admin_required
async def resume_user(update, context):
    try:
        uid = int(context.args[0]); set_trading_enabled(uid, True)
        await update.message.reply_text(f"✅ Resumed {uid}.")
    except: await update.message.reply_text("Usage: /resume <id>")

@admin_required
async def reset_hwm(update, context):
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
        reset_deposit_alert(uid)
        await update.message.reply_text(f"✅ HWM reset to ${nw:.2f} for {uid}.")
    except: await update.message.reply_text("Usage: /reset_hwm <id>")

# ------------------------- CALLBACK QUERY -------------------------
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("reset_hwm_"):
        uid = int(data.split("_")[2])
        user = get_user(uid)
        if not user:
            await query.edit_message_text("❌ User not found.")
            return
        nw = get_total_net_worth(user['api_key'], user['secret'])
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('UPDATE users SET high_water_mark = ?, last_net_worth = ? WHERE telegram_id = ?', (nw, nw, uid))
            conn.commit()
            conn.close()
        reset_deposit_alert(uid)
        await query.edit_message_text(f"✅ HWM reset to ${nw:.2f} for user {uid} (deposit confirmed).")

# ------------------------- FLASK DASHBOARD (with Basic Auth) -------------------------
flask_app = Flask(__name__)

def check_auth(username, password):
    return username == DASHBOARD_USER and password == DASHBOARD_PASS

def authenticate():
    return Response(
        'Login required', 401,
        {'WWW-Authenticate': 'Basic realm="MoussaBlvckLion Dashboard"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

@flask_app.route('/')
@requires_auth
def dashboard():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT telegram_id, total_profit, fee_paid, trading_enabled, high_water_mark, last_net_worth FROM users ORDER BY fee_paid DESC')
        rows = c.fetchall()
        c.execute('SELECT COUNT(*) FROM users')
        total_users = c.fetchone()[0]
        c.execute('SELECT SUM(fee_paid) FROM users')
        total_fees = c.fetchone()[0] or 0.0
        conn.close()

    table_rows = ""
    for r in rows:
        status = "✅" if r[3] else "❌"
        table_rows += f"<tr><td>{r[0]}</td><td>${r[1]:.2f}</td><td>${r[2]:.2f}</td><td>{status}</td><td>${r[4]:.2f}</td><td>${r[5]:.2f}</td></tr>"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MoussaBlvckLion Dashboard</title>
        <style>
            body {{ font-family: sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }}
            .card {{ background: #161b22; border-radius: 8px; padding: 20px; margin-bottom: 20px; border: 1px solid #30363d; }}
            h1 {{ color: #58a6ff; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px; border-bottom: 1px solid #30363d; text-align: left; }}
            th {{ background: #21262d; }}
            .stats {{ display: flex; gap: 20px; flex-wrap: wrap; }}
            .stat-box {{ background: #21262d; padding: 15px 25px; border-radius: 6px; }}
        </style>
    </head>
    <body>
        <h1>🦁 MoussaBlvckLion Dashboard</h1>
        <div class="stats">
            <div class="stat-box">👥 Users: {total_users}</div>
            <div class="stat-box">💰 Total Fees Collected: ${total_fees:.2f}</div>
        </div>
        <div class="card">
            <h2>📋 User List</h2>
            <table>
                <tr><th>ID</th><th>Profit</th><th>Fees Paid</th><th>Status</th><th>HWM</th><th>Net Worth</th></tr>
                {table_rows if table_rows else "<tr><td colspan='6'>No users yet.</td></tr>"}
            </table>
        </div>
        <p style="color:#8b949e; font-size:0.8em;">Updated automatically. Bot is live.</p>
    </body>
    </html>
    """
    return render_template_string(html)

# ------------------------- MAIN (with auto-restart) -------------------------
def main():
    init_db()
    threading.Thread(target=lambda: flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000))), daemon=True).start()

    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        logging.error("❌ TELEGRAM_TOKEN is missing or empty. Bot cannot start.")
        return

    while True:
        try:
            # Create a new event loop for each run (fixes "Event loop is closed")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            logging.info("🔄 Starting Telegram bot...")
            app = Application.builder().token(token).read_timeout(30).build()

            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("accept", accept_terms))
            app.add_handler(CommandHandler("lang", lang_command))
            app.add_handler(CommandHandler("connect", connect))
            app.add_handler(CommandHandler("referral", referral))
            app.add_handler(CommandHandler("history", history))
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
            app.add_handler(CallbackQueryHandler(handle_callback))

            logging.info("✅ ULTIMATE BILINGUAL BOT STARTED (English/Français).")
            app.run_polling()

        except Exception as e:
            logging.error(f"❌ Bot crashed: {e}")
            # If the loop is closed, we break and restart the whole while loop anyway
            logging.info("🔄 Restarting in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    main()
