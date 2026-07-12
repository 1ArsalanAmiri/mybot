"""
xui_api.py
----------
تنها ماژولی که اجازه دارد در پنل x-ui چیزی «بسازد/ویرایش/حذف» کند — همیشه از
طریق REST API رسمی پنل، نه با دست‌کاری مستقیم x-ui.db (نگاه کن به توضیح
بالای xui_db.py: چون Xray تنظیمات را فقط موقع استارت سرویس می‌خواند، نوشتن
مستقیم روی دیتابیس تا ریستارت کامل x-ui اثری نداشت و باعث قطعی کاربران فعال
می‌شد. API پنل خودش هم دیتابیس را آپدیت می‌کند و هم Xray را زنده Reload
می‌کند، بدون قطعی).

هیچ Inbound ای اینجا هاردکد نشده — انتخاب Inbound همیشه یا از روی
config.py (نگاشت دستی اختیاری) یا داینامیک از روی خروجی xui_db.list_inbounds()
انجام می‌شود (نگاه کن به resolve_inbound_id).

نکته: چون sandbox توسعه به پنل واقعی شما دسترسی شبکه ندارد، این ماژول اینجا
اجرا/تست زنده نشده؛ حتماً بعد از دیپلوی روی سرور واقعی یک بار با
/testxuiapi (یا از پنل ادمین → اکانت‌های تست → ساخت تست) امتحانش کن.
"""

from __future__ import annotations

import json
import logging
import secrets
import string
import time
import uuid
from typing import Any, Dict, List, Optional

import requests

from config import (
    XUI_PANEL_URL,
    XUI_PANEL_USERNAME,
    XUI_PANEL_PASSWORD,
    TEST_ACCOUNT_INBOUND_ID,
    REFERRAL_GIFT_INBOUND_ID,
    PRODUCT_INBOUND_MAP,
)
import xui_db

logger = logging.getLogger("xui_api")


class XUIAPIError(Exception):
    """هر خطای مربوط به ارتباط با پنل x-ui (لاگین، ساخت/حذف/ویرایش کلاینت، انتخاب inbound)."""


# ---------------------------------------------------------------------------
# جلسه‌ی HTTP و لاگین
# ---------------------------------------------------------------------------

_session: Optional[requests.Session] = None
_session_created_at: float = 0.0
_SESSION_TTL_SECONDS = 20 * 60  # هر ۲۰ دقیقه یک‌بار دوباره لاگین می‌کنیم تا کوکی منقضی نشود


def _base_url() -> str:
    return XUI_PANEL_URL.rstrip("/") + "/"


def _get_session() -> requests.Session:
    global _session, _session_created_at
    now = time.time()
    if _session is not None and (now - _session_created_at) < _SESSION_TTL_SECONDS:
        return _session

    session = requests.Session()
    try:
        resp = session.post(
            _base_url() + "panel/api/login",
            json={
                "username": XUI_PANEL_USERNAME,
                "password": XUI_PANEL_PASSWORD
            },
            timeout=15,
            verify=True,
        )
    except requests.exceptions.SSLError:
        # برخی پنل‌ها با گواهی self-signed اجرا می‌شوند
        resp = session.post(
            _base_url() + "panel/api/login",
            json={
                "username": XUI_PANEL_USERNAME,
                "password": XUI_PANEL_PASSWORD
            },
            timeout=15,
            verify=True,
        )
    except requests.RequestException as e:
        raise XUIAPIError(f"اتصال به پنل x-ui برای لاگین برقرار نشد: {e}") from e

    try:
        data = resp.json()
    except ValueError:
        raise XUIAPIError(f"پاسخ لاگین پنل JSON نبود (status={resp.status_code}). آدرس پنل را بررسی کن.")

    if not data.get("success"):
        raise XUIAPIError(f"لاگین به پنل x-ui ناموفق بود: {data.get('msg', 'نامشخص')}")

    _session = session
    _session_created_at = now
    return session


def _api_post(path: str, json_body: dict) -> dict:
    session = _get_session()
    url = _base_url() + path.lstrip("/")
    try:
        resp = session.post(url, json=json_body, timeout=15)
    except requests.RequestException as e:
        raise XUIAPIError(f"درخواست به پنل x-ui ناموفق بود ({path}): {e}") from e

    if resp.status_code == 401:
        # کوکی منقضی شده؛ یک‌بار دوباره لاگین و تلاش کن
        global _session
        _session = None
        session = _get_session()
        try:
            resp = session.post(url, json=json_body, timeout=15)
        except requests.RequestException as e:
            raise XUIAPIError(f"درخواست به پنل x-ui بعد از لاگین مجدد هم ناموفق بود ({path}): {e}") from e

    try:
        data = resp.json()
    except ValueError:
        raise XUIAPIError(f"پاسخ پنل x-ui برای {path} معتبر (JSON) نبود — status={resp.status_code}")

    if not data.get("success"):
        raise XUIAPIError(f"پنل x-ui درخواست {path} را رد کرد: {data.get('msg', 'نامشخص')}")

    return data


def _api_get(path: str) -> dict:
    session = _get_session()
    url = _base_url() + path.lstrip("/")
    try:
        resp = session.get(url, timeout=15)
    except requests.RequestException as e:
        raise XUIAPIError(f"درخواست GET به پنل x-ui ناموفق بود ({path}): {e}") from e
    try:
        data = resp.json()
    except ValueError:
        raise XUIAPIError(f"پاسخ پنل x-ui برای {path} معتبر (JSON) نبود — status={resp.status_code}")
    if not data.get("success"):
        raise XUIAPIError(f"پنل x-ui درخواست {path} را رد کرد: {data.get('msg', 'نامشخص')}")
    return data


# ---------------------------------------------------------------------------
# انتخاب داینامیک Inbound (بدون هیچ id هاردکد)
# ---------------------------------------------------------------------------

def resolve_inbound_id(purpose: str, product_key: Optional[str] = None) -> int:
    """
    ``purpose``: 'test' یا 'referral_gift' (یا هر برچسب دیگر).
    ترتیب اولویت:
        ۱) نگاشت دستی PRODUCT_INBOUND_MAP[product_key] در config.py
        ۲) TEST_ACCOUNT_INBOUND_ID / REFERRAL_GIFT_INBOUND_ID در config.py
        ۳) اگر فقط یک inbound فعال در پنل بود، همان
        ۴) حدس بر اساس remark (کلیدواژه‌ی نامحدود برای هدیه، کلیدواژه‌ی تست برای تست)
        ۵) در نهایت: اولین inbound فعال (بر اساس id)
    اگر هیچ inbound فعالی پیدا نشود، خطا می‌دهد (چیزی حدس زده نمی‌شود).
    """
    if product_key and product_key in PRODUCT_INBOUND_MAP:
        return int(PRODUCT_INBOUND_MAP[product_key])

    if purpose == "test" and TEST_ACCOUNT_INBOUND_ID:
        return int(TEST_ACCOUNT_INBOUND_ID)
    if purpose == "referral_gift" and REFERRAL_GIFT_INBOUND_ID:
        return int(REFERRAL_GIFT_INBOUND_ID)

    inbounds = xui_db.list_inbounds()
    enabled = [i for i in inbounds if i.get("enable")]
    if not enabled:
        raise XUIAPIError(
            "هیچ Inbound فعالی در x-ui پیدا نشد. یک Inbound در پنل بساز/فعال کن "
            "یا در config.py مقدار TEST_ACCOUNT_INBOUND_ID / REFERRAL_GIFT_INBOUND_ID را دستی ست کن."
        )

    if len(enabled) == 1:
        return enabled[0]["id"]

    keyword_map = {
        "referral_gift": ["نامحدود", "unlimited"],
        "test": ["تست", "test"],
    }
    keywords = keyword_map.get(purpose, [])
    for inbound in enabled:
        remark = (inbound.get("remark") or "").lower()
        if any(kw.lower() in remark for kw in keywords):
            return inbound["id"]

    logger.warning(
        "xui_api.resolve_inbound_id: چند Inbound فعال هست و remark مناسبی پیدا نشد؛ "
        "از اولین Inbound فعال (id=%s) استفاده می‌شود. برای انتخاب دقیق، در config.py "
        "TEST_ACCOUNT_INBOUND_ID / REFERRAL_GIFT_INBOUND_ID / PRODUCT_INBOUND_MAP را ست کن.",
        enabled[0]["id"],
    )
    return enabled[0]["id"]


def _get_inbound_raw(inbound_id: int) -> dict:
    """اطلاعات کامل یک inbound را مستقیم از API پنل می‌گیرد (برای ساخت client مناسب پروتکل)."""
    data = _api_get(f"panel/api/inbounds/get/{inbound_id}")
    return data.get("obj") or {}


# ---------------------------------------------------------------------------
# ساخت آبجکت کلاینت متناسب با پروتکل inbound
# ---------------------------------------------------------------------------

def _random_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _random_sub_id(length: int = 16) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _build_client_object(
    protocol: str,
    email: str,
    telegram_user_id: int,
    total_bytes: int,
    expiry_ms: int,
    stream_security: Optional[str] = None,
) -> Dict[str, Any]:
    sub_id = _random_sub_id()
    client: Dict[str, Any] = {
        "email": email,
        "enable": True,
        "expiryTime": int(expiry_ms),
        "totalGB": int(total_bytes),  # نام فیلد در x-ui همیشه totalGB است ولی واحدش بایت است
        "limitIp": 1,  # طبق سوالات متداول فعلی ربات: هر اشتراک فقط برای یک دستگاه
        "subId": sub_id,
        "tgId": str(telegram_user_id),
    }

    protocol = (protocol or "").lower()
    if protocol in ("vless",):
        client["id"] = str(uuid.uuid4())
        client["flow"] = "xtls-rprx-vision" if stream_security == "reality" else ""
    elif protocol in ("vmess",):
        client["id"] = str(uuid.uuid4())
    elif protocol in ("trojan",):
        client["password"] = _random_password()
    elif protocol in ("shadowsocks", "ss"):
        client["password"] = _random_password()
        client["method"] = ""  # از تنظیمات پیش‌فرض inbound استفاده می‌شود
    else:
        # پروتکل ناشناخته: هم id هم password را می‌گذاریم تا اکثر پروتکل‌ها پوشش داده شوند
        client["id"] = str(uuid.uuid4())
        client["password"] = _random_password()

    return client, sub_id


def _inbound_stream_security(inbound_raw: dict) -> Optional[str]:
    try:
        stream = json.loads(inbound_raw.get("streamSettings") or "{}")
        return stream.get("security")
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# API عمومی: ساخت / تمدید / حذف کلاینت
# ---------------------------------------------------------------------------

def create_client(
    purpose: str,
    telegram_user_id: int,
    days: float,
    volume_gb: float,
    email_prefix: str,
    product_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    یک کلاینت واقعی و زنده در x-ui می‌سازد (از طریق API، بدون قطعی سرویس) و
    اطلاعات لازم برای ذخیره در دیتابیس ربات و ساخت لینک subscription را
    برمی‌گرداند:
        {
          "inbound_id": int, "protocol": str, "email": str, "uuid_or_password": str,
          "sub_id": str, "link": str, "expiry_ms": int, "total_bytes": int,
        }
    ``days`` می‌تواند اعشاری باشد (مثلاً 1 روز = 24 ساعت؛ برای تست ساعتی از
    days = hours/24 استفاده کن). ``volume_gb`` صفر یعنی نامحدود.
    """
    inbound_id = resolve_inbound_id(purpose, product_key=product_key)
    inbound_raw = _get_inbound_raw(inbound_id)
    protocol = inbound_raw.get("protocol", "vless")
    security = _inbound_stream_security(inbound_raw)

    email = f"{email_prefix}-{secrets.token_hex(3)}"
    expiry_ms = int((time.time() + days * 86400) * 1000) if days else 0
    total_bytes = int(volume_gb * 1024 ** 3) if volume_gb else 0

    client_obj, sub_id = _build_client_object(
        protocol, email, telegram_user_id, total_bytes, expiry_ms, stream_security=security
    )

    _api_post(
        "panel/api/inbounds/addClient",
        {"id": inbound_id, "settings": json.dumps({"clients": [client_obj]})},
    )

    link = xui_db.build_subscription_link(sub_id)
    if not link:
        # اگر panel سرویس subscription نداشت/غیرفعال بود، حداقل خطای واضح بده
        # تا لایه‌ی بالاتر بتواند به ادمین اطلاع دهد (کلاینت ساخته شده ولی لینک نداریم)
        logger.error(
            "xui_api.create_client: کلاینت با email=%s ساخته شد ولی لینک subscription قابل ساخت نبود "
            "(سرویس subscription در پنل x-ui فعال/تنظیم نشده).",
            email,
        )

    return {
        "inbound_id": inbound_id,
        "protocol": protocol,
        "email": email,
        "uuid_or_password": client_obj.get("id") or client_obj.get("password"),
        "sub_id": sub_id,
        "link": link,
        "expiry_ms": expiry_ms,
        "total_bytes": total_bytes,
    }


def _find_client_in_inbound(inbound_raw: dict, email: str) -> Optional[dict]:
    try:
        settings = json.loads(inbound_raw.get("settings") or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    for client in settings.get("clients") or []:
        if isinstance(client, dict) and client.get("email") == email:
            return client
    return None


def delete_client(inbound_id: int, email: str) -> None:
    """کلاینت را با ایمیل از inbound مشخص‌شده حذف می‌کند."""
    inbound_raw = _get_inbound_raw(inbound_id)
    client = _find_client_in_inbound(inbound_raw, email)
    if not client:
        raise XUIAPIError(f"کلاینتی با ایمیل {email} در inbound {inbound_id} پیدا نشد (شاید قبلاً حذف شده).")

    client_id = client.get("id") or client.get("password") or email
    _api_post(f"panel/api/inbounds/{inbound_id}/delClient/{client_id}", {})


def extend_client(inbound_id: int, email: str, extra_days: float) -> int:
    """
    انقضای کلاینت را ``extra_days`` روز جلو می‌برد (یا اگر بدون انقضا/منقضی
    بود، از همین لحظه شروع می‌کند) و enable را دوباره True می‌کند.
    مقدار جدید expiryTime (میلی‌ثانیه) را برمی‌گرداند.
    """
    inbound_raw = _get_inbound_raw(inbound_id)
    settings = json.loads(inbound_raw.get("settings") or "{}")
    clients = settings.get("clients") or []

    target = None
    for client in clients:
        if isinstance(client, dict) and client.get("email") == email:
            target = client
            break
    if not target:
        raise XUIAPIError(f"کلاینتی با ایمیل {email} در inbound {inbound_id} پیدا نشد.")

    now_ms = int(time.time() * 1000)
    current_expiry = int(target.get("expiryTime") or 0)
    base = current_expiry if current_expiry > now_ms else now_ms
    new_expiry = base + int(extra_days * 86400 * 1000)

    target["enable"] = True
    target["expiryTime"] = new_expiry

    client_id = target.get("id") or target.get("password") or email
    _api_post(
        f"panel/api/inbounds/updateClient/{client_id}",
        {"id": inbound_id, "settings": json.dumps({"clients": [target]})},
    )
    return new_expiry