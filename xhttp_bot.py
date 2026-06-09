#!/usr/bin/env python3
"""
ربات تلگرام برای XHTTP Panel
سازنده: Claude
"""

import os
import logging
import asyncio
import aiohttp
import json
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

# ─── تنظیمات ───────────────────────────────────────────────
BOT_TOKEN = "8814779677:AAHQo4zXMu0pGtaF6YyF3zjXOXN69KIEUu0"          # توکن ربات از @BotFather
PANEL_URL = "http://c.chilitay.shop"  # آدرس پنل شما
PANEL_USER = "admin"                            # یوزر پنل
PANEL_PASS = "admin"             # رمز پنل

# اگه میخوای فقط کانال‌ات بتونه استفاده کنه (اختیاری - خالی بذار برای عمومی)
ALLOWED_CHANNEL = "@ChiliTech"   # مثلاً: "@mychannel"  یا خالی

# لاگ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── مراحل conversation ────────────────────────────────────
CHOOSE_PLATFORM, ENTER_TOKEN, ENTER_PROJECT_NAME, CONFIRM = range(4)

PLATFORMS = {
    "railway": {"label": "🚂 Railway", "emoji": "🚂"},
    "fastly":  {"label": "⚡ Fastly",  "emoji": "⚡"},
    "vercel":  {"label": "▲ Vercel",   "emoji": "▲"},
    "netlify": {"label": "🟢 Netlify", "emoji": "🟢"},
    "deno":    {"label": "🦕 Deno",    "emoji": "🦕"},
}

# ─── helper: API پنل ───────────────────────────────────────
class PanelAPI:
    def __init__(self):
        self.base = PANEL_URL.rstrip("/")
        self._access_token = None

    async def login(self) -> bool:
        async with aiohttp.ClientSession() as s:
            try:
                r = await s.post(
                    f"{self.base}/api/v1/auth/login",
                    json={"username": PANEL_USER, "password": PANEL_PASS},
                    timeout=aiohttp.ClientTimeout(total=15)
                )
                data = await r.json()
                self._access_token = data.get("accessToken") or data.get("access_token")
                return bool(self._access_token)
            except Exception as e:
                logger.error(f"Login failed: {e}")
                return False

    def _headers(self):
        return {"Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json"}

    async def add_token(self, platform: str, token_value: str, label: str) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.post(
                f"{self.base}/api/v1/tokens",
                headers=self._headers(),
                json={"platform": platform, "token": token_value, "label": label},
                timeout=aiohttp.ClientTimeout(total=15)
            )
            return await r.json()

    async def test_token(self, token_id: int) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.post(
                f"{self.base}/api/v1/tokens/{token_id}/test",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=20)
            )
            return await r.json()

    async def deploy(self, platform: str, token_id: int, project_name: str) -> dict:
        payload = {
            "tokenId": token_id,
            "projectName": project_name,
            "relayPath": "/api",
        }
        async with aiohttp.ClientSession() as s:
            r = await s.post(
                f"{self.base}/api/v1/deploy/{platform}",
                headers=self._headers(),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            )
            return await r.json()

    async def get_configs(self) -> list:
        async with aiohttp.ClientSession() as s:
            r = await s.get(
                f"{self.base}/api/v1/configs/links",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15)
            )
            data = await r.json()
            return data if isinstance(data, list) else data.get("links", [])

    async def delete_token(self, token_id: int):
        async with aiohttp.ClientSession() as s:
            await s.delete(
                f"{self.base}/api/v1/tokens/{token_id}",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15)
            )

panel = PanelAPI()

# ─── دستورات اصلی ──────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("➕ ساخت کانفیگ جدید", callback_data="new_config")],
        [InlineKeyboardButton("❓ راهنما", callback_data="help")],
    ]
    await update.message.reply_text(
        "👋 سلام!\n\n"
        "این ربات برای شما کانفیگ **VLESS+XHTTP** میسازه.\n\n"
        "🔑 کافیه توکن API پلتفرم ابری‌تون رو بدید، "
        "بقیه‌ش خودکاره!\n\n"
        "📌 پلتفرم‌های پشتیبانی‌شده:\n"
        "• Railway | Fastly | Vercel | Netlify | Deno",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *راهنمای استفاده:*\n\n"
        "1️⃣ /newconfig — شروع ساخت کانفیگ\n"
        "2️⃣ پلتفرم رو انتخاب کن\n"
        "3️⃣ توکن API اون پلتفرم رو بفرست\n"
        "4️⃣ یه نام برای پروژه بده\n"
        "5️⃣ تأیید کن — کانفیگ آماده میشه!\n\n"
        "🔑 *چطور توکن بگیریم؟*\n"
        "• Railway: [railway.app/account/tokens](https://railway.app/account/tokens)\n"
        "• Fastly: داشبورد ← Account ← API tokens\n"
        "• Vercel: [vercel.com/account/tokens](https://vercel.com/account/tokens)\n"
        "• Netlify: User settings ← Applications ← New token\n"
        "• Deno: [dash.deno.com/account](https://dash.deno.com/account)\n\n"
        "/cancel — لغو عملیات جاری"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode="Markdown",
                                                       disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, parse_mode="Markdown",
                                        disable_web_page_preview=True)

# ─── conversation: ساخت کانفیگ ────────────────────────────
async def new_config_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """شروع — انتخاب پلتفرم"""
    query = update.callback_query
    if query:
        await query.answer()
        msg = query.message
    else:
        msg = update.message

    kb = [
        [InlineKeyboardButton(PLATFORMS[p]["label"], callback_data=f"plat_{p}")]
        for p in PLATFORMS
    ]
    kb.append([InlineKeyboardButton("❌ لغو", callback_data="cancel")])

    await msg.reply_text(
        "🌐 *پلتفرم مورد نظرت رو انتخاب کن:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CHOOSE_PLATFORM

async def choose_platform(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.message.reply_text("❌ عملیات لغو شد.")
        return ConversationHandler.END

    platform = query.data.replace("plat_", "")
    ctx.user_data["platform"] = platform
    emoji = PLATFORMS[platform]["emoji"]

    await query.message.reply_text(
        f"{emoji} *{platform.capitalize()}* انتخاب شد.\n\n"
        f"🔑 حالا **توکن API** {platform.capitalize()} رو برام بفرست:",
        parse_mode="Markdown"
    )
    return ENTER_TOKEN

async def enter_token(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    token_value = update.message.text.strip()

    # حذف پیام کاربر برای امنیت
    try:
        await update.message.delete()
    except Exception:
        pass

    if len(token_value) < 8:
        await update.message.reply_text("⚠️ توکن خیلی کوتاهه. دوباره بفرست:")
        return ENTER_TOKEN

    ctx.user_data["token_value"] = token_value

    # نام پیش‌فرض پروژه
    user = update.effective_user
    default_name = f"tg-{user.id}-{int(datetime.now().timestamp()) % 10000}"
    ctx.user_data["default_name"] = default_name

    await update.message.reply_text(
        f"✅ توکن دریافت شد.\n\n"
        f"📝 یه **نام** برای پروژه بنویس:\n"
        f"_(فقط حروف کوچک انگلیسی، عدد و خط‌تیره)_\n\n"
        f"پیش‌فرض: `{default_name}`\n"
        f"_(برای استفاده از پیش‌فرض، همین رو بفرست)_",
        parse_mode="Markdown"
    )
    return ENTER_PROJECT_NAME

async def enter_project_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip().lower()

    if not re.match(r'^[a-z0-9\-]{3,30}$', name):
        await update.message.reply_text(
            "⚠️ نام نامعتبره!\n"
            "فقط حروف کوچک انگلیسی، عدد و خط‌تیره (۳ تا ۳۰ کاراکتر).\n"
            "دوباره بنویس:"
        )
        return ENTER_PROJECT_NAME

    ctx.user_data["project_name"] = name
    platform = ctx.user_data["platform"]
    emoji = PLATFORMS[platform]["emoji"]

    kb = [
        [
            InlineKeyboardButton("✅ تأیید و دیپلوی", callback_data="confirm"),
            InlineKeyboardButton("❌ لغو", callback_data="cancel"),
        ]
    ]

    await update.message.reply_text(
        f"📋 *خلاصه:*\n\n"
        f"• پلتفرم: {emoji} {platform.capitalize()}\n"
        f"• نام پروژه: `{name}`\n\n"
        f"شروع کنم؟",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CONFIRM

async def confirm_deploy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.message.reply_text("❌ عملیات لغو شد.")
        return ConversationHandler.END

    platform = ctx.user_data["platform"]
    token_value = ctx.user_data["token_value"]
    project_name = ctx.user_data["project_name"]
    user = update.effective_user
    label = f"tg-user-{user.id}"

    msg = await query.message.reply_text("🔄 در حال اتصال به پنل...")

    # ─ login ─
    logged = await panel.login()
    if not logged:
        await msg.edit_text("❌ خطا در اتصال به پنل. لطفاً بعداً امتحان کن.")
        return ConversationHandler.END

    # ─ ثبت توکن ─
    await msg.edit_text("🔑 در حال ثبت توکن...")
    try:
        tok_resp = await panel.add_token(platform, token_value, label)
        token_id = tok_resp.get("id") or tok_resp.get("token", {}).get("id")
        if not token_id:
            raise ValueError(f"No token ID in response: {tok_resp}")
    except Exception as e:
        logger.error(f"add_token error: {e}")
        await msg.edit_text("❌ خطا در ثبت توکن. مطمئن شو توکن معتبره.")
        return ConversationHandler.END

    # ─ تست توکن ─
    await msg.edit_text("🧪 در حال تست اعتبار توکن...")
    try:
        test = await panel.test_token(token_id)
        valid = test.get("valid") or test.get("status") == "valid"
        if not valid:
            await panel.delete_token(token_id)
            await msg.edit_text(
                "❌ توکن معتبر نیست!\n\n"
                "مطمئن شو توکن رو درست کپی کردی و اکانت پلتفرم مشکلی نداره."
            )
            return ConversationHandler.END
    except Exception as e:
        logger.warning(f"test_token warning: {e}")

    # ─ دیپلوی ─
    await msg.edit_text(
        f"🚀 در حال دیپلوی روی {platform.capitalize()}...\n"
        f"_(این ممکنه ۱ تا ۳ دقیقه طول بکشه)_",
        parse_mode="Markdown"
    )
    try:
        deploy_resp = await panel.deploy(platform, token_id, project_name)
    except asyncio.TimeoutError:
        await msg.edit_text(
            "⏱ دیپلوی داره طول میکشه.\n"
            "معمولاً ۲-۳ دقیقه بعد آماده میشه.\n"
            "کانفیگ رو از /getconfigs بگیر."
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"deploy error: {e}")
        await msg.edit_text("❌ خطا در دیپلوی. لطفاً بعداً امتحان کن.")
        return ConversationHandler.END

    # ─ گرفتن کانفیگ ─
    await asyncio.sleep(3)
    await msg.edit_text("📡 در حال دریافت کانفیگ...")
    try:
        configs = await panel.get_configs()
        new_configs = [c for c in configs if project_name in str(c.get("name", ""))
                       or project_name in str(c.get("url", ""))
                       or platform in str(c.get("platform", "")).lower()]
        if not new_configs and configs:
            new_configs = [configs[-1]]  # آخرین کانفیگ
    except Exception as e:
        logger.error(f"get_configs error: {e}")
        new_configs = []

    if not new_configs:
        # اگه کانفیگ پیدا نشد، از deploy_resp استخراج کن
        vless = (deploy_resp.get("config") or deploy_resp.get("vless")
                 or deploy_resp.get("link") or deploy_resp.get("connectionLink"))
    else:
        config_obj = new_configs[0]
        vless = (config_obj.get("vless") or config_obj.get("link")
                 or config_obj.get("config") or config_obj.get("connectionLink"))

    # ─ پاسخ به کاربر ─
    if vless and vless.startswith("vless://"):
        await msg.edit_text(
            f"✅ *کانفیگ آماده‌ست!*\n\n"
            f"پلتفرم: {PLATFORMS[platform]['emoji']} {platform.capitalize()}\n"
            f"پروژه: `{project_name}`\n\n"
            f"📋 *کانفیگ VLESS:*\n"
            f"`{vless}`\n\n"
            f"_کانفیگ رو کپی کن و توی v2rayNG یا هر کلاینت دیگه‌ای وارد کن._",
            parse_mode="Markdown"
        )
    else:
        await msg.edit_text(
            f"✅ دیپلوی موفق بود!\n\n"
            f"پروژه `{project_name}` روی {platform.capitalize()} ساخته شد.\n\n"
            f"🔍 برای گرفتن کانفیگ /getconfigs رو بفرست.",
            parse_mode="Markdown"
        )

    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ عملیات لغو شد.")
    return ConversationHandler.END

# ─── دستور /getconfigs ─────────────────────────────────────
async def get_configs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 در حال دریافت کانفیگ‌ها...")

    logged = await panel.login()
    if not logged:
        await msg.edit_text("❌ خطا در اتصال به پنل.")
        return

    try:
        configs = await panel.get_configs()
    except Exception as e:
        await msg.edit_text(f"❌ خطا: {e}")
        return

    if not configs:
        await msg.edit_text("📭 هنوز کانفیگی وجود نداره.\n/newconfig برای ساخت کانفیگ.")
        return

    text = f"📋 *{len(configs)} کانفیگ موجود:*\n\n"
    for i, c in enumerate(configs[:5], 1):
        vless = (c.get("vless") or c.get("link") or c.get("config") or c.get("connectionLink") or "")
        platform = c.get("platform", "نامشخص")
        name = c.get("name") or c.get("projectName") or f"کانفیگ {i}"
        if vless.startswith("vless://"):
            text += f"*{i}. {name}* ({platform})\n`{vless}`\n\n"
        else:
            text += f"*{i}. {name}* ({platform}) — کانفیگ موجود نیست\n\n"

    if len(configs) > 5:
        text += f"_... و {len(configs)-5} کانفیگ دیگه_"

    await msg.edit_text(text, parse_mode="Markdown")

# ─── callback ──────────────────────────────────────────────
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "help":
        await help_cmd(update, ctx)
    elif query.data == "new_config":
        await new_config_start(update, ctx)

# ─── main ──────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("newconfig", new_config_start),
            CallbackQueryHandler(new_config_start, pattern="^new_config$"),
        ],
        states={
            CHOOSE_PLATFORM: [CallbackQueryHandler(choose_platform, pattern="^(plat_|cancel)")],
            ENTER_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_token)],
            ENTER_PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_project_name)],
            CONFIRM: [CallbackQueryHandler(confirm_deploy, pattern="^(confirm|cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("getconfigs", get_configs_cmd))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("ربات شروع به کار کرد...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
