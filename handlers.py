from html import escape
import asyncio
import logging
import os
from typing import Optional

import jdatetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest, TelegramError

from config import ADMIN_ID, CHANNEL_ID, TRANSACTION_LOG_CHANNEL_ID, TOMAN_PER_STAR
from db import (
    get_user_balance, get_or_create_user, has_used_test_account,
    get_available_config, get_user_orders,
    mark_test_account_used, assign_config_to_order,
    create_order, add_config, add_configs_batch, count_available_configs, get_stock_summary,
    delete_config, delete_configs_by_product, get_config_by_id, get_configs_by_product,
    get_order_by_id, update_order_status,
    add_user_balance, mark_config_sold,
    create_user_service, get_user_services_list, count_active_user_services,
    get_all_user_ids, get_services_by_user, get_user_service_by_id, set_service_xui_email,
)
from utils import (
    build_order_text,
    build_service_delivered_text,
    delete_message_safe,
    format_rial_from_toman,
    get_safe_username,
    send_new_message,
    format_toman,
    safe_answer,
    notify_admin,
    log_admin_event,
    notify_admin_purchase_request,
    notify_admin_receipt_submitted,
    notify_admin_test_account,
    notify_admin_stars_purchase,
    notify_admin_service_delivered,
    get_jalali_now,
    generate_qr_code,
)
import xui_db
from keyboads import (
    get_main_menu_keyboard, get_wallet_keyboard, get_support_keyboard, get_products_keyboard,
    DURATION_CODE_TO_DAYS, get_duration_menu_keyboard, get_payment_method_keyboard, PRODUCTS,
    get_buy_category_keyboard, get_unlimited_menu_keyboard, UNLIMITED_DURATION_LABELS,
    get_admin_panel_keyboard, get_admin_users_pagination_keyboard, get_admin_back_keyboard,
    get_admin_product_picker_keyboard, get_admin_product_actions_keyboard,
    get_admin_config_list_keyboard, get_admin_delall_confirm_keyboard, get_admin_cancel_add_keyboard,
    get_service_detail_keyboard,
)

# ---------------------------------------------------------------------------
# ثابت‌ها
# ---------------------------------------------------------------------------

WAITING_FOR_RECEIPT = 1
WAITING_FOR_TOPUP_AMOUNT = 2
WAITING_FOR_BROADCAST = 3

logger = logging.getLogger("handlers")

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
USERS_PER_PAGE = 5
VALID_PRODUCT_KEYS = set(PRODUCTS.keys()) | {"test_config"}

BAD_WORDS = {
    "کیری", "کصکش", "کسکش", "کوسکش", "جاکش", "کونی", "کیرم", "کص", "کس",
    "لاشی", "عوضی", "احمق", "خارکسه", "مادرجنده", "ننه جنده", "جنده",
    "حرومزاده", "بی شرف", "بیشرف", "آشغال", "کثافت", "گوه", "خفه شو",
    "کیرخر", "مادرقحبه", "ننه سگ", "پدرسگ", "عنتر", "خری", "الاغ",
}


# ---------------------------------------------------------------------------
# توابع کمکی
# ---------------------------------------------------------------------------

def is_admin(user_id: int) -> bool:
    return bool(ADMIN_ID and user_id == ADMIN_ID)


def contains_profanity(text: str) -> bool:
    if not text:
        return False
    normalized = text.replace("‌", " ").lower()
    return any(bad in normalized for bad in BAD_WORDS)


def is_valid_product_key(product_key: str) -> bool:
    return product_key in VALID_PRODUCT_KEYS


def _product_label(product_key: str) -> str:
    if product_key == "test_config":
        return "اکانت تست"
    if product_key == "topup":
        return "افزایش موجودی"
    product = PRODUCTS.get(product_key, {})
    if product:
        return f"{product.get('size', '')} / {product.get('duration', '')} روزه"
    return product_key


_DURATION_DAYS_LABELS = {
    "30": "یک ماهه",
    "60": "دو ماهه",
    "90": "سه ماهه",
    "180": "شش ماهه",
    "365": "یکساله",
}


def _service_product_label(product_key: str) -> str:
    """نام شیک محصول برای نمایش در صفحه‌ی جزئیات سرویس (مثلاً «یک ماهه نامحدود 💎»)."""
    if product_key == "test_config":
        return "سرویس تست 🧪"

    product = PRODUCTS.get(product_key)
    if not product:
        return f"{product_key} 💎"

    duration_label = _DURATION_DAYS_LABELS.get(product.get("duration", ""), f"{product.get('duration')} روزه")
    if product.get("category") == "unlimited":
        return f"{duration_label} نامحدود 💎"
    return f"{duration_label} {product.get('size', '')} 💎"


def _is_image_document(doc) -> bool:
    if not doc:
        return False
    mt = (doc.mime_type or "").lower().strip()
    if mt.startswith("image/"):
        return True
    filename = (doc.file_name or "").lower().strip()
    _, ext = os.path.splitext(filename)
    return ext in ALLOWED_IMAGE_EXTS


def _parse_addconfig_entries(message_text: str, args: list) -> list:
    """استخراج ورودی‌های addconfig از یک یا چند خط."""
    entries = []
    if message_text:
        for line in message_text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("/addconfig"):
                parts = line.split(maxsplit=2)
                if len(parts) >= 3:
                    entries.append((parts[1].strip(), parts[2].strip()))
            elif not line.startswith("/") and len(entries) == 0 and len(args) >= 2:
                break
    if not entries and len(args) >= 2:
        entries.append((args[0].strip(), " ".join(args[1:]).strip()))
    return entries


async def check_user_membership(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except BadRequest as e:
        print(f"Membership check BadRequest (CHANNEL_ID={CHANNEL_ID!r}): {e}")
        return False
    except TelegramError as e:
        print(f"Membership check error: {e}")
        return False


async def _edit_admin_message(query, text: str, reply_markup=None) -> None:
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramError:
        await delete_message_safe(query)
        await query.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="HTML")


def _build_stock_text() -> str:
    stock = {row["product_key"]: row["count"] for row in get_stock_summary()}
    lines = ["📋 <b>موجودی محصولات:</b>\n"]
    lines.append(f"<code>test_config</code> : {stock.get('test_config', 0)}")
    for key in PRODUCTS:
        count = stock.get(key, 0)
        lines.append(f"<code>{key}</code> : {count}")
    return "\n".join(lines)


def _build_users_services_text(page: int) -> tuple:
    total = count_active_user_services()
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    offset = page * USERS_PER_PAGE
    services = get_user_services_list(limit=USERS_PER_PAGE, offset=offset)

    lines = [f"👥 <b>کاربران دارای سرویس</b> (صفحه {page + 1}/{total_pages})\n"]
    if not services:
        lines.append("هیچ سرویس فعالی ثبت نشده.")
    else:
        for svc in services:
            svc_type = "تستی" if svc["service_type"] == "test" else "پولی"
            username = f"@{svc['username']}" if svc.get("username") else (svc.get("full_name") or "بدون یوزرنیم")
            link = svc.get("link") or "—"
            lines.append(
                f"━━━━━━━━━━━━━━━\n"
                f"🆔 <code>{svc['user_id']}</code>\n"
                f"👤 {escape(str(username))}\n"
                f"🏷 نوع: {svc_type}\n"
                f"📦 {escape(_product_label(svc['product_key']))}\n"
                f"📅 انقضا: {svc['expiry_date']}\n"
                f"🗜 حجم باقی‌مانده: {escape(str(svc['remaining_volume']))}\n"
                f"🔗 <code>{escape(str(link))}</code>"
            )
    return "\n".join(lines), page, total_pages


# ---------------------------------------------------------------------------
# تحویل سرویس
# ---------------------------------------------------------------------------

async def _deliver_topup(order: dict, context: ContextTypes.DEFAULT_TYPE) -> None:
    customer_id = order["user_id"]
    amount = order["price"]
    add_user_balance(customer_id, amount)
    update_order_status(order["id"], "completed")

    await context.bot.send_message(
        chat_id=customer_id,
        text=f"✅ پرداخت شما تأیید شد و مبلغ {format_toman(amount)} تومان به کیف پول شما اضافه شد.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]]),
    )

    await log_admin_event(
        context,
        "افزایش موجودی تأیید شد",
        f"🆔 <code>{customer_id}</code>\n💰 {format_toman(amount)} تومان\n📌 وضعیت: تکمیل شد",
    )


async def _deliver_product(
    order: dict,
    context: ContextTypes.DEFAULT_TYPE,
    username: str = None,
) -> bool:
    product_key = order["product_key"]
    customer_id = order["user_id"]

    config_data = get_available_config(product_key)
    if not config_data:
        return False

    assign_config_to_order(order["id"], config_data["id"])

    product = PRODUCTS.get(product_key, {})
    size = product.get("size", "نامشخص")
    duration_days = int(product.get("duration", 0) or 0)

    create_user_service(
        user_id=customer_id,
        username=username,
        service_type="paid",
        product_key=product_key,
        config_id=config_data["id"],
        link=config_data["link"],
        size=str(size),
        duration_days=duration_days or 30,
    )

    success_text = build_service_delivered_text(
        user_id=customer_id,
        config_id=config_data["id"],
        size=size,
        duration_days=product.get("duration", "نامشخص"),
        link=config_data["link"],
    )

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]])

    sent_message = None
    try:
        qr_bio = generate_qr_code(config_data["link"])
        sent_message = await context.bot.send_photo(
            chat_id=customer_id,
            photo=qr_bio,
            caption=success_text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except Exception as e:
        print(f"Could not generate/send QR code for {customer_id}: {e}")
        sent_message = await context.bot.send_message(
            chat_id=customer_id, text=success_text, parse_mode="HTML", reply_markup=reply_markup,
        )

    try:
        await context.bot.pin_chat_message(
            chat_id=customer_id, message_id=sent_message.message_id, disable_notification=True,
        )
    except TelegramError as e:
        print(f"Could not pin service-delivered message for {customer_id}: {e}")

    await notify_admin_service_delivered(
        context,
        user_id=customer_id,
        username=username,
        product_key=product_key,
        product_label=_product_label(product_key),
        config_id=config_data["id"],
        service_type="پولی",
    )
    return True


# ---------------------------------------------------------------------------
# دستورات کاربر
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if CHANNEL_ID and not await check_user_membership(user.id, context.bot):
        channel_url = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        join_text = (
            "🔒 <b>یه قدم تا استفاده از ربات فاصله داری!</b>\n\n"
            "برای اینکه بتونی از امکانات ربات استفاده کنی، اول باید توی کانال ما عضو بشی. "
            "بعد از عضویت، دوباره دستور /start رو بزن تا وارد ربات بشی. ✅"
        )
        await update.message.reply_text(
            text=join_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 عضویت در کانال", url=channel_url)],
                [InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data="check_membership")],
            ]),
        )
        return

    get_user_balance(user.id)
    first_name = escape(user.first_name or "داداش")
    welcome_text = (
        f"سلام <b>{first_name}</b> عزیز، خوش اومدی 👋\n\n"

        "🔥 <b>پیشنهاد ویژه فعال:</b>\n"
        "سرور فرانسه با <b>اینترنت نامحدود</b> فقط <b>۹۰ هزار تومان</b> برای یک ماه! 🚀\n\n"

        "اگر دنبال یک اتصال سریع، پایدار و باکیفیت هستی، این سرویس می‌تونه انتخاب مناسبی برات باشه.\n\n"

        "✅ سرور پرسرعت فرانسه 🇫🇷\n"
        "✅ حجم مصرفی کاملاً نامحدود\n"
        "✅ مناسب برای استفاده روزمره، کار، مطالعه و سرگرمی\n"
        "✅ فعال‌سازی سریع و آسان\n\n"

        "برای تهیه سرویس فقط از منوی پایین وارد بخش <b>«خرید کانفیگ»</b> شو و مراحل خرید رو انجام بده.\n\n"

        "در صورت نیاز به راهنمایی یا پشتیبانی، همراهت هستیم 😊\n\n"

        "🔸 یکی از گزینه‌های زیر رو انتخاب کن:"
    )
    await update.message.reply_text(
        text=welcome_text,
        reply_markup=get_main_menu_keyboard(show_admin_panel=is_admin(user.id)),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# دستورات ادمین
# ---------------------------------------------------------------------------

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    await update.message.reply_text(
        "🛠 <b>پنل مدیریت</b>\n\nیکی از گزینه‌ها را انتخاب کن:",
        parse_mode="HTML",
        reply_markup=get_admin_panel_keyboard(),
    )


async def admin_add_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    message_text = update.message.text or ""
    entries = _parse_addconfig_entries(message_text, context.args)

    if not entries:
        await update.message.reply_text(
            "❌ فرمت درست:\n"
            "<code>/addconfig product_key link</code>\n\n"
            "یا چند خط در یک پیام:\n"
            "<code>/addconfig buy_1m_10gb https://...\n"
            "/addconfig buy_1m_10gb https://...</code>\n\n"
            "برای دیدن لیست کلیدها از /listkeys استفاده کن.",
            parse_mode="HTML",
        )
        return

    invalid_keys = [e[0] for e in entries if not is_valid_product_key(e[0])]
    if invalid_keys:
        await update.message.reply_text(
            f"⚠️ کلیدهای نامعتبر: {', '.join(invalid_keys)}\n"
            "برای دیدن لیست کلیدهای معتبر از /listkeys استفاده کن."
        )
        return

    if len(entries) == 1:
        product_key, link = entries[0]
        config_id = add_config(product_key, link)
        remaining = count_available_configs(product_key)
        await update.message.reply_text(
            f"✅ لینک با شناسه <code>{config_id}</code> برای <code>{escape(product_key)}</code> ذخیره شد.\n"
            f"📦 موجودی: {remaining}",
            parse_mode="HTML",
        )
    else:
        results = add_configs_batch(entries)
        summary_lines = [f"✅ <b>{len(results)} لینک با موفقیت اضافه شد:</b>\n"]
        counts = {}
        for item in results:
            counts[item["product_key"]] = counts.get(item["product_key"], 0) + 1
        for key, cnt in counts.items():
            remaining = count_available_configs(key)
            summary_lines.append(f"• <code>{escape(key)}</code>: +{cnt} → موجودی: {remaining}")
        await update.message.reply_text("\n".join(summary_lines), parse_mode="HTML")

    await log_admin_event(
        context,
        "افزودن کانفیگ",
        f"تعداد: {len(entries)}\nادمین: <code>{user.id}</code>",
    )


async def admin_list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    await update.message.reply_text(_build_stock_text(), parse_mode="HTML")


async def admin_list_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ فرمت درست:\n<code>/listconfigs product_key</code>",
            parse_mode="HTML",
        )
        return

    product_key = args[0].strip()
    if not is_valid_product_key(product_key):
        await update.message.reply_text("⚠️ product_key معتبر نیست. از /listkeys استفاده کن.")
        return

    configs = get_configs_by_product(product_key, limit=30)
    if not configs:
        await update.message.reply_text(
            f"📦 هیچ لینک موجودی برای <code>{escape(product_key)}</code> نیست.",
            parse_mode="HTML",
        )
        return

    lines = [f"📋 <b>لینک‌های {escape(product_key)}:</b>\n"]
    for cfg in configs:
        link = cfg["link"]
        short_link = link if len(link) <= 60 else link[:57] + "..."
        lines.append(f"• <code>{cfg['id']}</code> → <code>{escape(short_link)}</code>")
    lines.append("\n🗑 حذف یکی: <code>/delconfig شناسه</code>")
    lines.append("🗑 حذف همه: <code>/delconfig product_key all</code>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def admin_delete_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    args = context.args
    if len(args) != 1 and len(args) != 2:
        await update.message.reply_text(
            "❌ فرمت:\n"
            "<code>/delconfig config_id</code>\n"
            "یا\n"
            "<code>/delconfig product_key all</code>",
            parse_mode="HTML",
        )
        return

    if len(args) == 2 and args[1].strip().lower() == "all":
        product_key = args[0].strip()
        if not is_valid_product_key(product_key):
            await update.message.reply_text("⚠️ product_key معتبر نیست.")
            return
        deleted = delete_configs_by_product(product_key)
        remaining = count_available_configs(product_key)
        await update.message.reply_text(
            f"🗑 <b>{deleted}</b> لینک از <code>{escape(product_key)}</code> حذف شد.\n"
            f"📦 موجودی باقی‌مانده: {remaining}",
            parse_mode="HTML",
        )
        await log_admin_event(context, "حذف گروهی کانفیگ", f"محصول: <code>{escape(product_key)}</code>\nتعداد: {deleted}")
        return

    if not args[0].strip().lstrip("-").isdigit():
        await update.message.reply_text(
            "❌ شناسه نامعتبر. از <code>/delconfig product_key all</code> برای حذف همه استفاده کن.",
            parse_mode="HTML",
        )
        return

    config_id = int(args[0].strip())
    config = get_config_by_id(config_id)
    if not config:
        await update.message.reply_text("⚠️ لینکی با این شناسه پیدا نشد.")
        return
    if config["status"] != "available":
        await update.message.reply_text("⚠️ این لینک قبلاً فروخته شده و قابل حذف نیست.")
        return

    ok = delete_config(config_id)
    if ok:
        remaining = count_available_configs(config["product_key"])
        await update.message.reply_text(
            f"🗑 لینک <code>{config_id}</code> حذف شد.\n📦 موجودی: {remaining}",
            parse_mode="HTML",
        )
        await log_admin_event(context, "حذف کانفیگ", f"شناسه: <code>{config_id}</code>")
    else:
        await update.message.reply_text("❌ حذف انجام نشد.")


def _admin_help_text() -> str:
    return (
        "🛠 <b>راهنمای کامل ادمین</b>\n\n"
        "<b>📌 پنل مدیریت</b>\n"
        "• <code>/adminpanel</code> — باز کردن پنل با دکمه‌های شیشه‌ای\n\n"
        "<b>📦 مدیریت موجودی</b>\n"
        "• <code>/addconfig product_key link</code> — افزودن یک لینک\n"
        "• چند خط در یک پیام — افزودن دسته‌ای (Batch Import)\n"
        "• <code>/listkeys</code> — موجودی همه محصولات\n"
        "• <code>/listconfigs product_key</code> — لیست لینک‌های یک محصول\n"
        "• <code>/delconfig config_id</code> — حذف یک لینک\n"
        "• <code>/delconfig product_key all</code> — حذف همه لینک‌های available\n\n"
        "<b>📊 پنل (Inline)</b>\n"
        "• مشاهده موجودی محصولات\n"
        "• مشاهده کاربران دارای سرویس (تستی/پولی)\n"
        "• ارسال پیام همگانی\n\n"
        "<b>📋 گزارش‌های خودکار</b>\n"
        "ربات این موارد را به ادمین گزارش می‌دهد:\n"
        "• ثبت درخواست خرید\n"
        "• دریافت رسید پرداخت\n"
        "• دریافت اکانت تست\n"
        "• خرید با Telegram Stars\n"
        "• افزایش موجودی با Stars\n"
        "• تحویل موفق سرویس\n\n"
        "<b>🧪 دیباگ اتصال به x-ui</b>\n"
        "• <code>/xuidebug</code> — نمایش جدول‌های موجود در دیتابیس x-ui\n"
        "• <code>/xuidebug email فلان@ایمیل</code> — تست خواندن یک کلاینت با ایمیل\n"
        "• <code>/xuidebug subid فلان‌ساب‌آیدی</code> — تست خواندن یک کلاینت با subId\n"
        "• <code>/xuidebug link https://.../sub/xxxx</code> — تست کامل با یک لینک subscription\n\n"
        "• <code>/helpadmin</code> — نمایش همین راهنما"
    )


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return
    await update.message.reply_text(_admin_help_text(), parse_mode="HTML")


async def admin_xui_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    دستور دیباگ برای تست مستقیم اتصال به x-ui.db روی سرور واقعی، بدون نیاز
    به دست‌کاری کد. چون این ماژول فقط SELECT انجام می‌دهد، اجرای این دستور
    کاملاً امن است و چیزی در x-ui تغییر نمی‌دهد.

    استفاده:
        /xuidebug                        -> لیست جدول‌های دیتابیس x-ui
        /xuidebug email user@example.com -> get_client_info با ایمیل
        /xuidebug subid rtxu6ex39kqesbru -> پیدا کردن ایمیل از روی subId و بعد get_client_info
        /xuidebug link https://host:2096/sub/rtxu6ex39kqesbru -> استخراج subId از لینک کامل
    """
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    args = context.args
    if not args:
        tables = await asyncio.to_thread(xui_db.list_tables)
        text = (
            f"🗄 <b>مسیر دیتابیس:</b> <code>{escape(xui_db.XUI_DB_PATH)}</code>\n\n"
            f"📋 <b>جدول‌های موجود ({len(tables)}):</b>\n"
            + ("\n".join(f"• <code>{escape(t)}</code>" for t in tables) if tables else "❌ هیچ جدولی خوانده نشد (مسیر یا دسترسی فایل را بررسی کن).")
        )
        await update.message.reply_text(text, parse_mode="HTML")
        return

    mode = args[0].strip().lower()
    value = " ".join(args[1:]).strip()

    if mode not in ("email", "subid", "link") or not value:
        await update.message.reply_text(
            "❌ فرمت درست:\n"
            "<code>/xuidebug email user@example.com</code>\n"
            "<code>/xuidebug subid rtxu6ex39kqesbru</code>\n"
            "<code>/xuidebug link https://host:2096/sub/xxxx</code>",
            parse_mode="HTML",
        )
        return

    if mode == "link":
        sub_id = xui_db.extract_subid_from_link(value)
        if not sub_id:
            await update.message.reply_text("❌ نتونستم subId رو از این لینک استخراج کنم.")
            return
        email = await asyncio.to_thread(xui_db.find_email_by_subid, sub_id)
    elif mode == "subid":
        sub_id = value
        email = await asyncio.to_thread(xui_db.find_email_by_subid, sub_id)
    else:
        sub_id = None
        email = value

    if not email:
        await update.message.reply_text(
            f"❌ کلاینتی پیدا نشد (subId: <code>{escape(sub_id or '-')}</code>).\n"
            "جزئیات خطا در لاگ ربات (stderr) ثبت شده.",
            parse_mode="HTML",
        )
        return

    info = await asyncio.to_thread(xui_db.get_client_info, email)
    if not info:
        await update.message.reply_text(
            f"❌ ایمیل <code>{escape(email)}</code> پیدا شد ولی get_client_info چیزی برنگردوند.",
            parse_mode="HTML",
        )
        return

    active = xui_db.is_active(info)
    usage_bytes = int(info.get("up") or 0) + int(info.get("down") or 0)
    total = int(info.get("total") or 0)
    remaining = "نامحدود" if total <= 0 else xui_db.format_bytes(max(total - usage_bytes, 0))

    text = (
        "🧪 <b>نتیجه دیباگ x-ui</b>\n"
        f"📧 ایمیل: <code>{escape(str(info.get('email')))}</code>\n"
        f"🆔 subId: <code>{escape(str(info.get('sub_id')))}</code>\n"
        f"🔑 UUID/Password: <code>{escape(str(info.get('uuid')))}</code>\n"
        f"📡 Inbound: <code>{escape(str(info.get('inbound_remark')))}</code> ({escape(str(info.get('inbound_protocol')))})\n"
        f"✅ enable: {info.get('enable')}\n"
        f"📊 وضعیت محاسبه‌شده: {'فعال ✅' if active else 'غیرفعال ❌'}\n"
        f"📥 مصرف: {xui_db.format_bytes(usage_bytes)}\n"
        f"💢 باقی‌مانده: {remaining}\n"
        f"📅 انقضا: {xui_db.format_expiry(info.get('expiry_time'))}\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# پنل ادمین — Callback
# ---------------------------------------------------------------------------

CONFIG_LIST_PAGE_SIZE = 8


async def _handle_admin_callbacks(query, context, data, mark_and_answer) -> bool:
    """True اگر callback مربوط به بخش ادمین بود (چه پردازش موفق چه رد دسترسی)."""
    if not data.startswith("admin_"):
        return False

    if not is_admin(query.from_user.id):
        await mark_and_answer("⛔️ این بخش فقط برای ادمین است.", alert=True)
        return True

    # اگر ادمین وسط فلوی «افزودن لینک» به بخش دیگری بره، حالت انتظار پاک می‌شه
    if not data.startswith("admin_cfgadd_"):
        context.user_data.pop("awaiting_config_add", None)

    if data == "admin_panel":
        context.user_data.pop("awaiting_broadcast", None)
        await _edit_admin_message(query, "🛠 <b>پنل مدیریت</b>\n\nیکی از گزینه‌ها را انتخاب کن:", get_admin_panel_keyboard())
        return True

    if data == "admin_stock":
        await _edit_admin_message(query, _build_stock_text(), get_admin_back_keyboard())
        return True

    if data.startswith("admin_users_"):
        try:
            page = int(data.rsplit("_", 1)[-1])
        except ValueError:
            page = 0
        text, page, total_pages = _build_users_services_text(page)
        await _edit_admin_message(query, text, get_admin_users_pagination_keyboard(page, total_pages))
        return True

    if data == "admin_broadcast":
        context.user_data["awaiting_broadcast"] = True
        await _edit_admin_message(
            query,
            "📢 <b>پیام همگانی</b>\n\nمتن پیام را ارسال کن.\nبرای لغو: /cancel یا دکمه بازگشت.",
            get_admin_back_keyboard(),
        )
        return True

    if data == "admin_help_panel":
        await _edit_admin_message(query, _admin_help_text(), get_admin_back_keyboard())
        return True

    # -----------------------------------------------------------------
    # مدیریت کانفیگ‌ها (کاملاً دکمه‌ای)
    # -----------------------------------------------------------------

    if data.startswith("admin_cfgpick_"):
        try:
            page = int(data[len("admin_cfgpick_"):])
        except ValueError:
            page = 0
        stock = {row["product_key"]: row["count"] for row in get_stock_summary()}
        await _edit_admin_message(
            query,
            "🛠 <b>مدیریت کانفیگ‌ها</b>\n\nیک محصول را برای مدیریت انتخاب کن:",
            get_admin_product_picker_keyboard(page, stock),
        )
        return True

    if data.startswith("admin_cfgsel_"):
        product_key = data[len("admin_cfgsel_"):]
        if not is_valid_product_key(product_key):
            await mark_and_answer("⚠️ محصول نامعتبر.", alert=True)
            return True
        remaining = count_available_configs(product_key)
        label = _product_label(product_key)
        text = (
            f"🛠 <b>مدیریت {escape(label)}</b>\n"
            f"🔑 <code>{escape(product_key)}</code>\n"
            f"📦 موجودی فعلی: <b>{remaining}</b>"
        )
        await _edit_admin_message(query, text, get_admin_product_actions_keyboard(product_key))
        return True

    if data.startswith("admin_cfgadd_"):
        product_key = data[len("admin_cfgadd_"):]
        if not is_valid_product_key(product_key):
            await mark_and_answer("⚠️ محصول نامعتبر.", alert=True)
            return True
        context.user_data["awaiting_config_add"] = product_key
        await _edit_admin_message(
            query,
            f"➕ <b>افزودن لینک برای</b> <code>{escape(product_key)}</code>\n\n"
            "یک یا چند لینک بفرست؛ هر لینک در یک خط جداگانه.\n"
            "برای لغو /cancel بزن یا دکمه زیر رو بزن.",
            get_admin_cancel_add_keyboard(product_key),
        )
        return True

    if data.startswith("admin_cfglist|"):
        try:
            _, product_key, page_str = data.split("|", 2)
            page = int(page_str)
        except (ValueError, IndexError):
            await mark_and_answer("خطای داخلی در پردازش.", alert=True)
            return True
        if not is_valid_product_key(product_key):
            await mark_and_answer("⚠️ محصول نامعتبر.", alert=True)
            return True
        await _render_config_list(query, product_key, page)
        return True

    if data.startswith("admin_delonecfg|"):
        try:
            _, cfg_id_str, product_key, page_str = data.split("|", 3)
            cfg_id = int(cfg_id_str)
            page = int(page_str)
        except (ValueError, IndexError):
            await mark_and_answer("خطای داخلی در پردازش.", alert=True)
            return True

        config = get_config_by_id(cfg_id)
        if not config or config["status"] != "available":
            await mark_and_answer("⚠️ این لینک قبلاً حذف یا فروخته شده.", alert=True)
        else:
            delete_config(cfg_id)
            await log_admin_event(
                context, "حذف کانفیگ (پنل)",
                f"شناسه: <code>{cfg_id}</code>\nمحصول: <code>{escape(product_key)}</code>",
            )
        await _render_config_list(query, product_key, page)
        return True

    if data.startswith("admin_cfgdelallok_"):
        product_key = data[len("admin_cfgdelallok_"):]
        if not is_valid_product_key(product_key):
            await mark_and_answer("⚠️ محصول نامعتبر.", alert=True)
            return True
        deleted = delete_configs_by_product(product_key)
        remaining = count_available_configs(product_key)
        await _edit_admin_message(
            query,
            f"🗑 <b>{deleted}</b> لینک از <code>{escape(product_key)}</code> حذف شد.\n📦 موجودی باقی‌مانده: {remaining}",
            get_admin_product_actions_keyboard(product_key),
        )
        await log_admin_event(
            context, "حذف گروهی کانفیگ (پنل)",
            f"محصول: <code>{escape(product_key)}</code>\nتعداد: {deleted}",
        )
        return True

    if data.startswith("admin_cfgdelall_"):
        product_key = data[len("admin_cfgdelall_"):]
        if not is_valid_product_key(product_key):
            await mark_and_answer("⚠️ محصول نامعتبر.", alert=True)
            return True
        remaining = count_available_configs(product_key)
        await _edit_admin_message(
            query,
            f"⚠️ مطمئنی می‌خوای همه‌ی <b>{remaining}</b> لینک موجود <code>{escape(product_key)}</code> حذف بشه؟\n"
            "این کار قابل بازگشت نیست.",
            get_admin_delall_confirm_keyboard(product_key),
        )
        return True

    return False


async def _render_config_list(query, product_key: str, page: int) -> None:
    total = count_available_configs(product_key)
    total_pages = max(1, (total + CONFIG_LIST_PAGE_SIZE - 1) // CONFIG_LIST_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    offset = page * CONFIG_LIST_PAGE_SIZE
    configs = get_configs_by_product(product_key, limit=CONFIG_LIST_PAGE_SIZE, offset=offset)

    if not configs:
        text = f"📦 هیچ لینک موجودی برای <code>{escape(product_key)}</code> نیست."
    else:
        lines = [f"📋 <b>لینک‌های {escape(product_key)}</b> (صفحه {page + 1}/{total_pages})\n"]
        for cfg in configs:
            short_link = cfg["link"] if len(cfg["link"]) <= 60 else cfg["link"][:57] + "..."
            lines.append(f"• #{cfg['id']} → <code>{escape(short_link)}</code>")
        text = "\n".join(lines)

    keyboard = get_admin_config_list_keyboard(
        product_key, page, configs,
        has_prev=page > 0, has_next=page < total_pages - 1,
    )
    await _edit_admin_message(query, text, keyboard)



async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id):
        return

    if not context.user_data.get("awaiting_broadcast"):
        return

    if not message or not message.text:
        await message.reply_text("❌ لطفاً فقط متن ارسال کن.")
        return

    if message.text.strip() == "/cancel":
        context.user_data.pop("awaiting_broadcast", None)
        await message.reply_text("❌ ارسال همگانی لغو شد.", reply_markup=get_admin_panel_keyboard())
        return

    broadcast_text = message.text.strip()
    context.user_data.pop("awaiting_broadcast", None)

    user_ids = get_all_user_ids()
    success, failed = 0, 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=broadcast_text)
            success += 1
        except TelegramError:
            failed += 1

    await message.reply_text(
        f"✅ پیام همگانی ارسال شد.\nموفق: {success}\nناموفق: {failed}",
        reply_markup=get_admin_panel_keyboard(),
    )
    await log_admin_event(
        context,
        "پیام همگانی",
        f"موفق: {success} | ناموفق: {failed}\nمتن: {escape(broadcast_text[:200])}",
    )


async def admin_config_add_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id):
        return

    product_key = context.user_data.get("awaiting_config_add")
    if not product_key:
        return

    if not message or not message.text:
        await message.reply_text("❌ فقط متن (لینک) ارسال کن.")
        return

    text = message.text.strip()
    if text == "/cancel":
        context.user_data.pop("awaiting_config_add", None)
        await message.reply_text("❌ افزودن لغو شد.", reply_markup=get_admin_product_actions_keyboard(product_key))
        return

    if not is_valid_product_key(product_key):
        context.user_data.pop("awaiting_config_add", None)
        await message.reply_text("⚠️ محصول نامعتبر شده. دوباره از پنل شروع کن.", reply_markup=get_admin_panel_keyboard())
        return

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        await message.reply_text("❌ چیزی دریافت نشد. یک لینک (یا چند لینک، هر خط یکی) بفرست.")
        return

    if len(lines) == 1:
        add_config(product_key, lines[0])
        added = 1
    else:
        add_configs_batch([(product_key, link) for link in lines])
        added = len(lines)

    context.user_data.pop("awaiting_config_add", None)
    remaining = count_available_configs(product_key)
    await message.reply_text(
        f"✅ {added} لینک برای <code>{escape(product_key)}</code> اضافه شد.\n📦 موجودی فعلی: {remaining}",
        parse_mode="HTML",
        reply_markup=get_admin_product_actions_keyboard(product_key),
    )
    await log_admin_event(
        context, "افزودن کانفیگ (پنل)",
        f"محصول: <code>{escape(product_key)}</code>\nتعداد: {added}\nادمین: <code>{user.id}</code>",
    )


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return
    context.user_data.pop("awaiting_broadcast", None)
    context.user_data.pop("awaiting_config_add", None)
    await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=get_admin_panel_keyboard())


# ---------------------------------------------------------------------------
# Callback اصلی
# ---------------------------------------------------------------------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return None

    answer_state = {"done": False}

    async def mark_and_answer(text: str = None, alert: bool = False) -> None:
        answer_state["done"] = True
        await safe_answer(query, text, alert)

    try:
        if await _handle_admin_callbacks(query, context, query.data, mark_and_answer):
            return None
        return await _button_handler_impl(update, context, query, mark_and_answer)
    finally:
        if not answer_state["done"]:
            await safe_answer(query)


async def _button_handler_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, query, mark_and_answer):
    user = query.from_user
    user_id = user.id
    data = query.data
    full_name = " ".join(filter(None, [user.first_name, user.last_name])).strip() or "کاربر"

    if data == "check_membership":
        if CHANNEL_ID and not await check_user_membership(user_id, context.bot):
            await mark_and_answer("❌ هنوز عضو کانال نشدی!", alert=True)
            return None

        get_or_create_user(user_id, user.username, full_name)
        first_name = escape(user.first_name or "داداش")
        welcome_text = (
            f"✅ خوش اومدی <b>{first_name}</b>! عضویتت تأیید شد.\n\n"
            "با منوی زیر می‌تونی هرچی دلت خواست رو با بالاترین کیفیت و بهترین قیمت واسه خودت دست و پا کنی.\n\n"
            "🔸 واسه شروع، یکی از گزینه‌های زیرو خیلی یواش لمس کن:"
        )
        await delete_message_safe(query)
        await send_new_message(update, context, text=welcome_text, reply_markup=get_main_menu_keyboard(show_admin_panel=is_admin(user_id)))
        return None

    db_user = get_or_create_user(user_id, user.username, full_name)

    if data.startswith("approve_order_"):
        return await _handle_approve_order(query, context, user, data, mark_and_answer)

    if data.startswith("reject_order_"):
        return await _handle_reject_order(query, context, user, data, mark_and_answer)

    if data == "test_account":
        return await _handle_test_account(update, context, query, user, user_id, mark_and_answer)

    if data == "my_services":
        return await _handle_my_services(update, context, query, user_id)

    if data.startswith("myservice_") or data.startswith("svcrefresh_"):
        try:
            service_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            return None
        return await _handle_show_service(update, context, query, user_id, service_id, mark_and_answer)

    if data == "wallet_profile":
        return await _handle_wallet_profile(update, context, query, user_id, full_name, db_user)

    if data == "support":
        await delete_message_safe(query)
        await send_new_message(update, context, text="☎️ در دکمه زیر ( سوالات متداول ) سوالات پرتکرار شما آمده است.", reply_markup=get_support_keyboard())
        return None

    if data == "faq":
        faq_text = (
            "💡 <b>سوالات متداول</b> ⁉️\n\n"
            "1️⃣ فیلترشکن شما آیپی ثابته؟\n"
            "✅ سرویس ما مناسب ترید نیست و فقط لوکیشن ثابته.\n\n"
            "2️⃣ آیا امکان استفاده همزمان از چند دستگاه وجود دارد؟\n"
            "✅ خیر، هر اشتراک مخصوص یک دستگاه است.\n\n"
            "3️⃣ اگر مشکلی در اتصال داشتم چه کار کنم؟\n"
            "✅ ابتدا آموزش اتصال را مطالعه کنید. اگر مشکل حل نشد، به پشتیبانی پیام دهید."
        )
        await delete_message_safe(query)
        await send_new_message(update, context, text=faq_text, reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]))
        return None

    if data == "tutorial":
        await delete_message_safe(query)
        await send_new_message(update, context, text="همین الان یا با پروکسی وصلی یا با وی پی ان ،دنبال آموزش اتصال چی میگردی دیگه یابو؟ 😂", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]]))
        return None

    if data == "buy_config":
        await delete_message_safe(query)
        await send_new_message(update, context, text="🛍 لطفاً نوع سرویس مورد نظرتون رو انتخاب کنید:", reply_markup=get_buy_category_keyboard())
        return None

    if data == "buy_limited":
        await delete_message_safe(query)
        await send_new_message(update, context, text="⏳ لطفاً مدت زمان اشتراک را انتخاب کنید:", reply_markup=get_duration_menu_keyboard())
        return None

    if data == "buy_unlimited":
        await delete_message_safe(query)
        await send_new_message(update, context, text="♾ لطفاً یکی از پلن‌های حجم نامحدود را انتخاب کنید:", reply_markup=get_unlimited_menu_keyboard())
        return None

    if data in DURATION_CODE_TO_DAYS:
        duration_days = DURATION_CODE_TO_DAYS[data]
        await delete_message_safe(query)
        await send_new_message(update, context, text="🛒 یکی از طرح‌ها را انتخاب کنید:", reply_markup=get_products_keyboard(duration_days))
        return None

    if data in PRODUCTS:
        return await _handle_product_selection(update, context, query, user, user_id, data)

    if data == "main_menu":
        await delete_message_safe(query)
        await send_new_message(update, context, text="🔸 یکی از گزینه‌های زیر را انتخاب کن:", reply_markup=get_main_menu_keyboard(show_admin_panel=is_admin(user_id)))
        return None

    if data == "pay_card":
        return await _handle_pay_card(update, context, query, mark_and_answer)

    if data == "pay_stars":
        return await _handle_pay_stars(update, context, query, mark_and_answer)

    return None


async def _handle_approve_order(query, context, user, data, mark_and_answer):
    try:
        order_id = int(data.rsplit("_", 1)[-1])
    except (ValueError, IndexError):
        await mark_and_answer("شناسه سفارش نامعتبر.", alert=True)
        return None

    if not is_admin(user.id):
        await mark_and_answer("⛔️ فقط ادمین.", alert=True)
        return None

    order = get_order_by_id(order_id)
    if not order:
        await mark_and_answer("❌ سفارش پیدا نشد.", alert=True)
        return None
    if order["status"] == "completed":
        await mark_and_answer("ℹ️ قبلاً تأیید شده.", alert=True)
        return None

    customer_id = order["user_id"]

    if order["product_key"] == "topup":
        try:
            await _deliver_topup(order, context)
            await _edit_order_message(query, "✅ درخواست افزایش موجودی تأیید شد.")
            await log_admin_event(context, "تأیید دستی topup", f"سفارش: <code>{order_id}</code>")
        except Exception as e:
            print(f"Error delivering topup: {e}")
            await mark_and_answer("❌ خطا در اطلاع‌رسانی.", alert=True)
        return None

    try:
        customer = await context.bot.get_chat(customer_id)
        username = customer.username
    except TelegramError:
        username = None

    try:
        delivered = await _deliver_product(order, context, username=username)
    except Exception as e:
        print(f"Error delivering product: {e}")
        await mark_and_answer("❌ خطا در ارسال به کاربر.", alert=True)
        return None

    if not delivered:
        await mark_and_answer("❌ موجودی تمام شده! /addconfig", alert=True)
        return None

    await _edit_order_message(query, "✅ فاکتور تأیید شد و لینک ارسال گردید.")
    await log_admin_event(context, "تأیید دستی خرید", f"سفارش: <code>{order_id}</code>")
    return None


async def _handle_reject_order(query, context, user, data, mark_and_answer):
    try:
        order_id = int(data.rsplit("_", 1)[-1])
    except (ValueError, IndexError):
        await mark_and_answer("شناسه نامعتبر.", alert=True)
        return None

    if not is_admin(user.id):
        await mark_and_answer("⛔️ فقط ادمین.", alert=True)
        return None

    order = get_order_by_id(order_id)
    if not order:
        await mark_and_answer("❌ سفارش پیدا نشد.", alert=True)
        return None
    if order["status"] == "completed":
        await mark_and_answer("ℹ️ قبلاً تأیید شده.", alert=True)
        return None

    update_order_status(order_id, "failed")
    try:
        await context.bot.send_message(
            chat_id=order["user_id"],
            text="❌ رسید شما تأیید نشد. با پشتیبانی تماس بگیرید.",
        )
        await _edit_order_message(query, "❌ فاکتور رد شد.")
        await log_admin_event(context, "رد فاکتور", f"سفارش: <code>{order_id}</code>")
    except TelegramError as e:
        print(f"Error rejecting order: {e}")
        await mark_and_answer("❌ خطا در پردازش.", alert=True)
    return None


async def _edit_order_message(query, caption: str) -> None:
    try:
        await query.edit_message_caption(caption=caption)
    except TelegramError:
        try:
            await query.edit_message_text(caption)
        except TelegramError:
            pass


async def _handle_test_account(update, context, query, user, user_id, mark_and_answer):
    if has_used_test_account(user_id):
        await delete_message_safe(query)
        await send_new_message(
            update, context,
            text="⛔️ <b>شما قبلاً از اکانت تست استفاده کرده‌اید!</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 خرید کانفیگ", callback_data="buy_config")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]),
        )
        return None

    test_config = get_available_config("test_config")
    if not test_config:
        await delete_message_safe(query)
        await send_new_message(
            update, context,
            text="در حال حاضر سرویس تست به اتمام رسیده. ⏱",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]]),
        )
        return None

    mark_test_account_used(user_id)
    mark_config_sold(test_config["id"])

    create_user_service(
        user_id=user_id,
        username=user.username,
        service_type="test",
        product_key="test_config",
        config_id=test_config["id"],
        link=test_config["link"],
        size="100 مگابایت",
        duration_days=1,
    )

    await notify_admin_test_account(context, user, test_config["id"])
    await notify_admin_service_delivered(
        context, user_id, user.username, "test_config", "اکانت تست",
        test_config["id"], service_type="تستی",
    )

    caption = (
        "🎁 <b>سرویس تست شما فعال شد!</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 <b>نام کاربری:</b> <code>{user_id}_test</code>\n"
        "🌿 <b>نوع:</b> تست رایگان\n"
        "🇳🇱 <b>لوکیشن:</b> Netherlands\n"
        "⏳ <b>مدت:</b> 24 ساعت\n"
        "🗜 <b>حجم:</b> 100 مگابایت\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"🔗 <code>{test_config['link']}</code>"
    )
    await delete_message_safe(query)

    sent_message = None
    try:
        qr_bio = generate_qr_code(test_config["link"])
        sent_message = await context.bot.send_photo(
            chat_id=user_id,
            photo=qr_bio,
            caption=caption,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📚 آموزش اتصال", callback_data="tutorial")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]),
        )
    except Exception as e:
        print(f"Could not generate/send QR code for {user_id}: {e}")
        sent_message = await send_new_message(update, context, text=caption, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 آموزش اتصال", callback_data="tutorial")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
        ]))

    if sent_message is not None:
        try:
            await context.bot.pin_chat_message(
                chat_id=user_id, message_id=sent_message.message_id, disable_notification=True,
            )
        except TelegramError as e:
            print(f"Could not pin test-account message for {user_id}: {e}")

    return None


SERVICE_LOCATION_LABEL = "France 🇫🇷"


async def _handle_my_services(update, context, query, user_id):
    services = get_services_by_user(user_id)
    text = "🛍 <b>اشتراک‌های شما</b>\n\nروی هر سرویس کلیک کنید."
    buttons = []
    if services:
        for svc in services:
            label = _service_product_label(svc["product_key"])
            buttons.append([InlineKeyboardButton(
                f"{label} — {svc['start_date']}",
                callback_data=f"myservice_{svc['id']}",
            )])
    else:
        buttons.append([InlineKeyboardButton("هنوز سرویسی ندارید 🙁", callback_data="#")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    await delete_message_safe(query)
    await send_new_message(update, context, text=text, reply_markup=InlineKeyboardMarkup(buttons))
    return None


async def _resolve_xui_email(svc: dict) -> Optional[str]:
    """
    ایمیل کلاینت متناظر این سرویس را در x-ui پیدا می‌کند.
    اول ستون کش‌شده (xui_email) را نگاه می‌کند؛ اگر خالی بود، از روی subId
    توی لینک subscription جستجو می‌کند و نتیجه را برای دفعات بعد کش می‌کند.
    """
    cached = svc.get("xui_email")
    if cached:
        return cached

    sub_id = xui_db.extract_subid_from_link(svc.get("link"))
    if not sub_id:
        logger.warning(
            "Cannot extract subId from service link (service_id=%s): %r",
            svc.get("id"), svc.get("link"),
        )
        return None

    email = await asyncio.to_thread(xui_db.find_email_by_subid, sub_id)
    if email:
        try:
            set_service_xui_email(svc["id"], email)
        except Exception as e:
            logger.error(
                "Failed to cache xui_email for service %s: %s", svc.get("id"), e, exc_info=True
            )
    else:
        logger.warning(
            "No x-ui client found for subId=%s (service_id=%s)", sub_id, svc.get("id")
        )
    return email


async def _render_service_detail_text(svc: dict) -> str:
    if svc["service_type"] == "test":
        service_username = f"{svc['user_id']}_test"
    else:
        service_username = f"{svc['user_id']}_{svc['config_id']}"

    product_label = _service_product_label(svc["product_key"])

    email = await _resolve_xui_email(svc)
    info = await asyncio.to_thread(xui_db.get_client_info, email) if email else None

    if info:
        is_active = xui_db.is_active(info)
        status_text = "فعال ✅" if is_active else "غیرفعال ❌"

        up = int(info.get("up") or 0)
        down = int(info.get("down") or 0)
        total = int(info.get("total") or 0)
        usage_bytes = up + down
        usage = xui_db.format_bytes(usage_bytes)
        remaining = (
            "نامحدود ♾" if total <= 0 else xui_db.format_bytes(max(total - usage_bytes, 0))
        )
        expiry = xui_db.format_expiry(info.get("expiry_time"))
        # این دو مقدار در دیتابیس x-ui اصلاً ذخیره نمی‌شوند (نیاز به gRPC API
        # زنده‌ی Xray یا access.log دارند)، پس صادقانه «نامشخص» نمایش می‌دهیم.
        last_online = "نامشخص"
        client_info = "نامشخص"
    else:
        status_text = "نامشخص ❔ (کلاینت در دیتابیس x-ui پیدا نشد)"
        usage = "نامشخص"
        remaining = "نامشخص"
        expiry = "نامشخص"
        last_online = "نامشخص"
        client_info = "نامشخص"

    return (
        "📄 <b>جزئیات سرویس</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"📊 <b>وضعیت سرویس:</b> {status_text}\n"
        f"👤 <b>نام سرویس:</b> <code>{escape(service_username)}</code>\n"
        f"🌍 <b>موقعیت سرویس:</b> {SERVICE_LOCATION_LABEL}\n"
        f"🗂 <b>نام محصول:</b> {escape(product_label)}\n"
        "━━━━━━━━━━━━━━━\n"
        "🔋 <b>ترافیک:</b>\n"
        f"📥 حجم مصرفی: {escape(str(usage))}\n"
        f"💢 حجم باقی‌مانده: {escape(str(remaining))}\n\n"
        f"📅 <b>تاریخ اتمام:</b> {escape(str(expiry))}\n"
        "━━━━━━━━━━━━━━━\n"
        f"🔗 <b>لینک سرویس:</b>\n<code>{escape(svc['link'])}</code>\n\n"
        f"📶 <b>آخرین زمان اتصال:</b> {escape(str(last_online))}\n"
        f"🔄 <b>آخرین بروزرسانی:</b> {get_jalali_now()}\n"
        f"#️⃣ <b>کلاینت متصل شده:</b> {escape(str(client_info))}"
    )


async def _handle_show_service(update, context, query, user_id, service_id, mark_and_answer):
    await mark_and_answer("⏳ در حال دریافت اطلاعات...")

    svc = get_user_service_by_id(service_id)
    if not svc or svc["user_id"] != user_id:
        await delete_message_safe(query)
        await send_new_message(
            update, context,
            text="⛔️ این سرویس یافت نشد یا متعلق به شما نیست.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏘 بازگشت به لیست سرویس‌ها", callback_data="my_services")]]
            ),
        )
        return None

    text = await _render_service_detail_text(svc)
    await delete_message_safe(query)
    await send_new_message(update, context, text=text, reply_markup=get_service_detail_keyboard(service_id))
    return None


async def _handle_wallet_profile(update, context, query, user_id, full_name, db_user):
    orders_count = len(get_user_orders(user_id))
    now = get_jalali_now()
    text = (
        "🗂 <b>اطلاعات حساب:</b>\n\n"
        f"🪪 شناسه: <code>{user_id}</code>\n"
        f"👤 نام: {escape(full_name)}\n"
        f"👥 کد معرف: <code>{db_user['referral_code']}</code>\n"
        f"💰 موجودی: {format_toman(db_user['balance'])} تومان\n"
        f"🛒 سرویس‌ها: {orders_count} عدد\n"
        f"📆 {now}"
    )
    await delete_message_safe(query)
    await send_new_message(update, context, text=text, reply_markup=get_wallet_keyboard())
    return None


async def _handle_product_selection(update, context, query, user, user_id, data):
    product = PRODUCTS[data]
    size = product["size"]
    price = int(product["price"])
    duration_days = product["duration"]
    service_title = f"{size} / {duration_days} روزه"

    order_id = create_order(user_id, data, price)
    context.user_data["pending_order"] = {
        "type": "product",
        "product_key": data,
        "service_title": service_title,
        "duration_days": duration_days,
        "size": size,
        "price_toman": price,
        "order_id": order_id,
    }

    await notify_admin_purchase_request(context, user, data, service_title, price, order_id)

    order_text = build_order_text(get_safe_username(user), service_title, duration_days, size, price)
    await delete_message_safe(query)
    await send_new_message(
        update, context,
        text=order_text + "\n\n💳 روش پرداخت را انتخاب کن:",
        reply_markup=get_payment_method_keyboard(),
    )
    return None


async def _handle_pay_card(update, context, query, mark_and_answer):
    order_data = context.user_data.get("pending_order")
    if not order_data:
        await mark_and_answer("سفارش فعالی نیست. دوباره خرید کنید.")
        return None

    price_toman_int = order_data.get("price_toman")
    if price_toman_int is None:
        await mark_and_answer("قیمت نامعتبر است.")
        return None

    text = (
        f"مبلغ دقیق: <b>{format_rial_from_toman(price_toman_int)}</b> ریال\n\n"
        "<code>6219 8619 0176 8530</code>\n"
        "<b>بانک سامان - امیری اشکذری</b>\n\n"
        f"💰 {format_toman(price_toman_int)} تومان\n\n"
        "بیش از 5 دقیقه تأیید نشد، رسید بفرست."
    )
    await delete_message_safe(query)
    await send_new_message(
        update, context, text=text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 ارسال رسید", callback_data="send_receipt_step"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="buy_config"),
        ]]),
    )
    return None


async def _handle_pay_stars(update, context, query, mark_and_answer):
    order_data = context.user_data.get("pending_order")
    if not order_data:
        await mark_and_answer("سفارش فعالی نیست.", alert=True)
        return None

    price_toman_int = order_data.get("price_toman")
    order_id = order_data.get("order_id")
    if not price_toman_int or not order_id:
        await mark_and_answer("اطلاعات سفارش نامعتبر.", alert=True)
        return None

    stars_amount = max(1, round(int(price_toman_int) / TOMAN_PER_STAR))
    title = str(order_data.get("service_title") or "خرید از ربات")[:32]

    try:
        await delete_message_safe(query)
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=title,
            description=f"{title} - Telegram Stars",
            payload=f"order_{order_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(title, stars_amount)],
        )
    except TelegramError as e:
        print(f"Stars invoice error: {e}")
        await send_new_message(
            update, context,
            text="❌ خطا در ایجاد فاکتور Stars.",
            reply_markup=get_payment_method_keyboard(),
        )
    return None


# ---------------------------------------------------------------------------
# Conversation: رسید و افزایش موجودی
# ---------------------------------------------------------------------------

async def start_receipt_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await safe_answer(query)
    await delete_message_safe(query)
    await send_new_message(update, context, text="🖼 اسکرین‌شات رسید را ارسال کن.")
    return WAITING_FOR_RECEIPT


async def start_topup_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await safe_answer(query)
    await delete_message_safe(query)
    await send_new_message(
        update, context,
        text="💸 مبلغ را به تومان وارد کنید:\n⚠️ حداقل 50,000 — حداکثر 5,000,000",
    )
    return WAITING_FOR_TOPUP_AMOUNT


async def topup_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user

    if not message or not message.text:
        await message.reply_text("❌ فقط عدد ارسال کن.")
        return WAITING_FOR_TOPUP_AMOUNT

    if contains_profanity(message.text):
        await message.reply_text("خودتی 🖕")
        return WAITING_FOR_TOPUP_AMOUNT

    raw = message.text.strip().replace(",", "").replace("،", "").replace(" ", "")
    if not raw.isdigit():
        await message.reply_text("❌ فقط عدد معتبر بفرست.")
        return WAITING_FOR_TOPUP_AMOUNT

    amount = int(raw)
    if amount < 50000 or amount > 5000000:
        await message.reply_text("❌ مبلغ باید بین 50,000 تا 5,000,000 باشد.")
        return WAITING_FOR_TOPUP_AMOUNT

    order_id = create_order(user.id, "topup", amount)
    context.user_data["pending_order"] = {
        "type": "topup",
        "product_key": "topup",
        "service_title": "افزایش موجودی کیف پول",
        "duration_days": "-",
        "size": "-",
        "price_toman": amount,
        "order_id": order_id,
    }

    await notify_admin_purchase_request(
        context, user, "topup", "افزایش موجودی کیف پول", amount, order_id,
    )

    await message.reply_text(
        f"💰 {format_toman(amount)} تومان ثبت شد.\n\n💳 روش پرداخت:",
        reply_markup=get_payment_method_keyboard(),
    )
    return ConversationHandler.END


async def receipt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not message:
        return WAITING_FOR_RECEIPT

    file_id = None
    file_kind = None

    if message.photo:
        file_id = message.photo[-1].file_id
        file_kind = "photo"
    elif message.document and _is_image_document(message.document):
        file_id = message.document.file_id
        file_kind = "document-image"
    else:
        await message.reply_text("❌ رسید باید عکس (JPG/PNG/WEBP) باشد.")
        return WAITING_FOR_RECEIPT

    order = context.user_data.get("pending_order", {})
    if not order:
        await message.reply_text("سفارش پیدا نشد. دوباره خرید کنید.")
        return ConversationHandler.END

    is_topup = order.get("type") == "topup"
    username_text = get_safe_username(user)
    user_full_name = " ".join(filter(None, [user.first_name, user.last_name])).strip() or "نامشخص"

    user_details_text = (
        "👤 <b>مشخصات کاربر</b>\n\n"
        f"• نام: <b>{escape(user_full_name)}</b>\n"
        f"• یوزرنیم: {username_text}\n"
        f"• آیدی: <code>{user.id}</code>\n"
    )

    if is_topup:
        order_details_text = f"💳 <b>افزایش موجودی</b>\n• مبلغ: <b>{format_toman(order.get('price_toman', 0))} تومان</b>\n"
    else:
        order_details_text = (
            "🛍 <b>مشخصات خرید</b>\n\n"
            f"• سرویس: <b>{escape(str(order.get('service_title', 'نامشخص')))}</b>\n"
            f"• مبلغ: <b>{format_toman(order.get('price_toman', 0))} تومان</b>\n"
            f"• کد: <code>{escape(str(order.get('product_key', '')))}</code>\n"
        )

    await message.reply_text("✅ رسید دریافت شد.")

    order_id_for_admin = order.get("order_id")
    if not order_id_for_admin:
        await message.reply_text("خطای داخلی: سفارش معتبر نیست.")
        return ConversationHandler.END

    product_key_raw = str(order.get("product_key", "")).strip()
    if is_topup:
        stock_status_line = "💳 نوع: افزایش موجودی"
        stock_status_caption = "افزایش موجودی"
    else:
        stock_count = count_available_configs(product_key_raw) if product_key_raw else 0
        stock_status_line = f"📦 موجودی: {'✅' if stock_count > 0 else '❌'} ({stock_count})"
        stock_status_caption = "✅ موجود" if stock_count > 0 else "❌ ناموجود"

    admin_text = (
        "🚨 <b>رسید پرداخت جدید</b>\n\n"
        f"{user_details_text}\n{order_details_text}\n{stock_status_line}\n\n"
        f"🕒 {get_jalali_now()}\n📌 وضعیت: در انتظار تأیید"
    )

    admin_caption = f"رسید از {user.id} — {'topup' if is_topup else product_key_raw} — {stock_status_caption}"
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید", callback_data=f"approve_order_{order_id_for_admin}")],
        [InlineKeyboardButton("❌ رد", callback_data=f"reject_order_{order_id_for_admin}")],
    ])

    await notify_admin_receipt_submitted(context, user, order, is_topup)

    try:
        if file_kind == "document-image":
            await context.bot.send_document(
                chat_id=ADMIN_ID, document=file_id, caption=admin_caption,
                reply_markup=admin_keyboard, parse_mode="HTML",
            )
        else:
            await context.bot.send_photo(
                chat_id=ADMIN_ID, photo=file_id, caption=admin_caption,
                reply_markup=admin_keyboard, parse_mode="HTML",
            )
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="HTML")
    except TelegramError as e:
        print(f"Error sending receipt to admin: {e}")
        await message.reply_text("مشکلی در ارسال به ادمین پیش آمد.")

    if TRANSACTION_LOG_CHANNEL_ID:
        try:
            log_id = int(TRANSACTION_LOG_CHANNEL_ID)
            if file_kind == "document-image":
                await context.bot.send_document(chat_id=log_id, document=file_id, caption="🚨 کپی رسید")
            else:
                await context.bot.send_photo(chat_id=log_id, photo=file_id, caption="🚨 کپی رسید")
            await context.bot.send_message(chat_id=log_id, text=admin_text, parse_mode="HTML")
        except (ValueError, TypeError, TelegramError) as e:
            print(f"Log channel error: {e}")

    return ConversationHandler.END


# ---------------------------------------------------------------------------
# پرداخت Stars
# ---------------------------------------------------------------------------

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    payload = query.invoice_payload or ""

    if not payload.startswith("order_"):
        await query.answer(ok=False, error_message="سفارش نامعتبر است.")
        return

    try:
        order_id = int(payload.split("_", 1)[1])
    except (ValueError, IndexError):
        await query.answer(ok=False, error_message="سفارش نامعتبر است.")
        return

    order = get_order_by_id(order_id)
    if not order or order["status"] == "completed":
        await query.answer(ok=False, error_message="این سفارش دیگر معتبر نیست.")
        return

    await query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    payment = message.successful_payment if message else None
    if not payment or not user:
        return

    payload = payment.invoice_payload or ""
    if not payload.startswith("order_"):
        return

    try:
        order_id = int(payload.split("_", 1)[1])
    except (ValueError, IndexError):
        return

    order = get_order_by_id(order_id)
    if not order or order["status"] == "completed":
        return

    stars_amount = payment.total_amount
    order_with_meta = {**order, "order_id": order_id}

    if order["product_key"] == "topup":
        await _deliver_topup(order, context)
        await notify_admin_stars_purchase(context, user, order_with_meta, stars_amount)
        return

    await notify_admin_stars_purchase(context, user, order_with_meta, stars_amount)

    delivered = await _deliver_product(order, context, username=user.username)
    if not delivered:
        update_order_status(order_id, "pending")
        await context.bot.send_message(
            chat_id=order["user_id"],
            text="✅ پرداخت دریافت شد، ولی موجودی تمام شده. به‌زودی لینک ارسال می‌شود.",
        )
        await notify_admin(
            context,
            f"⚠️ سفارش <code>{order_id}</code> با Stars پرداخت شد ولی موجودی "
            f"<code>{escape(order['product_key'])}</code> تمام است.",
        )


# ---------------------------------------------------------------------------
# دیباگ
# ---------------------------------------------------------------------------

async def debug_get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if user and is_admin(user.id):
        if context.user_data.get("awaiting_broadcast"):
            await admin_broadcast_handler(update, context)
            return
        if context.user_data.get("awaiting_config_add"):
            await admin_config_add_message_handler(update, context)
            return

    if message and message.text and contains_profanity(message.text):
        await message.reply_text("خودتی 🖕")
        return

    chat = update.effective_chat
    if chat:
        print(f"Chat ID: {chat.id} | Type: {chat.type} | Title: {chat.title}")