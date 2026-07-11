from html import escape, unescape
from typing import Any, Dict, Optional

import jdatetime
import io
import re
import random
import httpx
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
from qrcode.image.styles.colormasks import RadialGradiantColorMask
from PIL import Image, ImageDraw, ImageFilter, ImageFont
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


def generate_qr_code(data: str, brand: str = "ArsalanVPN") -> io.BytesIO:
    """یک QR Code شیک با ماژول‌های گرد، گرادیان رنگی و پس‌زمینه‌ی تزئینی می‌سازد."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    qr_img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(radius_ratio=0.9),
        color_mask=RadialGradiantColorMask(
            back_color=(255, 255, 255),
            center_color=(30, 58, 138),   # indigo
            edge_color=(88, 28, 135),     # violet
        ),
    ).convert("RGBA")
    qr_size = qr_img.size[0]

    # کارت سفید گرد پشت QR برای حفظ کنتراست و quiet zone
    card_pad = 60
    card_size = qr_size + card_pad * 2
    card = Image.new("RGBA", (card_size, card_size), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle(
        [0, 0, card_size - 1, card_size - 1], radius=48, fill=(255, 255, 255, 255)
    )
    card.paste(qr_img, (card_pad, card_pad), qr_img)

    # سایه‌ی نرم زیر کارت
    shadow = Image.new("RGBA", (card_size + 40, card_size + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [20, 26, card_size + 20, card_size + 26], radius=48, fill=(0, 0, 0, 140)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))

    # بوم پس‌زمینه با گرادیان بنفش تیره به سرمه‌ای
    pad_top, pad_bottom, pad_side = 130, 90, 70
    W = card_size + pad_side * 2
    H = card_size + pad_top + pad_bottom
    bg = Image.new("RGB", (W, H), (0, 0, 0))
    top_color, bottom_color = (23, 15, 60), (10, 12, 38)
    px = bg.load()
    for y in range(H):
        t = y / H
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        for x in range(W):
            px[x, y] = (r, g, b)
    bg = bg.convert("RGBA")

    # هاله‌ی نوری نرم پشت کارت
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = W // 2, pad_top + card_size // 2
    max_r = card_size // 2 + 90
    for i in range(max_r, 0, -4):
        alpha = int(70 * (1 - i / max_r))
        gd.ellipse([cx - i, cy - i, cx + i, cy + i], fill=(124, 92, 255, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(30))
    bg = Image.alpha_composite(bg, glow)

    # نقطه‌های ریز نورانی برای بافت
    dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    random.seed(7)
    for _ in range(70):
        x, y = random.randint(0, W), random.randint(0, H)
        r = random.choice([1, 1, 2])
        a = random.randint(40, 130)
        dd.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, a))
    bg = Image.alpha_composite(bg, dots)

    bg.alpha_composite(shadow, (pad_side - 20, pad_top - 26))
    bg.alpha_composite(card, (pad_side, pad_top))

    # گوشه‌های تزئینی برای حس تکنولوژیک
    accent = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ad = ImageDraw.Draw(accent)
    accent_color, L, thick = (167, 139, 250, 200), 46, 6
    tr_x, bl_y = pad_side + card_size + 8, pad_top + card_size + 8
    corners = [
        [(pad_side - 8, pad_top - 8), (pad_side - 8 + L, pad_top - 8), (pad_side - 8, pad_top - 8), (pad_side - 8, pad_top - 8 + L)],
        [(tr_x, pad_top - 8), (tr_x - L, pad_top - 8), (tr_x, pad_top - 8), (tr_x, pad_top - 8 + L)],
        [(pad_side - 8, bl_y), (pad_side - 8 + L, bl_y), (pad_side - 8, bl_y), (pad_side - 8, bl_y - L)],
        [(tr_x, bl_y), (tr_x - L, bl_y), (tr_x, bl_y), (tr_x, bl_y - L)],
    ]
    for p1, p2, p3, p4 in corners:
        ad.line([p1, p2], fill=accent_color, width=thick)
        ad.line([p3, p4], fill=accent_color, width=thick)
    bg.alpha_composite(accent)

    # عنوان برند و زیرنویس
    draw = ImageDraw.Draw(bg)
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
        font_sub = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    tb = draw.textbbox((0, 0), brand, font=font_title)
    draw.text(((W - (tb[2] - tb[0])) / 2, 34), brand, font=font_title, fill=(255, 255, 255, 255))

    sub_text = "Scan to connect"
    sb = draw.textbbox((0, 0), sub_text, font=font_sub)
    draw.text(((W - (sb[2] - sb[0])) / 2, H - pad_bottom + 22), sub_text, font=font_sub, fill=(200, 190, 255, 230))

    bio = io.BytesIO()
    bio.name = "qrcode.png"
    bg.convert("RGB").save(bio, "PNG")
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


# ---------------------------------------------------------------------------
# دریافت وضعیت لحظه‌ای سرویس از روی لینک اشتراک (صفحه‌ی Subscription Info پنل)
# ---------------------------------------------------------------------------

_SUB_INFO_LABELS = [
    "Subscription ID",
    "Email",
    "Status",
    "Downloaded",
    "Uploaded",
    "Usage",
    "Total quota",
    "Remaining",
    "Last Online",
    "Expiry",
]

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


def _html_to_lines(html: str) -> list:
    """صفحه HTML را به یک لیست از خط‌های متنی قابل‌خواندن تبدیل می‌کند."""
    cleaned = _SCRIPT_STYLE_RE.sub(" ", html)
    cleaned = _TAG_RE.sub("\n", cleaned)
    cleaned = unescape(cleaned)
    lines = [ln.strip() for ln in cleaned.splitlines()]
    return [ln for ln in lines if ln]


def _pair_labeled_values(lines: list) -> Dict[str, str]:
    """خط‌های متنی صفحه را بر اساس برچسب‌های شناخته‌شده جفت (برچسب -> مقدار) می‌کند."""
    result: Dict[str, str] = {}
    n = len(lines)
    for i, line in enumerate(lines):
        for label in _SUB_INFO_LABELS:
            if label in result:
                continue
            if line == label or line.lower() == label.lower():
                if i + 1 < n and lines[i + 1] not in _SUB_INFO_LABELS:
                    result[label] = lines[i + 1]
                break
            if line.lower().startswith(label.lower()) and line != label:
                rest = line[len(label):].strip(" \t:：-")
                if rest:
                    result[label] = rest
                break
    return result


def _parse_userinfo_header(header_value: str) -> Dict[str, str]:
    """پارس هدر استاندارد Subscription-Userinfo (upload=..; download=..; total=..; expire=..)."""
    data = {}
    for part in header_value.split(";"):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            data[key.strip().lower()] = value.strip()
    return data


async def fetch_subscription_stats(link: str) -> Optional[Dict[str, Any]]:
    """
    اطلاعات لحظه‌ای مصرف را از روی لینک اشتراک سرویس می‌خواند (همون صفحه‌ای که
    با باز کردن لینک در مرورگر دیده می‌شه). اگر پنل هدر استاندارد
    Subscription-Userinfo را هم بفرستد، به‌عنوان منبع کمکی/پشتیبان استفاده می‌شه.
    در صورت هر گونه خطا (قطعی سرور، تغییر قالب صفحه و ...) مقدار None برمی‌گردد
    و بخش فراخوان باید با نمایش «نامشخص» با آن کنار بیاید.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False, follow_redirects=True) as client:
            resp = await client.get(link, headers=headers)
    except httpx.HTTPError as e:
        print(f"fetch_subscription_stats error for {link}: {e}")
        return None

    if resp.status_code != 200:
        print(f"fetch_subscription_stats: HTTP {resp.status_code} for {link}")
        return None

    parsed = _pair_labeled_values(_html_to_lines(resp.text))

    userinfo_header = resp.headers.get("subscription-userinfo") or resp.headers.get("Subscription-Userinfo")
    header_info = _parse_userinfo_header(userinfo_header) if userinfo_header else {}

    status_raw = parsed.get("Status", "")
    is_active = status_raw.strip().lower() == "active" if status_raw else None

    result = {
        "email": parsed.get("Email"),
        "status_raw": status_raw or None,
        "is_active": is_active,
        "downloaded": parsed.get("Downloaded"),
        "uploaded": parsed.get("Uploaded"),
        "usage": parsed.get("Usage"),
        "total_quota": parsed.get("Total quota"),
        "remaining": parsed.get("Remaining"),
        "last_online": parsed.get("Last Online"),
        "expiry": parsed.get("Expiry"),
        "header_info": header_info,
    }

    if not any(v for k, v in result.items() if k not in ("header_info", "is_active")):
        # هیچ کدام از برچسب‌های شناخته‌شده پیدا نشدن؛ یعنی این صفحه اصلاً همون
        # قالب مورد انتظار نیست (مثلاً پنل عوض شده یا لینک نامعتبره)
        return None

    return result