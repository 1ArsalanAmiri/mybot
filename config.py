import os

BOT_TOKEN = "8773239091:AAETY7lxUm1JmydlkW2J8k2cu5gYjG2-S4M"
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN تنظیم نشده است. لطفاً توکن را به صورت Environment Variable ست کن."
    )

CHANNEL_ID = os.getenv("CHANNEL_ID", "@ArsalanVPN_Channel")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5737414011"))
TRANSACTION_LOG_CHANNEL_ID = int(os.getenv("TRANSACTION_LOG_CHANNEL_ID", "-1004491596177"))
TOMAN_PER_STAR = int(os.getenv("TOMAN_PER_STAR", "2000"))

DB_PATH = os.getenv("DB_PATH", "bot_database.db")

# مسیر دیتابیس پنل x-ui (فقط خوانده می‌شود، هیچ‌وقت نوشته نمی‌شود — نگاه کن به xui_db.py)
XUI_DB_PATH = os.getenv("XUI_DB_PATH", "/etc/x-ui/x-ui.db")

# ---------------------------------------------------------------------------
# اتصال نوشتاری (REST API) به پنل x-ui — نگاه کن به xui_api.py
# ساخت/حذف/ویرایش کلاینت همیشه از طریق همین API انجام می‌شود، نه با دست‌کاری
# مستقیم دیتابیس (که چون Xray کانفیگ را فقط موقع استارت می‌خواند، تا ریستارت
# کامل سرویس x-ui از کلاینت جدید خبردار نمی‌شد و همه‌ی کاربران فعال قطع می‌شدند).
#
# ⚠️ امنیتی: این مقادیر داخل چت به ربات داده شدند. پیشنهاد می‌شود:
#   ۱) پسورد ادمین پنل x-ui را همین الان از پنل عوض کنید،
#   ۲) به‌جای هاردکد این‌ها در فایل، از Environment Variable استفاده کنید.
# ---------------------------------------------------------------------------
# XUI_PANEL_URL = os.getenv("XUI_PANEL_URL", "https://d1.trapxan.ir:31904/ruABWX2VUALMAAuMsd/")
XUI_PANEL_URL = "https://127.0.0.1:31904/ruABWX2VUALMAAuMsd/"
XUI_PANEL_USERNAME = os.getenv("XUI_PANEL_USERNAME", "admin")
XUI_PANEL_PASSWORD = os.getenv("XUI_PANEL_PASSWORD", "1234")

# ---------------------------------------------------------------------------
# انتخاب Inbound برای هر نقش — عمداً هاردکد نشده. اگر خالی/None بماند، ربات
# به‌صورت داینامیک از روی جدول inbounds تصمیم می‌گیرد (نگاه کن به
# xui_api.resolve_inbound_id). اگر چند inbound دارید و می‌خواهید دستی مشخص
# کنید کدام برای تست و کدام برای هدیه‌ی Referral ساخته شود، شناسه‌ی عددیش را
# اینجا بگذارید (همان id ستون اول جدول inbounds).
# ---------------------------------------------------------------------------
TEST_ACCOUNT_INBOUND_ID = os.getenv("TEST_ACCOUNT_INBOUND_ID")
TEST_ACCOUNT_INBOUND_ID = int(TEST_ACCOUNT_INBOUND_ID) if TEST_ACCOUNT_INBOUND_ID else None

REFERRAL_GIFT_INBOUND_ID = os.getenv("REFERRAL_GIFT_INBOUND_ID")
REFERRAL_GIFT_INBOUND_ID = int(REFERRAL_GIFT_INBOUND_ID) if REFERRAL_GIFT_INBOUND_ID else None

# نگاشت دستی و اختیاری هر product_key به یک inbound id مشخص. اگر برای یک
# product_key ای اینجا چیزی نبود، همان منطق داینامیک بالا اعمال می‌شود.
# مثال: {"buy_un_1m": 4, "buy_1m_10gb": 1}
PRODUCT_INBOUND_MAP = {}

# اکانت تست خودکار (بخش ۱)
TEST_ACCOUNT_VOLUME_GB = float(os.getenv("TEST_ACCOUNT_VOLUME_GB", "1"))
TEST_ACCOUNT_DURATION_HOURS = int(os.getenv("TEST_ACCOUNT_DURATION_HOURS", "24"))

# سیستم Referral (بخش ۶)
REFERRAL_REQUIRED_INVITES = int(os.getenv("REFERRAL_REQUIRED_INVITES", "5"))
REFERRAL_GIFT_LABEL = os.getenv("REFERRAL_GIFT_LABEL", "30 روزه نامحدود 💎")
REFERRAL_GIFT_DURATION_DAYS = int(os.getenv("REFERRAL_GIFT_DURATION_DAYS", "30"))

# نام سرویس‌های systemd برای بخش «وضعیت سرورها» در پنل ادمین (بخش ۲)
XUI_SERVICE_NAME = os.getenv("XUI_SERVICE_NAME", "x-ui")
# اگر ربات با systemd اجرا می‌شود، اسم سرویسش را اینجا ست کن تا در مانیتورینگ نمایش داده شود
BOT_SERVICE_NAME = os.getenv("BOT_SERVICE_NAME", "")

# لیبل نمایشی سرور برای بخش مانیتورینگ (بخش ۲) — طبق تصمیم فعلی فقط همین سرور (لوکال) پایش می‌شود
SERVER_DISPLAY_LABEL = os.getenv("SERVER_DISPLAY_LABEL", "France 🇫🇷")