#!/usr/bin/env python3
"""
ربات تلگرام برای XHTTP Panel
"""

import logging
import asyncio
import aiohttp
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

CHOOSE_PLATFORM, ENTER_TOKEN, ENTER_PROJECT_NAME, CONFIRM = range(4)

PLATFORMS = {
    "railway": {"label": "🚂 Railway", "emoji": "🚂"},
    "fastly":  {"label": "⚡ Fastly",  "emoji": "⚡"},
    "vercel":  {"label": "▲ Vercel",   "emoji": "▲"},
    "netlify": {"label": "🟢 Netlify", "emoji": "🟢"},
    "deno":    {"label": "🦕 Deno",    "emoji": "🦕"},
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
        return {"Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json"}

    async def get_server_info(self) -> dict:
        """گرفتن UUID و دامنه مستقیم از کانفیگ Xray"""
        async with aiohttp.ClientSession() as s:
            r = await s.get(
                f"{self.base}/api/v1/configs/xray",
                headers=self._h(),
                timeout=aiohttp.ClientTimeout(total=15)
            )
            data = await r.json()

        uuid = ""
        domain = ""
        path = "/api"

        try:
            clients = data["inbounds"][0]["settings"]["clients"]
            uuid = clients[0]["id"]
        except Exception:
            pass

        try:
            xhttp = data["inbounds"][0]["streamSettings"]["xhttpSettings"]
            domain = xhttp.get("host", "")
            path = xhttp.get("path", "/api")
        except Exception:
            pass

        return {"uuid": uuid, "domain": domain, "path": path}

    async def add_token(self, platform: str, token_value: str, label: str) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.post(
                f"{self.base}/api/v1/tokens",
                headers=self._h(),
                json={
                    "platform": platform,
                    "label": label,
                    "tokenData": {"token": token_value}
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

    async def deploy(self, platform: str, token_id: int, project_name: str, target_domain: str) -> dict:
        async with aiohttp.ClientSession() as s:
            r = await s.post(
                f"{self.base}/api/v1/deploy/{platform}",
                headers=self._h(),
                json={
                    "tokenId": token_id,
                    "projectName": project_name,
                    "targetDomain": target_domain,
                    "relayPath": "/api",
                },
                timeout=aiohttp.ClientTimeout(total=180)
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

def build_vless(deploy: dict, uuid: str, domain: str, path: str) -> str:
    """ساخت لینک VLESS با اطلاعات واقعی از پنل"""
    deploy_url = deploy.get("deploy_url", "")
    platform = deploy.get("platform", "")
    name = deploy.get("project_name", "config")

    if not deploy_url or not uuid:
        return ""

    host = deploy_url.replace("https://", "").replace("http://", "").rstrip("/")

    return (
        f"vless://{uuid}@{domain}:443"
        f"?mode=auto"
        f"&path={path}"
        f"&security=tls"
        f"&encryption=none"
        f"&insecure=0"
        f"&host={host}"
        f"&fp=chrome"
        f"&type=xhttp"
        f"&allowInsecure=0"
        f"&sni={host}"
        f"#{platform}-{name}"
    )

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
        "📌 پلتفرم‌ها: Railway | Fastly | Vercel | Netlify | Deno",
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

    kb = [[InlineKeyboardButton(PLATFORMS[p]["label"], callback_data=f"plat_{p}")] for p in PLATFORMS]
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

    await query.message.reply_text(
        f"{PLATFORMS[platform]['emoji']} *{platform.capitalize()}* انتخاب شد.\n\n"
        f"🔑 توکن API {platform.capitalize()} رو بفرست:\n"
        f"_(پیام بعد از دریافت حذف میشه)_",
        parse_mode="Markdown"
    )
    return ENTER_TOKEN

async def enter_token(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    token_value = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass

    if len(token_value) < 8:
        await update.message.reply_text("⚠️ توکن خیلی کوتاهه. دوباره بفرست:")
        return ENTER_TOKEN

    ctx.user_data["token_value"] = token_value
    user = update.effective_user
    default_name = f"tg-{user.id % 9999}-{int(datetime.now().timestamp()) % 9999}"

    await update.message.reply_text(
        f"✅ توکن دریافت شد.\n\n"
        f"📝 نام پروژه رو بنویس:\n"
        f"_(حروف کوچک، عدد، خط‌تیره — ۳ تا ۳۰ کاراکتر)_\n\n"
        f"پیش‌فرض: `{default_name}`",
        parse_mode="Markdown"
    )
    ctx.user_data["default_name"] = default_name
    return ENTER_PROJECT_NAME

async def enter_project_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip().lower()

    if not re.match(r'^[a-z0-9\-]{3,30}$', name):
        await update.message.reply_text(
            "⚠️ نام نامعتبره!\n"
            "فقط حروف کوچک انگلیسی، عدد و خط‌تیره.\n"
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
    token_value = ctx.user_data["token_value"]
    project_name = ctx.user_data["project_name"]
    label = f"tg-{update.effective_user.id}"

    msg = await query.message.reply_text("🔄 در حال اتصال به پنل...")

    # login
    if not await panel.login():
        await msg.edit_text("❌ خطا در اتصال به پنل.")
        return ConversationHandler.END

    # گرفتن UUID و دامنه از پنل
    await msg.edit_text("⚙️ در حال خواندن اطلاعات سرور...")
    try:
        server_info = await panel.get_server_info()
        uuid = server_info["uuid"]
        domain = server_info["domain"]
        path = server_info["path"]
        if not uuid or not domain:
            raise ValueError("UUID یا دامنه پیدا نشد")
    except Exception as e:
        logger.error(f"get_server_info: {e}")
        await msg.edit_text("❌ خطا در خواندن اطلاعات سرور.")
        return ConversationHandler.END

    # ثبت توکن
    await msg.edit_text("🔑 در حال ثبت توکن...")
    try:
        tok_resp = await panel.add_token(platform, token_value, label)
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
        valid = test.get("valid") or test.get("status") == "valid"
        if not valid:
            await panel.delete_token(token_id)
            await msg.edit_text(
                "❌ توکن معتبر نیست!\n"
                "توکن رو چک کن و دوباره امتحان کن."
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
        deploy_resp = await panel.deploy(platform, token_id, project_name, domain)
        deploy_id = deploy_resp.get("id")
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

    # صبر برای تکمیل
    await msg.edit_text("⏳ منتظر تکمیل دیپلوی...")
    final_deploy = None
    for _ in range(24):  # حداکثر ۲ دقیقه
        await asyncio.sleep(5)
        try:
            deploys = await panel.get_deploys()
            current = next((d for d in deploys if d.get("id") == deploy_id), None)
            if current:
                status = current.get("status")
                if status == "active":
                    final_deploy = current
                    break
                elif status == "failed":
                    await msg.edit_text(
                        "❌ دیپلوی ناموفق بود.\n"
                        "توکن رو چک کن یا پلتفرم دیگه‌ای امتحان کن."
                    )
                    return ConversationHandler.END
        except Exception:
            pass

    # ساخت و ارسال کانفیگ
    if final_deploy and final_deploy.get("deploy_url"):
        vless = build_vless(final_deploy, uuid, domain, path)
        if vless:
            await msg.edit_text(
                f"✅ *کانفیگ آماده‌ست!*\n\n"
                f"پلتفرم: {PLATFORMS[platform]['emoji']} {platform.capitalize()}\n"
                f"پروژه: `{project_name}`\n\n"
                f"📋 *کانفیگ VLESS:*\n"
                f"`{vless}`\n\n"
                f"_کپی کن و توی v2rayNG یا هر کلاینت دیگه وارد کن._",
                parse_mode="Markdown"
            )
        else:
            await msg.edit_text("⚠️ دیپلوی شد ولی کانفیگ ساخته نشد. /getconfigs رو بزن.")
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
        server_info = await panel.get_server_info()
        uuid   = server_info["uuid"]
        domain = server_info["domain"]
        path   = server_info["path"]
        deploys = await panel.get_deploys()
    except Exception as e:
        await msg.edit_text(f"❌ خطا: {e}")
        return

    active = [d for d in deploys if d.get("status") == "active" and d.get("deploy_url")]

    if not active:
        await msg.edit_text(
            "📭 هیچ کانفیگ فعالی نیست.\n"
            "/newconfig برای ساخت کانفیگ."
        )
        return

    text = f"📋 *{len(active)} کانفیگ فعال:*\n\n"
    for i, d in enumerate(active[:5], 1):
        vless = build_vless(d, uuid, domain, path)
        plat = d.get("platform", "")
        name = d.get("project_name", f"config-{i}")
        emoji = PLATFORMS.get(plat, {}).get("emoji", "🌐")
        if vless:
            text += f"*{i}. {emoji} {name}*\n`{vless}`\n\n"
        else:
            text += f"*{i}. {emoji} {name}* — کانفیگ موجود نیست\n\n"

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
            CHOOSE_PLATFORM:    [CallbackQueryHandler(choose_platform, pattern="^(plat_|cancel)")],
            ENTER_TOKEN:        [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_token)],
            ENTER_PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_project_name)],
            CONFIRM:            [CallbackQueryHandler(confirm_deploy, pattern="^(confirm|cancel)$")],
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
