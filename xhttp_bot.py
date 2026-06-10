#!/usr/bin/env python3
"""
ربات تلگرام برای XHTTP Panel
نسخه کامل با سیستم پرداخت، صف، و مدیریت کاربران
"""

import logging
import asyncio
import aiohttp
import json
import re
import sqlite3
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

# ─── تنظیمات ───────────────────────────────────────────────
BOT_TOKEN   = "YOUR_BOT_TOKEN"
PANEL_URL   = "http://c.chilitay.shop"
PANEL_USER  = "admin"
PANEL_PASS  = "admin"
ADMIN_ID    = 1267941075
CARD_NUMBER = "6037998214674474"
CARD_OWNER  = "صاحب ربات"
DB_PATH     = os.path.expanduser("~/crconf/bot_data.db")

# پلن‌ها
PLANS = {
    "plan_2": {"configs": 2,  "price": 100_000,  "label": "۲ کانفیگ — ۱۰۰,۰۰۰ تومان"},
    "plan_4": {"configs": 4,  "price": 200_000,  "label": "۴ کانفیگ — ۲۰۰,۰۰۰ تومان"},
    "plan_10":{"configs": 10, "price": 500_000,  "label": "۱۰ کانفیگ — ۵۰۰,۰۰۰ تومان"},
}

COOLDOWN_MINUTES = 10  # فاصله بین دو کانفیگ

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── مراحل conversation ────────────────────────────────────
(CHOOSE_PLATFORM, ENTER_TOKEN, ENTER_PROJECT_NAME, CONFIRM,
 SEND_RECEIPT, CHOOSE_PLAN) = range(6)

PLATFORMS = {
    "railway": {"label": "🚂 Railway", "emoji": "🚂",
                "token_fields": {"apiToken": "توکن API Railway"}},
    "fastly":  {"label": "⚡ Fastly",  "emoji": "⚡",
                "token_fields": {"apiToken": "توکن API Fastly"}},
    "vercel":  {"label": "▲ Vercel",   "emoji": "▲",
                "token_fields": {"token": "توکن API Vercel"}},
    "netlify": {"label": "🟢 Netlify", "emoji": "🟢",
                "token_fields": {"token": "توکن API Netlify"}},
    "deno":    {"label": "🦕 Deno",    "emoji": "🦕",
                "token_fields": {"apiToken": "توکن API Deno", "orgName": "نام Organization"}},
}

# ─── دیتابیس ───────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            credits     INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS configs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            platform    TEXT,
            project_name TEXT,
            deploy_id   INTEGER,
            config_link TEXT,
            deploy_url  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            plan_key    TEXT,
            amount      INTEGER,
            configs     INTEGER,
            status      TEXT DEFAULT 'pending',
            receipt_file_id TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, credits FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "username": row[1], "credits": row[2]}
    return None

def ensure_user(user_id: int, username: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
              (user_id, username or ""))
    c.execute("UPDATE users SET username=? WHERE user_id=?", (username or "", user_id))
    conn.commit()
    conn.close()

def add_credits(user_id: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET credits = credits + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def use_credit(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT credits FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row or row[0] <= 0:
        conn.close()
        return False
    conn.execute("UPDATE users SET credits = credits - 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return True

def save_config(user_id: int, platform: str, project_name: str,
                deploy_id: int, config_link: str, deploy_url: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO configs (user_id, platform, project_name, deploy_id, config_link, deploy_url)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, platform, project_name, deploy_id, config_link, deploy_url))
    conn.commit()
    conn.close()

def get_user_configs(user_id: int) -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT platform, project_name, config_link, deploy_url, created_at
        FROM configs WHERE user_id=? ORDER BY created_at DESC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_last_config_time(user_id: int) -> datetime | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT created_at FROM configs WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
              (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return datetime.fromisoformat(row[0])
    return None

def save_payment(user_id: int, plan_key: str, receipt_file_id: str) -> int:
    plan = PLANS[plan_key]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO payments (user_id, plan_key, amount, configs, receipt_file_id)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, plan_key, plan["price"], plan["configs"], receipt_file_id))
    payment_id = c.lastrowid
    conn.commit()
    conn.close()
    return payment_id

def confirm_payment(payment_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, configs, status FROM payments WHERE id=?", (payment_id,))
    row = c.fetchone()
    if not row or row[2] != "pending":
        conn.close()
        return None
    conn.execute("UPDATE payments SET status='confirmed' WHERE id=?", (payment_id,))
    conn.commit()
    conn.close()
    return {"user_id": row[0], "configs": row[1]}

def reject_payment(payment_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, status FROM payments WHERE id=?", (payment_id,))
    row = c.fetchone()
    if not row or row[1] != "pending":
        conn.close()
        return None
    conn.execute("UPDATE payments SET status='rejected' WHERE id=?", (payment_id,))
    conn.commit()
    conn.close()
    return {"user_id": row[0]}

# ─── صف دیپلوی ─────────────────────────────────────────────
deploy_lock = asyncio.Lock()

# ─── API پنل ───────────────────────────────────────────────
class PanelAPI:
    def __init__(self):
        self.base = PANEL_URL.rstrip("/")
        self._token = None

    async def login(self) -> bool:
        async with aiohttp.ClientSession() as s:
            try:
                r = await s.post(
                    f"{self.base}/api/v1/auth/login",
                    json={"username": PANEL_USER, "password": PANEL_PASS},
                    timeout=aiohttp.ClientTimeout(total=15)
                )
                data = await r.json()
                self._token = data.get("accessToken")
                return bool(self._token)
            except Exception as e:
                logger.error(f"Login: {e}")
                return False

    def _h(self):
        return {"Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json"}

    async def get_server_domain(self) -> str:
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/api/v1/configs/server-status",
                            headers=self._h(), timeout=aiohttp.ClientTimeout(total=10))
            return (await r.json()).get("domain", "")

    async def add_token(self, platform: str, token_data: dict, label: str) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.post(f"{self.base}/api/v1/tokens", headers=self._h(),
                             json={"platform": platform, "label": label, "tokenData": token_data},
                             timeout=aiohttp.ClientTimeout(total=15))
            return await r.json()

    async def test_token(self, token_id: int) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.post(f"{self.base}/api/v1/tokens/{token_id}/test",
                             headers=self._h(), timeout=aiohttp.ClientTimeout(total=30))
            return await r.json()

    async def deploy(self, platform: str, token_id: int,
                     project_name: str, target_domain: str) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.post(f"{self.base}/api/v1/deploy/{platform}", headers=self._h(),
                             json={"tokenId": token_id, "projectName": project_name,
                                   "targetDomain": target_domain,
                                   "relayPath": "/api", "publicPath": "/api"},
                             timeout=aiohttp.ClientTimeout(total=180))
            return await r.json()

    async def get_deploy(self, deploy_id: int) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/api/v1/deploy/{deploy_id}",
                            headers=self._h(), timeout=aiohttp.ClientTimeout(total=15))
            return await r.json()

    async def delete_token(self, token_id: int):
        async with aiohttp.ClientSession() as s:
            await s.delete(f"{self.base}/api/v1/tokens/{token_id}",
                           headers=self._h(), timeout=aiohttp.ClientTimeout(total=15))

def extract_config_link(deploy: dict) -> str:
    try:
        cj = deploy.get("config_json")
        if isinstance(cj, str):
            cj = json.loads(cj)
        if isinstance(cj, dict):
            link = cj.get("configLink", "")
            if link and link.startswith("vless://"):
                return link
    except Exception:
        pass
    return ""

panel = PanelAPI()

# ─── کیبورد اصلی ───────────────────────────────────────────
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ساخت کانفیگ جدید", callback_data="new_config")],
        [InlineKeyboardButton("📋 کانفیگ‌های من",     callback_data="my_configs")],
        [InlineKeyboardButton("💳 خرید اعتبار",       callback_data="buy_credit")],
        [InlineKeyboardButton("👤 حساب من",           callback_data="my_account")],
    ])

# ─── /start ────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username)
    await update.message.reply_text(
        f"👋 سلام {user.first_name}!\n\n"
        "به ربات ساخت کانفیگ *VLESS+XHTTP* خوش اومدی.\n\n"
        "از منوی زیر استفاده کن:",
        parse_mode="Markdown",
        reply_markup=main_menu_kb()
    )

async def main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    ensure_user(user.id, user.username)
    await query.message.reply_text(
        "🏠 منوی اصلی:",
        reply_markup=main_menu_kb()
    )

# ─── حساب من ───────────────────────────────────────────────
async def my_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    u = get_user(user.id)
    configs = get_user_configs(user.id)
    last_time = get_last_config_time(user.id)

    cooldown_msg = ""
    if last_time:
        diff = datetime.utcnow() - last_time
        remaining = timedelta(minutes=COOLDOWN_MINUTES) - diff
        if remaining.total_seconds() > 0:
            mins = int(remaining.total_seconds() // 60)
            secs = int(remaining.total_seconds() % 60)
            cooldown_msg = f"\n⏳ تا کانفیگ بعدی: {mins}م {secs}ث"

    await query.message.reply_text(
        f"👤 *حساب شما*\n\n"
        f"• آیدی: `{user.id}`\n"
        f"• اعتبار باقی‌مانده: *{u['credits'] if u else 0}* کانفیگ\n"
        f"• تعداد کانفیگ‌های ساخته‌شده: *{len(configs)}*"
        f"{cooldown_msg}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]
        ])
    )

# ─── کانفیگ‌های من ─────────────────────────────────────────
async def my_configs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    configs = get_user_configs(user.id)

    if not configs:
        await query.message.reply_text(
            "📭 هنوز کانفیگی نساختی.\n"
            "از منوی اصلی کانفیگ جدید بساز.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ ساخت کانفیگ", callback_data="new_config")],
                [InlineKeyboardButton("🏠 منوی اصلی",   callback_data="main_menu")],
            ])
        )
        return

    text = f"📋 *کانفیگ‌های شما ({len(configs)} عدد):*\n\n"
    for i, (platform, name, config_link, deploy_url, created_at) in enumerate(configs[:5], 1):
        emoji = PLATFORMS.get(platform, {}).get("emoji", "🌐")
        date = created_at[:10] if created_at else ""
        if config_link:
            text += f"*{i}. {emoji} {name}* — {date}\n`{config_link}`\n\n"
        else:
            text += f"*{i}. {emoji} {name}* — {date}\n_{deploy_url}_\n\n"

    if len(configs) > 5:
        text += f"_... و {len(configs)-5} کانفیگ دیگه_"

    await query.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]
        ])
    )

# ─── خرید اعتبار ───────────────────────────────────────────
async def buy_credit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    kb = [
        [InlineKeyboardButton(PLANS["plan_2"]["label"],  callback_data="plan_plan_2")],
        [InlineKeyboardButton(PLANS["plan_4"]["label"],  callback_data="plan_plan_4")],
        [InlineKeyboardButton(PLANS["plan_10"]["label"], callback_data="plan_plan_10")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="main_menu")],
    ]
    await query.message.reply_text(
        "💳 *خرید اعتبار*\n\n"
        "یکی از پلن‌های زیر رو انتخاب کن:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CHOOSE_PLAN

async def choose_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    plan_key = query.data.replace("plan_", "")
    if plan_key not in PLANS:
        return ConversationHandler.END

    plan = PLANS[plan_key]
    ctx.user_data["selected_plan"] = plan_key

    price_formatted = f"{plan['price']:,}".replace(",", "،")

    await query.message.reply_text(
        f"💳 *اطلاعات پرداخت*\n\n"
        f"پلن: {plan['label']}\n"
        f"مبلغ: *{price_formatted} تومان*\n\n"
        f"شماره کارت:\n"
        f"`{CARD_NUMBER}`\n"
        f"به نام: {CARD_OWNER}\n\n"
        f"پس از واریز، رسید (عکس یا متن) رو اینجا بفرست:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 برگشت", callback_data="buy_credit")]
        ])
    )
    return SEND_RECEIPT

async def receive_receipt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    plan_key = ctx.user_data.get("selected_plan")
    if not plan_key:
        return ConversationHandler.END

    plan = PLANS[plan_key]

    # رسید عکس یا متن
    if update.message.photo:
        receipt_file_id = update.message.photo[-1].file_id
        receipt_type = "photo"
    elif update.message.document:
        receipt_file_id = update.message.document.file_id
        receipt_type = "document"
    elif update.message.text:
        receipt_file_id = update.message.text
        receipt_type = "text"
    else:
        await update.message.reply_text("⚠️ لطفاً رسید رو به صورت عکس یا متن بفرست.")
        return SEND_RECEIPT

    payment_id = save_payment(user.id, plan_key, receipt_file_id)

    # ارسال به ادمین
    price_formatted = f"{plan['price']:,}".replace(",", "،")
    admin_text = (
        f"💰 *درخواست پرداخت جدید*\n\n"
        f"کاربر: [{user.first_name}](tg://user?id={user.id})\n"
        f"آیدی: `{user.id}`\n"
        f"پلن: {plan['label']}\n"
        f"مبلغ: {price_formatted} تومان\n"
        f"شناسه پرداخت: `{payment_id}`"
    )
    kb_admin = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأیید", callback_data=f"pay_ok_{payment_id}"),
            InlineKeyboardButton("❌ رد",    callback_data=f"pay_no_{payment_id}"),
        ]
    ])

    try:
        if receipt_type == "photo":
            await ctx.bot.send_photo(ADMIN_ID, receipt_file_id,
                                     caption=admin_text, parse_mode="Markdown",
                                     reply_markup=kb_admin)
        elif receipt_type == "document":
            await ctx.bot.send_document(ADMIN_ID, receipt_file_id,
                                        caption=admin_text, parse_mode="Markdown",
                                        reply_markup=kb_admin)
        else:
            await ctx.bot.send_message(ADMIN_ID,
                                       admin_text + f"\n\nرسید متنی:\n`{receipt_file_id}`",
                                       parse_mode="Markdown", reply_markup=kb_admin)
    except Exception as e:
        logger.error(f"Send to admin: {e}")

    await update.message.reply_text(
        "✅ رسیدت دریافت شد!\n\n"
        "بعد از تأیید ادمین، اعتبارت شارژ میشه و میتونی کانفیگ بسازی.\n"
        "معمولاً زیر ۳۰ دقیقه تأیید میشه.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]
        ])
    )
    return ConversationHandler.END

# ─── تأیید/رد پرداخت توسط ادمین ───────────────────────────
async def admin_payment_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        return

    data = query.data
    if data.startswith("pay_ok_"):
        payment_id = int(data.replace("pay_ok_", ""))
        result = confirm_payment(payment_id)
        if result:
            add_credits(result["user_id"], result["configs"])
            await query.edit_message_caption(
                caption=query.message.caption + "\n\n✅ *تأیید شد*",
                parse_mode="Markdown"
            ) if query.message.caption else await query.edit_message_text(
                query.message.text + "\n\n✅ *تأیید شد*", parse_mode="Markdown"
            )
            try:
                await ctx.bot.send_message(
                    result["user_id"],
                    f"✅ *پرداخت شما تأیید شد!*\n\n"
                    f"{result['configs']} کانفیگ به حسابت اضافه شد.\n"
                    f"از منوی اصلی کانفیگ بساز 🎉",
                    parse_mode="Markdown",
                    reply_markup=main_menu_kb()
                )
            except Exception as e:
                logger.error(f"Notify user: {e}")
        else:
            await query.answer("این پرداخت قبلاً پردازش شده.", show_alert=True)

    elif data.
