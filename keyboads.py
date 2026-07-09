from typing import Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


PRODUCTS: Dict[str, Dict[str, str]] = {
    "buy_1m_10gb": {"size": "10 گیگ", "price": "80000", "duration": "30"},
    "buy_1m_15gb": {"size": "15 گیگ", "price": "90000", "duration": "30"},
    "buy_1m_20gb": {"size": "20 گیگ", "price": "120000", "duration": "30"},
    "buy_1m_30gb": {"size": "30 گیگ", "price": "180000", "duration": "30"},
    "buy_1m_50gb": {"size": "50 گیگ", "price": "300000", "duration": "30"},
    "buy_1m_100gb": {"size": "100 گیگ", "price": "510000", "duration": "30"},
    "buy_1m_200gb": {"size": "200 گیگ", "price": "860000", "duration": "30"},

    "buy_2m_20gb": {"size": "20 گیگ", "price": "140000", "duration": "60"},
    "buy_2m_30gb": {"size": "30 گیگ", "price": "200000", "duration": "60"},
    "buy_2m_50gb": {"size": "50 گیگ", "price": "320000", "duration": "60"},
    "buy_2m_100gb": {"size": "100 گیگ", "price": "550000", "duration": "60"},
    "buy_2m_200gb": {"size": "200 گیگ", "price": "980000", "duration": "60"},
    "buy_2m_400gb": {"size": "400 گیگ", "price": "1580000", "duration": "60"},

    "buy_3m_30gb": {"size": "30 گیگ", "price": "220000", "duration": "90"},
    "buy_3m_60gb": {"size": "60 گیگ", "price": "400000", "duration": "90"},
    "buy_3m_90gb": {"size": "90 گیگ", "price": "580000", "duration": "90"},
    "buy_3m_150gb": {"size": "150 گیگ", "price": "880000", "duration": "90"},
    "buy_3m_300gb": {"size": "300 گیگ", "price": "1400000", "duration": "90"},

    "buy_1y_600gb": {"size": "600 گیگ", "price": "2640000", "duration": "365"},
    "buy_1y_1tb": {"size": "1 ترابایت", "price": "4000000", "duration": "365"},
}

# همه‌ی محصولات بالا از نوع "محدودیت حجم" هستند مگر اینکه category دیگری داشته باشند
for _key in PRODUCTS:
    PRODUCTS[_key].setdefault("category", "limited")

# محصولات حجم نامحدود (سرور اشتراکی)
# نکته: قیمت پلن یک‌ماهه طبق درخواست کارفرما 80000 تومان است.
# قیمت پلن‌های 3/6/12 ماهه به صورت پیش‌فرض و تخمینی تعیین شده و باید توسط ادمین در همین‌جا نهایی شود.
PRODUCTS.update({
    "buy_un_1m": {"size": "نامحدود", "price": "90000", "duration": "30", "category": "unlimited"},
    "buy_un_3m": {"size": "نامحدود", "price": "270000", "duration": "90", "category": "unlimited"},
    "buy_un_6m": {"size": "نامحدود", "price": "540000", "duration": "180", "category": "unlimited"},
    "buy_un_1y": {"size": "نامحدود", "price": "1080000", "duration": "365", "category": "unlimited"},
})

UNLIMITED_DURATION_LABELS = {
    "30": "یک ماهه",
    "90": "سه ماهه",
    "180": "شش ماهه",
    "365": "یکساله",
}


DURATION_CODE_TO_DAYS = {
    "show_1m_plans": "30",
    "show_2m_plans": "60",
    "show_3m_plans": "90",
    "show_1y_plans": "365",
}


def format_toman(amount) -> str:
    try:
        return f"{int(amount):,}"
    except (TypeError, ValueError):
        return str(amount)


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🛒 خرید کانفیگ", callback_data="buy_config"),
            InlineKeyboardButton("⏱ اکانت تست", callback_data="test_account"),
        ],
        [
            InlineKeyboardButton("📁 سرویس‌های من", callback_data="my_services"),
            InlineKeyboardButton("🗂 کیف پول و حساب کاربری", callback_data="wallet_profile"),
        ],
        [
            InlineKeyboardButton("📢 کانال ما", url="https://t.me/ArsalanVPN_channel"),
            InlineKeyboardButton("📚 آموزش اتصال", callback_data="tutorial"),
        ],
        [
            InlineKeyboardButton("👨‍💻 پشتیبانی", callback_data="support"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_buy_category_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🔋 دارای محدودیت حجم (شخصی و پرسرعت)", callback_data="buy_limited")],
        [InlineKeyboardButton("♾ حجم نامحدود (سرور اشتراکی)", callback_data="buy_unlimited")],
        [InlineKeyboardButton("🔙 برگردیم به منوی اصلی", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_duration_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("یک ماه ⏳", callback_data="show_1m_plans")],
        [InlineKeyboardButton("دو ماه ⏳", callback_data="show_2m_plans")],
        [InlineKeyboardButton("سه ماه ⏳", callback_data="show_3m_plans")],
        [InlineKeyboardButton("یک‌ساله ⏳", callback_data="show_1y_plans")],
        [InlineKeyboardButton("🔙 برگشت به انتخاب نوع سرویس", callback_data="buy_config")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_products_by_duration(duration_days: str, category: str = "limited") -> List[Tuple[str, Dict[str, str]]]:
    return [
        (callback_data, product)
        for callback_data, product in PRODUCTS.items()
        if product.get("duration") == duration_days and product.get("category", "limited") == category
    ]


def get_products_by_category(category: str) -> List[Tuple[str, Dict[str, str]]]:
    items = [
        (callback_data, product)
        for callback_data, product in PRODUCTS.items()
        if product.get("category", "limited") == category
    ]
    return sorted(items, key=lambda kv: int(kv[1].get("duration", 0)))


def get_products_keyboard(duration_days: str, category: str = "limited") -> InlineKeyboardMarkup:
    keyboard = []

    for callback_data, product in get_products_by_duration(duration_days, category):
        size = product["size"]
        price = format_toman(product["price"])
        keyboard.append([InlineKeyboardButton(f"🔋 {size} - {price} تومان", callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("🔙 برگشت به انتخاب مدت", callback_data="buy_limited")])
    keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_unlimited_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = []

    for callback_data, product in get_products_by_category("unlimited"):
        label = UNLIMITED_DURATION_LABELS.get(product.get("duration", ""), f"{product.get('duration')} روزه")
        price = format_toman(product["price"])
        keyboard.append([InlineKeyboardButton(f"♾ {label} - {price} تومان", callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("🔙 برگشت به انتخاب نوع سرویس", callback_data="buy_config")])
    keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_payment_method_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💳 1- کارت به کارت", callback_data="pay_card")],
        [InlineKeyboardButton("⭐️ 2- Telegram Stars", callback_data="pay_stars")],
        [InlineKeyboardButton("🔙 3- برگردیم منوی اصلی", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_support_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💡 سوالات متداول", callback_data="faq")],
        [InlineKeyboardButton("💬 ارسال پیام به پشتیبانی", url="https://t.me/arsalanvpn1_support")],
        [InlineKeyboardButton("🔙 برگردیم به منوی اصلی", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_wallet_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💳 افزایش موجودی", callback_data="add_balance")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ---------------------------------------------------------------------------
# پنل ادمین
# ---------------------------------------------------------------------------

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📦 موجودی محصولات", callback_data="admin_stock")],
        [InlineKeyboardButton("👥 کاربران دارای سرویس", callback_data="admin_users_0")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📚 راهنمای ادمین", callback_data="admin_help_panel")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_users_pagination_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons = []
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"admin_users_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"admin_users_{page + 1}"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)


def get_admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]
    ])