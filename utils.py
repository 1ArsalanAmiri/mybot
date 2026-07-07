from html import escape
from typing import Any, Optional
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from telegram import InlineKeyboardMarkup
import qrcode
import io


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


def build_admin_order_text(user, order: dict) -> str:
    username_text = get_safe_username(user)

    return (
        "🚨 <b>رسید پرداخت جدید</b>\n\n"
        f"👤 <b>کاربر:</b> {username_text}\n\n"
        f"🆔 <b>آیدی:</b> <code>{user.id}</code>\n\n"
        f"👤 <b>نام:</b> {escape(' '.join(filter(None, [user.first_name, user.last_name])).strip() or 'نامشخص')}</b>\n\n"
        f"🛍 <b>سرویس درخواستی:</b> {escape(str(order.get('service_title', 'نامشخص')))}\n\n"
        f"📆 <b>مدت:</b> {escape(str(order.get('duration_days', 'نامشخص')))} روز\n\n"
        f"👥 <b>حجم:</b> {escape(str(order.get('size', 'نامشخص')))}\n\n"
        f"💰 <b>مبلغ فاکتور:</b> {format_toman(order.get('price_toman', 'نامشخص'))} تومان\n\n"
        f"🧾 <b>کد محصول:</b> <code>{escape(str(order.get('product_key', 'نامشخص')))}</code>\n"
        "برای تایید این رسید و شارژ حساب کاربر اقدام کنید."
    )


def build_service_delivered_text(
    user_id: int,
    config_id: int,
    size: str,
    duration_days: str,
    link: str,
    location: str = "projectv",
) -> str:
    """
    متن نهایی‌ای که هنگام تایید سفارش (یا تحویل هر لینک اشتراک) برای کاربر ارسال می‌شود.
    فرمت دقیقاً مطابق نمونه‌ای است که خودت خواستی.
    """
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
    bio.name = 'qrcode.png'
    img.save(bio, 'PNG')
    bio.seek(0)

    return bio