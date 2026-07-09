from html import escape
from typing import Any, Optional

import jdatetime
import io
import qrcode
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from config import ADMIN_ID


def format_toman(amount: Any) -> str:
    try:
        return f"{int(amount):,}"
    except (TypeError, ValueError):
        return str(amount)


def format_rial_from_toman(toman: Any) -> str:
    try:
        return f"{int(toman) * 10:,}"
    except (TypeError, ValueError):
        return "0"


def get_safe_username(user) -> str:
    if user.username:
        return f"@{escape(user.username)}"
    full_name = " ".join(filter(None, [user.first_name, user.last_name])).strip()
    return escape(full_name) if full_name else f"کاربر {user.id}"


def get_jalali_now() -> str:
    return jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")


async def delete_message_safe(query) -> None:
    if not query or not query.message:
        return
    try:
        await query.message.delete()
    except TelegramError:
        pass


async def send_new_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "HTML",
):
    chat_id = None
    if update.effective_chat:
        chat_id = update.effective_chat.id
    elif update.callback_query and update.callback_query.message:
        chat_id = update.callback_query.message.chat_id

    if chat_id is None:
        return None

    return await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


def build_order_text(username: str, service_title: str, duration_days: str, size: str, amount_toman: int) -> str:
    return (
        f"👤 برا این داری میخری: {username}\n\n"
        f"🔐 سرویس: {service_title}\n\n"
        f"📆 مدت استفاده: {duration_days} روز\n\n"
        f"👥 حجم اکانت: {size}\n\n"
        f"💶 مبلغ: {amount_toman:,} تومان"
    )


def build_service_delivered_text(
    user_id: int,
    config_id: int,
    size: str,
    duration_days: str,
    link: str,
    location: str = "projectv",
) -> str:
    service_username = f"{user_id}_{config_id}"
    return (
        "✅ سرویس با موفقیت ایجاد شد\n\n"
        f"👤 نام کاربری سرویس : {service_username}\n"
        f"🌿 نام سرویس: {escape(str(size))} - {escape(str(duration_days))} روزه\n"
        f"🇺🇳 لوکیشن: {escape(location)}\n"
        f"⏳ مدت زمان: {escape(str(duration_days))} روز\n"
        f"🗜 حجم سرویس: {escape(str(size))}\n\n"
        "لینک اتصال:\n"
        f"<code>{escape(link)}</code>\n\n"
        "🧑‍🦯 شما می‌توانید شیوه اتصال را با فشردن دکمه زیر و انتخاب سیستم عامل خود دریافت کنید."
    )


def generate_qr_code(data: str) -> io.BytesIO:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    bio.name = "qrcode.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio


async def safe_answer(query, text=None, alert=False):
    if not query:
        return
    try:
        await query.answer(text=text, show_alert=alert)
    except TelegramError:
        pass
    except Exception as e:
        print(f"safe_answer error: {e}")


# ---------------------------------------------------------------------------
# گزارش‌ها و لاگ ادمین
# ---------------------------------------------------------------------------

async def notify_admin(context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode: str = "HTML") -> bool:
    if not ADMIN_ID:
        return False
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode=parse_mode)
        return True
    except TelegramError as e:
        print(f"Error sending admin notification: {e}")
        return False


async def log_admin_event(context: ContextTypes.DEFAULT_TYPE, event_title: str, details: str) -> None:
    text = (
        f"📋 <b>{escape(event_title)}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{details}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🕒 {get_jalali_now()}"
    )
    await notify_admin(context, text)


def _user_report_block(user) -> str:
    username = get_safe_username(user)
    return (
        f"🆔 <b>شناسه:</b> <code>{user.id}</code>\n"
        f"👤 <b>یوزرنیم:</b> {username}\n"
    )


async def notify_admin_purchase_request(
    context: ContextTypes.DEFAULT_TYPE,
    user,
    product_key: str,
    product_label: str,
    amount: int,
    order_id: int,
) -> None:
    details = (
        f"{_user_report_block(user)}"
        f"📦 <b>محصول:</b> {escape(product_label)}\n"
        f"🔑 <b>کلید:</b> <code>{escape(product_key)}</code>\n"
        f"💰 <b>مبلغ:</b> {format_toman(amount)} تومان\n"
        f"🧾 <b>شناسه سفارش:</b> <code>{order_id}</code>\n"
        f"📌 <b>وضعیت:</b> در انتظار پرداخت"
    )
    await log_admin_event(context, "ثبت درخواست خرید", details)


async def notify_admin_receipt_submitted(
    context: ContextTypes.DEFAULT_TYPE,
    user,
    order: dict,
    is_topup: bool,
) -> None:
    product_key = str(order.get("product_key", "نامشخص"))
    if is_topup:
        product_label = "افزایش موجودی کیف پول"
    else:
        product_label = str(order.get("service_title", product_key))

    details = (
        f"{_user_report_block(user)}"
        f"📦 <b>محصول:</b> {escape(product_label)}\n"
        f"🔑 <b>کلید:</b> <code>{escape(product_key)}</code>\n"
        f"💰 <b>مبلغ:</b> {format_toman(order.get('price_toman', 0))} تومان\n"
        f"🧾 <b>شناسه سفارش:</b> <code>{order.get('order_id', 'نامشخص')}</code>\n"
        f"📌 <b>وضعیت:</b> رسید ارسال شد — در انتظار تأیید"
    )
    await log_admin_event(context, "دریافت رسید پرداخت", details)


async def notify_admin_test_account(context: ContextTypes.DEFAULT_TYPE, user, config_id: int) -> None:
    details = (
        f"{_user_report_block(user)}"
        f"📦 <b>محصول:</b> اکانت تست\n"
        f"🔑 <b>کلید:</b> <code>test_config</code>\n"
        f"🧾 <b>شناسه کانفیگ:</b> <code>{config_id}</code>\n"
        f"📌 <b>وضعیت:</b> تحویل شد"
    )
    await log_admin_event(context, "دریافت اکانت تست", details)


async def notify_admin_stars_purchase(
    context: ContextTypes.DEFAULT_TYPE,
    user,
    order: dict,
    stars_amount: int,
) -> None:
    is_topup = order.get("product_key") == "topup"
    if is_topup:
        title = "افزایش موجودی با Telegram Stars"
        product_label = "افزایش موجودی کیف پول"
    else:
        title = "خرید با Telegram Stars"
        product_label = str(order.get("service_title") or order.get("product_key", "نامشخص"))

    details = (
        f"{_user_report_block(user)}"
        f"📦 <b>محصول:</b> {escape(product_label)}\n"
        f"🔑 <b>کلید:</b> <code>{escape(str(order.get('product_key', 'نامشخص')))}</code>\n"
        f"💰 <b>مبلغ:</b> {format_toman(order.get('price', order.get('price_toman', 0)))} تومان\n"
        f"⭐️ <b>Stars:</b> {stars_amount}\n"
        f"🧾 <b>شناسه سفارش:</b> <code>{order.get('id', order.get('order_id', 'نامشخص'))}</code>\n"
        f"📌 <b>وضعیت:</b> پرداخت موفق"
    )
    await log_admin_event(context, title, details)


async def notify_admin_service_delivered(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    username: Optional[str],
    product_key: str,
    product_label: str,
    config_id: int,
    service_type: str = "پولی",
) -> None:
    username_display = f"@{escape(username)}" if username else f"کاربر {user_id}"
    details = (
        f"🆔 <b>شناسه:</b> <code>{user_id}</code>\n"
        f"👤 <b>یوزرنیم:</b> {username_display}\n"
        f"📦 <b>محصول:</b> {escape(product_label)}\n"
        f"🔑 <b>کلید:</b> <code>{escape(product_key)}</code>\n"
        f"🏷 <b>نوع سرویس:</b> {escape(service_type)}\n"
        f"🧾 <b>شناسه کانفیگ:</b> <code>{config_id}</code>\n"
        f"📌 <b>وضعیت:</b> تحویل موفق"
    )
    await log_admin_event(context, "تحویل موفق سرویس", details)
