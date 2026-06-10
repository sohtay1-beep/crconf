#!/usr/bin/env python3
"""
ربات تلگرام برای XHTTP Panel
نسخه نهایی — با سورس کد کامل پنل
"""

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
BOT_TOKEN  = "YOUR_TELEGRAM_BOT_TOKEN"   # از @BotFather بگیر
PANEL_URL  = "http://c.chilitay.shop"
PANEL_USER = "admin"
PANEL_PASS = "admin"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── مراحل conversation ────────────────────────────────────
(CHOOSE_PLATFORM, ENTER_TOKEN, ENTER_EXTRA,
 ENTER_PROJECT_NAME, CONFIRM) = range(5)

# ─── پلتفرم‌ها و فیلدهای مورد نیاز ────────────────────────
PLATFORMS = {
    "railway": {
        "label": "🚂 Railway",
        "emoji": "🚂",
        "token_fields": {"apiToken": "توکن API Railway"},
        "extra_fields": {}
    },
    "fastly": {
        "label": "⚡ Fastly",
        "emoji": "⚡",
        "token_fields": {"apiToken": "توکن API Fastly"},
        "extra_fields": {}
    },
    "vercel": {
        "label": "▲ Vercel",
        "emoji": "▲",
        "token_fields": {"token": "توکن API Vercel"},
        "extra_fields": {}
    },
    "netlify": {
        "label": "🟢 Netlify",
        "emoji": "🟢",
        "token_fields": {"token": "توکن API Netlify"},
        "extra_fields": {}
    },
    "deno": {
        "label": "🦕 Deno",
        "emoji": "🦕",
        "token_fields": {"apiToken": "توکن API Deno", "orgName": "نام Organization"},
        "extra_fields": {}
    },
}

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
                logger.error(f"Login failed: {e}")
                return False

    def _h(self):
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json"
        }

    async def add_token(self, platform: str, token_data: dict, label: str) -> dict:
        """token_data فیلد درست هر پلتفرم رو داره"""
        async with aiohttp.ClientSession() as s:
            r = await s.post(
                f"{self.base}/api/v1/tokens",
                headers=self._h(),
                json={
                    "platform": platform,
                    "label": label,
                    "tokenData": token_data
                },
                timeout=aiohttp.ClientTimeout(total=15)
            )
            return await r.json()

    async def test_token(self, token_id: int) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.post(
                f"{self.base}/api/v1/tokens/{token_id}/test",
                headers=self._h(),
                timeout=aiohttp.ClientTimeout(total=30)
            )
            return await r.json()

    async def get_server_domain(self) -> str:
        """دامنه سرور رو از status میگیره"""
        async with aiohttp.ClientSession() as s:
            r = await s.get(
                f"{self.base}/api/v1/configs/server-status",
                headers=self._h(),
                timeout=aiohttp.ClientTimeout(total=10)
            )
            data = await r.json()
            return data.get("domain", "")

    async def deploy(self, platform: str, token_id: int,
                     project_name: str, target_domain: str) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.post(
                f"{self.base}/api/v1/deploy/{platform}",
                headers=self._h(),
                json={
                    "tokenId": token_id,
                    "projectName": project_name,
                    "targetDomain": target_domain,
                    "relayPath": "/api",
                    "publicPath": "/api",
                },
                timeout=aiohttp.ClientTimeout(total=180)
            )
            return await r.json()

    async def get_deploy(self, deploy_id: int) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.get(
                f"{self.base}/api/v1/deploy/{deploy_id}",
                headers=self._h(),
                timeout=aiohttp.ClientTimeout(total=15)
            )
            return await r.json()

    async def get_deploys(self) -> list:
        async with aiohttp.ClientSession() as s:
            r = await s.get(
                f"{self.base}/api/v1/deploy",
                headers=self._h(),
                timeout=aiohttp.ClientTimeout(total=15)
            )
            data = await r.json()
            return data if isinstance(data, list) else []

    async def delete_token(self, token_id: int):
        async with aiohttp.ClientSession() as s:
            await s.delete(
                f"{self.base}/api/v1/tokens/{token_id}",
                headers=self._h(),
                timeout=aiohttp.ClientTimeout(total=15)
            )

def extract_config_link(deploy: dict) -> str:
    """کانفیگ رو از config_json دیپلوی میخونه — همونطور که پنل ذخیره میکنه"""
    try:
        config_json = deploy.get("config_json")
        if config_json:
            if isinstance(config_json, str):
                config_json = json.loads(config_json)
            link = config_json.get("configLink", "")
            if link and link.startswith("vless://"):
                return link
    except Exception:
        pass
    return ""

panel = PanelAPI()

# ─── /start ────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("➕ ساخت کانفیگ جدید", callback_data="new_config")],
        [InlineKeyboardButton("📋 کانفیگ‌های موجود", callback_data="list_configs")],
        [InlineKeyboardButton("❓ راهنما", callback_data="help")],
    ]
    await update.message.reply_text(
        "👋 سلام!\n\n"
        "این ربات برای شما کانفیگ *VLESS+XHTTP* میسازه.\n\n"
        "🔑 توکن API پلتفرم ابری‌تون رو بدید، بقیه‌ش خودکاره!\n\n"
        "📌 پلتفرم‌ها:\n"
        "Railway | Fastly | Vercel | Netlify | Deno",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *راهنما:*\n\n"
        "1️⃣ /newconfig — ساخت کانفیگ جدید\n"
        "2️⃣ پلتفرم رو انتخاب کن\n"
        "3️⃣ توکن API بفرست\n"
        "4️⃣ نام پروژه بده\n"
        "5️⃣ تأیید کن — کانفیگ آماده!\n\n"
        "🔑 *گرفتن توکن:*\n"
        "• Railway: railway.app/account/tokens\n"
        "• Fastly: Dashboard → Account → API tokens\n"
        "• Vercel: vercel.com/account/tokens\n"
        "• Netlify: User settings → Applications\n"
        "• Deno: dash.deno.com/account\n\n"
        "/getconfigs — لیست کانفیگ‌های فعال\n"
        "/cancel — لغو عملیات"
    )
    msg = update.callback_query.message if update.callback_query else update.message
    if update.callback_query:
        await update.callback_query.answer()
    await msg.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)

# ─── conversation ───────────────────────────────────────────
async def new_config_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        msg = query.message
    else:
        msg = update.message

    kb = [[InlineKeyboardButton(PLATFORMS[p]["label"], callback_data=f"plat_{p}")]
          for p in PLATFORMS]
    kb.append([InlineKeyboardButton("❌ لغو", callback_data="cancel")])

    await msg.reply_text(
        "🌐 *پلتفرم رو انتخاب کن:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CHOOSE_PLATFORM

async def choose_platform(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.message.reply_text("❌ لغو شد.")
        return ConversationHandler.END

    platform = query.data.replace("plat_", "")
    ctx.user_data["platform"] = platform
    ctx.user_data["token_data"] = {}
    ctx.user_data["token_fields_remaining"] = list(
        PLATFORMS[platform]["token_fields"].keys()
    )

    # شروع جمع‌آوری فیلدهای توکن
    return await ask_next_token_field(update, ctx, query.message)

async def ask_next_token_field(update, ctx, msg):
    platform = ctx.user_data["platform"]
    fields_remaining = ctx.user_data["token_fields_remaining"]

    if not fields_remaining:
        # همه فیلدها جمع شدن — برو به نام پروژه
        user = update.effective_user or update.callback_query.from_user
        default_name = f"tg-{user.id % 9999}-{int(datetime.now().timestamp()) % 9999}"
        ctx.user_data["default_name"] = default_name
        await msg.reply_text(
            f"✅ اطلاعات دریافت شد.\n\n"
            f"📝 نام پروژه رو بنویس:\n"
            f"_(حروف کوچک، عدد، خط‌تیره — ۳ تا ۳۰ کاراکتر)_\n\n"
            f"پیش‌فرض: `{default_name}`",
            parse_mode="Markdown"
        )
        return ENTER_PROJECT_NAME

    field_key = fields_remaining[0]
    field_label = PLATFORMS[platform]["token_fields"][field_key]
    emoji = PLATFORMS[platform]["emoji"]

    await msg.reply_text(
        f"{emoji} *{platform.capitalize()}*\n\n"
        f"🔑 {field_label} رو بفرست:\n"
        f"_(پیام بعد از دریافت حذف میشه)_",
        parse_mode="Markdown"
    )
    return ENTER_TOKEN

async def enter_token_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass

    if len(value) < 3:
        await update.message.reply_text("⚠️ خیلی کوتاهه. دوباره بفرست:")
        return ENTER_TOKEN

    platform = ctx.user_data["platform"]
    fields_remaining = ctx.user_data["token_fields_remaining"]
    field_key = fields_remaining.pop(0)
    ctx.user_data["token_data"][field_key] = value
    ctx.user_data["token_fields_remaining"] = fields_remaining

    return await ask_next_token_field(update, ctx, update.message)

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

    kb = [[
        InlineKeyboardButton("✅ تأیید و دیپلوی", callback_data="confirm"),
        InlineKeyboardButton("❌ لغو", callback_data="cancel"),
    ]]

    await update.message.reply_text(
        f"📋 *خلاصه:*\n\n"
        f"• پلتفرم: {PLATFORMS[platform]['emoji']} {platform.capitalize()}\n"
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
        await query.message.reply_text("❌ لغو شد.")
        return ConversationHandler.END

    platform = ctx.user_data["platform"]
    token_data = ctx.user_data["token_data"]
    project_name = ctx.user_data["project_name"]
    label = f"tg-{update.effective_user.id}"

    msg = await query.message.reply_text("🔄 در حال اتصال به پنل...")

    # login
    if not await panel.login():
        await msg.edit_text("❌ خطا در اتصال به پنل.")
        return ConversationHandler.END

    # دامنه سرور
    await msg.edit_text("⚙️ در حال خواندن اطلاعات سرور...")
    try:
        target_domain = await panel.get_server_domain()
        if not target_domain:
            raise ValueError("دامنه پیدا نشد")
    except Exception as e:
        logger.error(f"get_server_domain: {e}")
        await msg.edit_text("❌ خطا در خواندن دامنه سرور.")
        return ConversationHandler.END

    # ثبت توکن با فیلد درست هر پلتفرم
    await msg.edit_text("🔑 در حال ثبت توکن...")
    try:
        tok_resp = await panel.add_token(platform, token_data, label)
        token_id = tok_resp.get("id")
        if not token_id:
            raise ValueError(f"Response: {tok_resp}")
    except Exception as e:
        logger.error(f"add_token: {e}")
        await msg.edit_text("❌ خطا در ثبت توکن.")
        return ConversationHandler.END

    # تست توکن
    await msg.edit_text("🧪 در حال تست توکن...")
    try:
        test = await panel.test_token(token_id)
        valid = test.get("valid", False)
        detail = test.get("detail", "")
        if not valid:
            await panel.delete_token(token_id)
            await msg.edit_text(
                f"❌ توکن معتبر نیست!\n"
                f"جزئیات: `{detail}`\n\n"
                f"توکن رو چک کن و دوباره /newconfig رو بزن.",
                parse_mode="Markdown"
            )
            return ConversationHandler.END
    except Exception as e:
        logger.warning(f"test_token: {e} — ادامه میدیم")

    # دیپلوی
    await msg.edit_text(
        f"🚀 در حال دیپلوی روی {platform.capitalize()}...\n"
        f"_(۱ تا ۳ دقیقه طول میکشه)_",
        parse_mode="Markdown"
    )
    try:
        deploy_resp = await panel.deploy(platform, token_id, project_name, target_domain)
        deploy_id = deploy_resp.get("id")
        if not deploy_id:
            raise ValueError(f"No deploy ID: {deploy_resp}")
    except asyncio.TimeoutError:
        await msg.edit_text(
            "⏱ دیپلوی داره طول میکشه.\n"
            "چند دقیقه دیگه /getconfigs رو بفرست."
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"deploy: {e}")
        await msg.edit_text("❌ خطا در دیپلوی.")
        return ConversationHandler.END

    # صبر برای تکمیل — هر ۵ ثانیه چک میکنه
    await msg.edit_text("⏳ منتظر تکمیل دیپلوی...")
    final_deploy = None
    for i in range(36):  # حداکثر ۳ دقیقه
        await asyncio.sleep(5)
        try:
            d = await panel.get_deploy(deploy_id)
            status = d.get("status", "")
            if status == "active":
                final_deploy = d
                break
            elif status == "failed":
                # سعی کن خطا رو از config_json بخونی
                err_detail = ""
                try:
                    cj = json.loads(d.get("config_json") or "{}")
                    err_detail = cj.get("error", "")
                except Exception:
                    pass
                await msg.edit_text(
                    f"❌ دیپلوی ناموفق بود.\n"
                    f"{('خطا: ' + err_detail) if err_detail else ''}\n\n"
                    f"توکن رو چک کن یا پلتفرم دیگه‌ای امتحان کن."
                )
                return ConversationHandler.END
        except Exception:
            pass

    # ارسال کانفیگ
    if final_deploy:
        config_link = extract_config_link(final_deploy)
        deploy_url = final_deploy.get("deploy_url", "")

        if config_link:
            await msg.edit_text(
                f"✅ *کانفیگ آماده‌ست!*\n\n"
                f"پلتفرم: {PLATFORMS[platform]['emoji']} {platform.capitalize()}\n"
                f"پروژه: `{project_name}`\n"
                f"URL: `{deploy_url}`\n\n"
                f"📋 *کانفیگ VLESS:*\n"
                f"`{config_link}`\n\n"
                f"_کپی کن و توی v2rayNG یا هر کلاینت دیگه وارد کن._",
                parse_mode="Markdown"
            )
        else:
            await msg.edit_text(
                f"✅ دیپلوی شد!\n\n"
                f"پروژه `{project_name}` روی {platform.capitalize()} فعاله.\n"
                f"URL: `{deploy_url}`\n\n"
                f"برای کانفیگ /getconfigs رو بفرست.",
                parse_mode="Markdown"
            )
    else:
        await msg.edit_text(
            f"✅ دیپلوی شروع شد.\n\n"
            f"پروژه `{project_name}` داره راه‌اندازی میشه.\n"
            f"چند دقیقه دیگه /getconfigs رو بفرست.",
            parse_mode="Markdown"
        )

    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ لغو شد.")
    return ConversationHandler.END

# ─── /getconfigs ───────────────────────────────────────────
async def get_configs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        msg = await query.message.reply_text("📡 در حال دریافت...")
    else:
        msg = await update.message.reply_text("📡 در حال دریافت...")

    if not await panel.login():
        await msg.edit_text("❌ خطا در اتصال به پنل.")
        return

    try:
        deploys = await panel.get_deploys()
    except Exception as e:
        await msg.edit_text(f"❌ خطا: {e}")
        return

    active = [d for d in deploys if d.get("status") == "active"]

    if not active:
        await msg.edit_text(
            "📭 هیچ کانفیگ فعالی نیست.\n"
            "/newconfig برای ساخت کانفیگ."
        )
        return

    text = f"📋 *{len(active)} کانفیگ فعال:*\n\n"
    for i, d in enumerate(active[:5], 1):
        config_link = extract_config_link(d)
        plat = d.get("platform", "")
        name = d.get("project_name", f"config-{i}")
        emoji = PLATFORMS.get(plat, {}).get("emoji", "🌐")

        if config_link:
            text += f"*{i}. {emoji} {name}*\n`{config_link}`\n\n"
        else:
            url = d.get("deploy_url", "")
            text += f"*{i}. {emoji} {name}*\n_{url}_\n_(کانفیگ هنوز آماده نشده)_\n\n"

    if len(active) > 5:
        text += f"_... و {len(active)-5} کانفیگ دیگه_"

    await msg.edit_text(text, parse_mode="Markdown")

# ─── callback ──────────────────────────────────────────────
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "help":
        await help_cmd(update, ctx)
    elif query.data == "list_configs":
        await get_configs_cmd(update, ctx)

# ─── main ──────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("newconfig", new_config_start),
            CallbackQueryHandler(new_config_start, pattern="^new_config$"),
        ],
        states={
            CHOOSE_PLATFORM: [
                CallbackQueryHandler(choose_platform, pattern="^(plat_|cancel)")
            ],
            ENTER_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_token_field)
            ],
            ENTER_PROJECT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_project_name)
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_deploy, pattern="^(confirm|cancel)$")
            ],
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
