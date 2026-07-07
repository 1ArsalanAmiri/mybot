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
            InlineKeyboardButton("🎁 هدیه", callback_data="gift"),
            InlineKeyboardButton("📚 آموزش اتصال", callback_data="tutorial"),
        ],
        [
            InlineKeyboardButton("👨‍💻 پشتیبانی", callback_data="support"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_duration_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("یک ماه ⏳", callback_data="show_1m_plans")],
        [InlineKeyboardButton("دو ماه ⏳", callback_data="show_2m_plans")],
        [InlineKeyboardButton("سه ماه ⏳", callback_data="show_3m_plans")],
        [InlineKeyboardButton("یک‌ساله ⏳", callback_data="show_1y_plans")],
        [InlineKeyboardButton("🔙 برگردیم به منوی اصلی", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_products_by_duration(duration_days: str) -> List[Tuple[str, Dict[str, str]]]:
    return [
        (callback_data, product)
        for callback_data, product in PRODUCTS.items()
        if product.get("duration") == duration_days
    ]


def get_products_keyboard(duration_days: str) -> InlineKeyboardMarkup:
    keyboard = []

    for callback_data, product in get_products_by_duration(duration_days):
        size = product["size"]
        price = format_toman(product["price"])
        keyboard.append([InlineKeyboardButton(f"🔋 {size} - {price} تومان", callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("🔙 برگشت به انتخاب مدت", callback_data="buy_config")])
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
        [
            InlineKeyboardButton("💳 افزایش موجودی", callback_data="add_balance"),
            InlineKeyboardButton("🎟 کد تخفیف", callback_data="discount_code"),
        ],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)