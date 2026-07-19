import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# لود کردن فایل .env از مسیری که فایل main.py در آن قرار دارد
# این دستور به صورت صریح می‌گوید: "فایل .env را دقیقاً کنار main.py پیدا کن"
dotenv_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=dotenv_path)

# ---------------------------------------------------------------------------
# توکن ربات — قبلاً هاردکد بود؛ حالا فقط از Environment Variable خوانده می‌شود.
# چون این توکن قبلاً به‌صورت متن ساده در یک چت رد و بدل شده، توصیه می‌شود
# همین الان از BotFather ریوک/رجنریت شود، صرف‌نظر از این تغییر.
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN تنظیم نشده است. لطفاً توکن را در فایل .env یا Environment Variable ست کن."
    )

CHANNEL_ID = os.getenv("CHANNEL_ID", "@ArsalanVPN_Channel")

_admin_id_raw = os.getenv("ADMIN_ID")
if not _admin_id_raw:
    raise RuntimeError("ADMIN_ID تنظیم نشده است. لطفاً آیدی عددی ادمین را در .env ست کن.")
ADMIN_ID = int(_admin_id_raw)

_txn_log_raw = os.getenv("TRANSACTION_LOG_CHANNEL_ID")
TRANSACTION_LOG_CHANNEL_ID = int(_txn_log_raw) if _txn_log_raw else None

TOMAN_PER_STAR = int(os.getenv("TOMAN_PER_STAR", "2000"))

DB_PATH = os.getenv("DB_PATH", "bot_database.db")

# مسیر دیتابیس پنل x-ui (فقط خوانده می‌شود، هیچ‌وقت نوشته نمی‌شود — نگاه کن به xui_db.py)
XUI_DB_PATH = os.getenv("XUI_DB_PATH", "/etc/x-ui/x-ui.db")

# ---------------------------------------------------------------------------
# اتصال نوشتاری (REST API) به پنل x-ui — نگاه کن به xui_api.py
# ساخت/حذف/ویرایش کلاینت همیشه از طریق همین API انجام می‌شود، نه با دست‌کاری
# مستقیم دیتابیس (چون Xray کانفیگ را فقط موقع استارت می‌خواند، نوشتن مستقیم
# روی دیتابیس تا ریستارت کامل x-ui اثری نداشت و کاربران فعال را قطع می‌کرد).
#
# ⚠️ امنیتی: این مقادیر قبلاً هاردکد بودند (و حتی یک‌بار در چت رد و بدل
# شدند). حالا هیچ مقدار پیش‌فرضی برای URL/username/password در نظر گرفته
# نشده — اگر در .env ست نشوند، برنامه با خطای واضح بالا می‌آید (به‌جای
# ادامه‌ی کار با مقدار پیش‌فرض ضعیف/فراموش‌شده).
# ---------------------------------------------------------------------------
XUI_PANEL_URL = os.getenv("XUI_PANEL_URL")
XUI_PANEL_USERNAME = os.getenv("XUI_PANEL_USERNAME")
XUI_PANEL_PASSWORD = os.getenv("XUI_PANEL_PASSWORD")
if not all([XUI_PANEL_URL, XUI_PANEL_USERNAME, XUI_PANEL_PASSWORD]):
    raise RuntimeError(
        "تنظیمات اتصال به پنل x-ui کامل نیست. لطفاً XUI_PANEL_URL, "
        "XUI_PANEL_USERNAME, XUI_PANEL_PASSWORD را در .env ست کن."
    )

# تأیید گواهی SSL پنل هنگام تماس با API. پیش‌فرض True (امن). فقط اگر پنل با
# گواهی self-signed/نامعتبر بالا آمده و موقتاً نیاز به دور زدن این بررسی
# داری، صراحتاً XUI_VERIFY_SSL=false را در .env ست کن — هرگز در کد هاردکد
# نکن، چون غیرفعال کردن دائمی SSL verify آسیب‌پذیری MITM ایجاد می‌کند.
XUI_VERIFY_SSL = os.getenv("XUI_VERIFY_SSL", "true").strip().lower() not in ("false", "0", "no")

# ---------------------------------------------------------------------------
# انتخاب Inbound برای هر نقش — عمداً هاردکد نشده. اگر خالی/None بماند، ربات
# به‌صورت داینامیک از روی جدول inbounds تصمیم می‌گیرد (نگاه کن به
# xui_api.resolve_inbound_id). اگر چند inbound دارید و می‌خواهید دستی مشخص
# کنید کدام برای تست و کدام برای هدیه‌ی Referral ساخته شود، شناسه‌ی عددیش را
# اینجا بگذارید (همان id ستون اول جدول inbounds).
# ---------------------------------------------------------------------------
_test_inbound_raw = os.getenv("TEST_ACCOUNT_INBOUND_ID")
TEST_ACCOUNT_INBOUND_ID = int(_test_inbound_raw) if _test_inbound_raw else None

_referral_inbound_raw = os.getenv("REFERRAL_GIFT_INBOUND_ID")
REFERRAL_GIFT_INBOUND_ID = int(_referral_inbound_raw) if _referral_inbound_raw else None

# این مقدار قبلاً هاردکد به 1 بود؛ حالا هم از env قابل override است ولی
# پیش‌فرضش را برای سازگاری با رفتار قبلی روی 1 نگه داشتیم.
XRAY_INBOUND_ID = int(os.getenv("XRAY_INBOUND_ID", "1"))

# نگاشت دستی و اختیاری هر product_key به یک inbound id مشخص. اگر برای یک
# product_key ای اینجا چیزی نبود، همان منطق داینامیک بالا اعمال می‌شود.
# از env به‌صورت رشته‌ی "key:id,key2:id2" قابل تنظیم است تا نیازی به تغییر
# کد نباشد؛ مثال: PRODUCT_INBOUND_MAP="buy_un_1m:4,buy_1m_10gb:1"
_product_inbound_map_raw = os.getenv("PRODUCT_INBOUND_MAP", "")
PRODUCT_INBOUND_MAP = {}
for _pair in _product_inbound_map_raw.split(","):
    _pair = _pair.strip()
    if not _pair or ":" not in _pair:
        continue
    _key, _val = _pair.split(":", 1)
    try:
        PRODUCT_INBOUND_MAP[_key.strip()] = int(_val.strip())
    except ValueError:
        pass

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

# لیبل نمایشی سرور برای بخش مانیتورینگ (بخش ۲)
SERVER_DISPLAY_LABEL = os.getenv("SERVER_DISPLAY_LABEL", "France 🇫🇷")