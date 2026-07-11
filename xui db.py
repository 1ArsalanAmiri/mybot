"""
xui_db.py
---------
ماژول فقط-خواندنی برای گرفتن اطلاعات لحظه‌ای کلاینت‌ها مستقیماً از دیتابیس x-ui
(sqlite در مسیر /etc/x-ui/x-ui.db یا هر مسیری که با XUI_DB_PATH ست شده).

چرا این‌طوری؟
    - ربات و پنل x-ui روی یک سرور هستند، پس نیازی به HTTP/scraping صفحه‌ی
      subscription نیست؛ می‌شود مستقیم از دیتابیس panel خواند. این هم پایدارتره
      و هم سریع‌تر.

نکات مهم درباره‌ی ساختار x-ui:
    - کلاینت‌ها به‌صورت یک آرایه‌ی JSON داخل ستون `settings` جدول `inbounds`
      ذخیره می‌شوند (نه یک جدول جداگانه به اسم client). هر آیتم چیزی شبیه این
      است:
          {
            "id": "<uuid>",           # یا "password" برای trojan/shadowsocks
            "email": "...",
            "enable": true,
            "totalGB": 0,             # بایت؛ 0 یعنی نامحدود
            "expiryTime": 0,          # میلی‌ثانیه epoch؛ 0 یعنی بدون انقضا
            "subId": "rtxu6ex39kqesbru",
            "limitIp": 0,
            "tgId": "",
            "flow": ""
          }
    - نسخه‌های جدیدتر x-ui (و فورک 3x-ui) یک جدول کمکی به اسم
      `client_traffics` هم دارند که up/down/total/enable/expiry_time را
      به‌صورت لحظه‌ای (sync شده با آمار واقعی Xray) نگه می‌دارد. اگر این
      جدول موجود باشد، برای مصرف واقعی به آن اولویت می‌دهیم؛ در غیر این
      صورت از همان مقادیر تعریف‌شده در settings استفاده می‌کنیم.
    - «آخرین زمان اتصال» و «User-Agent کلاینت» در هیچ‌کدام از این جدول‌ها
      ذخیره نمی‌شوند (این‌ها فقط از طریق gRPC API لحظه‌ای Xray یا access.log
      قابل استخراجند، نه از دیتابیس). به همین خاطر این ماژول برای این دو
      مقدار None برمی‌گرداند و لایه‌ی بالاتر (handlers.py) باید «نامشخص»
      نمایش بدهد. این محدودیت واقعی دیتابیس x-ui است، نه یک باگ.

این ماژول هیچ INSERT/UPDATE/DELETE‌ای روی x-ui.db انجام نمی‌دهد؛ اتصال هم
همیشه با mode=ro (فقط خواندن) باز می‌شود تا هیچ‌وقت دیتابیس پنل دستکاری نشود.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

logger = logging.getLogger("xui_db")

try:
    from config import XUI_DB_PATH
except ImportError:
    XUI_DB_PATH = os.getenv("XUI_DB_PATH", "/etc/x-ui/x-ui.db")


# ---------------------------------------------------------------------------
# اتصال فقط-خواندنی
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    """
    یک اتصال فقط-خواندنی (mode=ro) به دیتابیس x-ui باز می‌کند.
    عمداً از URI استفاده می‌شود تا حتی در صورت باگ در کد این ماژول، امکان
    نوشتن روی دیتابیس پنل وجود نداشته باشد.
    """
    if not os.path.exists(XUI_DB_PATH):
        raise FileNotFoundError(f"x-ui database not found at: {XUI_DB_PATH}")

    uri = f"file:{XUI_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    )
    return cur.fetchone() is not None


def list_tables() -> List[str]:
    """برای دیباگ/بررسی نسخه‌ی نصب‌شده: لیست همه‌ی جدول‌های دیتابیس x-ui را برمی‌گرداند."""
    try:
        with _connect() as conn:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
            return [row["name"] for row in cur.fetchall()]
    except Exception as e:
        logger.error("xui_db.list_tables failed: %s", e, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# استخراج کلاینت‌ها از settings جدول inbounds
# ---------------------------------------------------------------------------

def _iter_inbound_clients(conn: sqlite3.Connection):
    """
    روی همه‌ی رکوردهای جدول inbounds حلقه می‌زند، ستون settings (JSON) را
    پارس می‌کند و برای هر کلاینت، یک دیکشنری نرمال‌شده yield می‌کند.
    """
    try:
        cur = conn.execute("SELECT id, remark, protocol, enable, settings FROM inbounds")
    except sqlite3.OperationalError as e:
        logger.error("xui_db: cannot read 'inbounds' table (schema mismatch?): %s", e)
        return

    for row in cur.fetchall():
        raw_settings = row["settings"]
        if not raw_settings:
            continue
        try:
            settings = json.loads(raw_settings)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(
                "xui_db: failed to parse settings JSON for inbound %s: %s", row["id"], e
            )
            continue

        clients = settings.get("clients") or []
        if not isinstance(clients, list):
            continue

        for client in clients:
            if not isinstance(client, dict):
                continue
            yield {
                "inbound_id": row["id"],
                "inbound_remark": row["remark"],
                "inbound_protocol": row["protocol"],
                "inbound_enable": bool(row["enable"]) if row["enable"] is not None else True,
                "email": client.get("email"),
                "uuid": client.get("id") or client.get("password") or client.get("uuid"),
                "sub_id": client.get("subId") or client.get("subID") or client.get("sub_id"),
                "enable": bool(client.get("enable", True)),
                "total": int(client.get("totalGB") or 0),
                "expiry_time": int(client.get("expiryTime") or 0),
                "limit_ip": int(client.get("limitIp") or 0),
                "tg_id": client.get("tgId") or None,
                "flow": client.get("flow") or None,
                # این دو فقط از settings قابل استخراج نیستند مگر client_traffics موجود باشد
                "up": 0,
                "down": 0,
            }


def _find_client(conn: sqlite3.Connection, *, email: Optional[str] = None,
                  sub_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not email and not sub_id:
        return None

    matches = []
    for client in _iter_inbound_clients(conn):
        if email and client.get("email") == email:
            matches.append(client)
        elif sub_id and client.get("sub_id") == sub_id:
            matches.append(client)

    if not matches:
        return None

    if len(matches) > 1:
        logger.warning(
            "xui_db: multiple clients matched (email=%s, sub_id=%s) — using the first one. "
            "این یعنی چند کلاینت با ایمیل/subId یکسان در پنل وجود دارد.",
            email, sub_id,
        )

    return matches[0]


def _get_traffic_row(conn: sqlite3.Connection, email: str) -> Optional[Dict[str, Any]]:
    """اگر جدول client_traffics موجود باشد، مصرف لحظه‌ای کلاینت را از آن می‌خواند."""
    if not _table_exists(conn, "client_traffics"):
        return None
    try:
        cur = conn.execute(
            "SELECT enable, up, down, total, expiry_time FROM client_traffics WHERE email = ? LIMIT 1",
            (email,),
        )
    except sqlite3.OperationalError as e:
        logger.error("xui_db: cannot read 'client_traffics' table (schema mismatch?): %s", e)
        return None

    row = cur.fetchone()
    if not row:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# API عمومی (فقط SELECT)
# ---------------------------------------------------------------------------

def find_email_by_subid(sub_id: str) -> Optional[str]:
    """
    ایمیل کلاینتی که subId اش با subId موجود در لینک subscription ما یکی است
    را برمی‌گرداند. لینک‌های ما به شکل .../sub/<subId> هستند، پس این تابع
    پل ارتباطی بین «لینکی که کاربر دارد» و «کلاینت واقعی در x-ui» است.
    """
    if not sub_id:
        return None
    try:
        with _connect() as conn:
            client = _find_client(conn, sub_id=sub_id)
            return client.get("email") if client else None
    except Exception as e:
        logger.error("xui_db.find_email_by_subid(%s) failed: %s", sub_id, e, exc_info=True)
        return None


def get_client_info(email: str) -> Optional[Dict[str, Any]]:
    """
    اطلاعات کامل یک کلاینت را بر اساس ایمیل برمی‌گرداند (ترکیب settings +
    client_traffics در صورت وجود). فقط SELECT انجام می‌شود.
    خروجی None یعنی کلاینتی با این ایمیل در x-ui پیدا نشد.
    """
    if not email:
        return None
    try:
        with _connect() as conn:
            client = _find_client(conn, email=email)
            if not client:
                logger.warning("xui_db.get_client_info: no client found for email=%s", email)
                return None

            traffic = _get_traffic_row(conn, email)
            if traffic:
                # client_traffics منبع لحظه‌ای و معتبرتر برای مصرف/انقضا/فعال‌بودن است
                client["up"] = traffic.get("up") or 0
                client["down"] = traffic.get("down") or 0
                if traffic.get("total") is not None:
                    client["total"] = traffic.get("total") or 0
                if traffic.get("expiry_time") is not None:
                    client["expiry_time"] = traffic.get("expiry_time") or 0
                if traffic.get("enable") is not None:
                    client["enable"] = bool(traffic.get("enable"))

            # این فیلدها اصلاً در دیتابیس x-ui ذخیره نمی‌شوند (نیاز به gRPC API
            # زنده‌ی Xray یا پارس access.log دارند)؛ صادقانه None برمی‌گردانیم.
            client["last_online"] = None
            client["connected_client"] = None

            return client
    except FileNotFoundError as e:
        logger.error("xui_db.get_client_info: %s", e)
        return None
    except Exception as e:
        logger.error("xui_db.get_client_info(%s) failed: %s", email, e, exc_info=True)
        return None


def get_client_usage(email: str) -> Optional[Dict[str, Any]]:
    """
    فقط بخش مصرف/حجم را برمی‌گرداند:
        {"up": int, "down": int, "usage": int, "total": int, "remaining": Optional[int]}
    total == 0 یعنی نامحدود (remaining هم None خواهد بود).
    """
    info = get_client_info(email)
    if not info:
        return None

    up = int(info.get("up") or 0)
    down = int(info.get("down") or 0)
    usage = up + down
    total = int(info.get("total") or 0)
    remaining = (total - usage) if total > 0 else None
    if remaining is not None and remaining < 0:
        remaining = 0

    return {"up": up, "down": down, "usage": usage, "total": total, "remaining": remaining}


def get_client_status(email: str) -> Optional[bool]:
    """
    وضعیت فعال/غیرفعال کلاینت را طبق قانون زیر برمی‌گرداند:
        فعال است اگر:
            enable == True
            و expiry نگذشته باشد (یا اصلاً expiry نداشته باشد)
            و (حجم نامحدود باشد یا) حجم باقی‌مانده صفر نباشد
        در غیر این صورت: غیرفعال.
    اگر کلاینت پیدا نشود: None.
    """
    info = get_client_info(email)
    if not info:
        return None
    return is_active(info)


def is_active(info: Dict[str, Any]) -> bool:
    """
    طبق قانون خواسته‌شده تشخیص می‌دهد که آیا یک کلاینت فعال است یا نه:
        فعال = enable و (بدون انقضا یا انقضا نگذشته) و (نامحدود یا حجم باقی‌مانده > 0)
    ورودی همان دیکشنری خروجی get_client_info است.
    """
    if not info.get("enable", True):
        return False

    expiry_time = int(info.get("expiry_time") or 0)
    if expiry_time > 0:
        now_ms = int(time.time() * 1000)
        if now_ms >= expiry_time:
            return False

    total = int(info.get("total") or 0)
    if total > 0:
        used = int(info.get("up") or 0) + int(info.get("down") or 0)
        if used >= total:
            return False

    return True


# ---------------------------------------------------------------------------
# توابع کمکی فرمت‌بندی
# ---------------------------------------------------------------------------

def extract_subid_from_link(link: Optional[str]) -> Optional[str]:
    """از لینک subscription (.../sub/<subId>) مقدار subId را استخراج می‌کند."""
    if not link:
        return None
    try:
        path = urlsplit(link).path
    except ValueError:
        return None
    segment = path.rstrip("/").rsplit("/", 1)[-1].strip()
    return segment or None


def format_bytes(n: Optional[int]) -> str:
    """بایت را به یک رشته‌ی خوانا مثل '15.09MB' یا '1.00GB' تبدیل می‌کند."""
    if n is None:
        return "نامشخص"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "نامشخص"
    if n <= 0:
        return "0B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    while n >= 1024 and idx < len(units) - 1:
        n /= 1024.0
        idx += 1
    return f"{n:.2f}{units[idx]}"


def format_expiry(expiry_ms: Optional[int]) -> str:
    """میلی‌ثانیه epoch را به تاریخ خوانا تبدیل می‌کند. 0/None یعنی بدون انقضا."""
    if not expiry_ms:
        return "بدون انقضا ♾"
    try:
        ts = int(expiry_ms) / 1000
        return time.strftime("%m/%d/%Y, %H:%M:%S", time.localtime(ts))
    except (TypeError, ValueError, OSError):
        return "نامشخص"