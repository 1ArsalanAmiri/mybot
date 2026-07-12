import sqlite3
from typing import List, Optional, Tuple

import jdatetime

from config import DB_PATH


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance INTEGER DEFAULT 0,
                referral_code TEXT,
                phone TEXT DEFAULT '❌ ارسال نشده است ❌',
                join_date TEXT,
                test_account_used INTEGER DEFAULT 0
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_key TEXT,
                link TEXT,
                status TEXT DEFAULT 'available'
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_key TEXT,
                price INTEGER,
                status TEXT DEFAULT 'pending',
                assigned_config_id INTEGER,
                order_date TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS user_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                service_type TEXT NOT NULL,
                product_key TEXT,
                config_id INTEGER,
                link TEXT,
                size TEXT,
                duration_days INTEGER,
                start_date TEXT,
                expiry_date TEXT,
                remaining_volume TEXT,
                status TEXT DEFAULT 'active',
                xui_email TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            """
        )

        # مهاجرت برای دیتابیس‌های قدیمی‌تر که ستون xui_email را ندارند
        # (این ستون کش ایمیل کلاینت x-ui است تا لازم نباشه هر بار همه‌ی
        # inbound ها را برای پیدا کردن subId اسکن کنیم)
        if not _column_exists(conn, "user_services", "xui_email"):
            c.execute("ALTER TABLE user_services ADD COLUMN xui_email TEXT")

        # -------------------------------------------------------------
        # مهاجرت‌های جدید (تست خودکار / مانیتورینگ / تیکت / آمار / Referral)
        # فقط افزودن ستون/جدول در صورت نبود؛ هیچ داده‌ی قبلی حذف/تغییر نمی‌شود.
        # -------------------------------------------------------------

        # user_services: نوع ماشین‌خوان سرویس + اطلاعات کلاینت زنده‌ی x-ui
        if not _column_exists(conn, "user_services", "kind"):
            c.execute("ALTER TABLE user_services ADD COLUMN kind TEXT DEFAULT 'paid'")
        if not _column_exists(conn, "user_services", "xui_client_uuid"):
            c.execute("ALTER TABLE user_services ADD COLUMN xui_client_uuid TEXT")
        if not _column_exists(conn, "user_services", "xui_inbound_id"):
            c.execute("ALTER TABLE user_services ADD COLUMN xui_inbound_id INTEGER")
        if not _column_exists(conn, "user_services", "total_bytes"):
            c.execute("ALTER TABLE user_services ADD COLUMN total_bytes INTEGER DEFAULT 0")
        if not _column_exists(conn, "user_services", "expiry_ms"):
            c.execute("ALTER TABLE user_services ADD COLUMN expiry_ms INTEGER DEFAULT 0")
        if not _column_exists(conn, "user_services", "protocol"):
            c.execute("ALTER TABLE user_services ADD COLUMN protocol TEXT")

        # users: سیستم Referral (بخش ۶)
        if not _column_exists(conn, "users", "invited_by"):
            c.execute("ALTER TABLE users ADD COLUMN invited_by INTEGER")
        if not _column_exists(conn, "users", "invite_count"):
            c.execute("ALTER TABLE users ADD COLUMN invite_count INTEGER DEFAULT 0")
        if not _column_exists(conn, "users", "referral_rewards_given"):
            c.execute("ALTER TABLE users ADD COLUMN referral_rewards_given INTEGER DEFAULT 0")

        # orders: نوع سفارش (برای گزارش فروش بخش ۴؛ پیش‌فرض 'purchase' سازگار با داده‌ی قبلی)
        if not _column_exists(conn, "orders", "kind"):
            c.execute("ALTER TABLE orders ADD COLUMN kind TEXT DEFAULT 'purchase'")

        # سیستم تیکت پشتیبانی (بخش ۳)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                message TEXT NOT NULL,
                admin_reply TEXT,
                status TEXT DEFAULT 'open',
                created_at TEXT,
                updated_at TEXT
            )
            """
        )

        # لاگ دعوت‌های موفق Referral — هر invited_id فقط یک‌بار می‌تواند ثبت شود
        # (UNIQUE روی invited_id دقیقاً همان قانون «اگر قبلاً start کرده بود حساب نشود» را تضمین می‌کند)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_id INTEGER NOT NULL,
                invited_id INTEGER NOT NULL UNIQUE,
                created_at TEXT
            )
            """
        )

        # لاگ هدایای اعطاشده (هدیه‌ی رفرال و غیره)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                reward_type TEXT NOT NULL,
                service_id INTEGER,
                created_at TEXT
            )
            """
        )

        # اسنپ‌شات‌های مانیتورینگ سرور (بخش ۲) — فقط برای تاریخچه؛ نمایش زنده مستقیم از psutil است
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS server_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cpu_percent REAL,
                ram_percent REAL,
                disk_percent REAL,
                uptime_seconds INTEGER,
                created_at TEXT
            )
            """
        )

        # لاگ نوتیفیکیشن‌های ادمین (کاربر جدید، هدیه‌ی رفرال، ...) — برای رهگیری/گزارش
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                payload TEXT,
                created_at TEXT
            )
            """
        )

        conn.commit()


def get_or_create_user(
    user_id: int,
    username: Optional[str],
    full_name: str,
    inviter_id: Optional[int] = None,
) -> dict:
    """
    کاربر را برمی‌گرداند (و اگر وجود نداشت می‌سازد).
    خروجی یک دیکشنری از ستون‌های جدول users است که یک کلید اضافه‌ی
    ``_is_new`` هم دارد: True فقط دقیقاً همان باری که این کاربر برای اولین‌بار
    ساخته می‌شود (برای نوتیفیکیشن «کاربر جدید» در بخش ۵ استفاده می‌شود — طبق
    قانون «فقط اولین start، نه هر بار»).

    اگر inviter_id داده شود و کاربر واقعاً برای اولین‌بار ساخته شود (و
    inviter_id با خودِ user_id یکی نباشد، یعنی کسی نمی‌تواند خودش را دعوت
    کند)، ستون invited_by ثبت می‌شود — پایه‌ی سیستم Referral در بخش ۶.
    ثبت شمارش/پاداش دعوت‌کننده در جای دیگری (record_referral) انجام می‌شود.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()

        if row:
            c.execute(
                "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
                (username, full_name, user_id),
            )
            conn.commit()
            c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            updated_row = c.fetchone()
            result = dict(zip([column[0] for column in c.description], updated_row))
            result["_is_new"] = False
            return result

        import uuid

        ref_code = str(uuid.uuid4().hex)[:12]
        now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        valid_inviter = inviter_id if (inviter_id and inviter_id != user_id) else None

        c.execute(
            "INSERT INTO users (user_id, username, full_name, balance, referral_code, join_date, invited_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, full_name, 0, ref_code, now, valid_inviter),
        )
        conn.commit()

        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        new_row = c.fetchone()
        result = dict(zip([column[0] for column in c.description], new_row))
        result["_is_new"] = True
        return result


def get_user_by_referral_code(code: str) -> Optional[dict]:
    if not code:
        return None
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE referral_code = ?", (code.strip(),))
        row = c.fetchone()
        if not row:
            return None
        return dict(zip([column[0] for column in c.description], row))


def get_user_by_id(user_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        if not row:
            return None
        return dict(zip([column[0] for column in c.description], row))


def get_user_balance(user_id: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        res = c.fetchone()
        return res[0] if res else 0


def has_used_test_account(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT test_account_used FROM users WHERE user_id = ?", (user_id,))
        res = c.fetchone()
        return bool(res[0]) if res else False


def mark_test_account_used(user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET test_account_used = 1 WHERE user_id = ?", (user_id,))
        conn.commit()


def get_available_config(product_key: str) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM configs WHERE product_key = ? AND status = 'available' LIMIT 1",
            (product_key,),
        )
        row = c.fetchone()
        if row:
            return {"id": row[0], "product_key": row[1], "link": row[2], "status": row[3]}
        return None


def assign_config_to_order(order_id: int, config_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE configs SET status = 'sold' WHERE id = ?", (config_id,))
        c.execute(
            "UPDATE orders SET status = 'completed', assigned_config_id = ? WHERE id = ?",
            (config_id, order_id),
        )
        conn.commit()


def create_order(user_id: int, product_key: str, price: int) -> int:
    now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO orders (user_id, product_key, price, order_date) VALUES (?, ?, ?, ?)",
            (user_id, product_key, price, now),
        )
        conn.commit()
        return c.lastrowid


def get_user_orders(user_id: int) -> List[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT o.id, o.product_key, o.order_date, c.link
            FROM orders o
            LEFT JOIN configs c ON o.assigned_config_id = c.id
            WHERE o.user_id = ? AND o.status = 'completed'
            ORDER BY o.id DESC
            """,
            (user_id,),
        )
        return [{"id": r[0], "product_key": r[1], "date": r[2], "link": r[3]} for r in c.fetchall()]


# ---------------------------------------------------------------------------
# مدیریت موجودی لینک‌ها
# ---------------------------------------------------------------------------

def add_config(product_key: str, link: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO configs (product_key, link, status) VALUES (?, ?, 'available')",
            (product_key, link),
        )
        conn.commit()
        return c.lastrowid


def add_configs_batch(entries: List[Tuple[str, str]]) -> List[dict]:
    """چند لینک را در یک تراکنش اضافه می‌کند."""
    if not entries:
        return []

    results = []
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        for product_key, link in entries:
            c.execute(
                "INSERT INTO configs (product_key, link, status) VALUES (?, ?, 'available')",
                (product_key, link),
            )
            results.append({"product_key": product_key, "config_id": c.lastrowid})
        conn.commit()
    return results


def count_available_configs(product_key: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM configs WHERE product_key = ? AND status = 'available'",
            (product_key,),
        )
        return c.fetchone()[0]


def get_stock_summary() -> List[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT product_key, COUNT(*) FROM configs WHERE status = 'available' GROUP BY product_key"
        )
        return [{"product_key": r[0], "count": r[1]} for r in c.fetchall()]


def delete_config(config_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM configs WHERE id = ? AND status = 'available'", (config_id,))
        conn.commit()
        return c.rowcount > 0


def delete_configs_by_product(product_key: str) -> int:
    """تمام لینک‌های available یک محصول را حذف می‌کند."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM configs WHERE product_key = ? AND status = 'available'",
            (product_key,),
        )
        conn.commit()
        return c.rowcount


def get_config_by_id(config_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, product_key, link, status FROM configs WHERE id = ?", (config_id,))
        row = c.fetchone()
        if not row:
            return None
        return {"id": row[0], "product_key": row[1], "link": row[2], "status": row[3]}


def get_configs_by_product(product_key: str, limit: int = 30, offset: int = 0) -> List[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, link FROM configs WHERE product_key = ? AND status = 'available' "
            "ORDER BY id ASC LIMIT ? OFFSET ?",
            (product_key, limit, offset),
        )
        return [{"id": r[0], "link": r[1]} for r in c.fetchall()]


# ---------------------------------------------------------------------------
# مدیریت سفارشات
# ---------------------------------------------------------------------------

def get_order_by_id(order_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, user_id, product_key, price, status, assigned_config_id, order_date FROM orders WHERE id = ?",
            (order_id,),
        )
        row = c.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "product_key": row[2],
            "price": row[3],
            "status": row[4],
            "assigned_config_id": row[5],
            "order_date": row[6],
        }


def update_order_status(order_id: int, status: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        conn.commit()


def add_user_balance(user_id: int, amount: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()


def mark_config_sold(config_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE configs SET status = 'sold' WHERE id = ?", (config_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# سرویس‌های فعال کاربران (برای پنل ادمین)
# ---------------------------------------------------------------------------

def create_user_service(
    user_id: int,
    username: Optional[str],
    service_type: str,
    product_key: str,
    config_id: Optional[int],
    link: str,
    size: str,
    duration_days: int,
    kind: Optional[str] = None,
    xui_client_uuid: Optional[str] = None,
    xui_inbound_id: Optional[int] = None,
    xui_email: Optional[str] = None,
    total_bytes: int = 0,
    expiry_ms: int = 0,
    protocol: Optional[str] = None,
) -> int:
    """
    ``config_id`` می‌تواند None باشد (سرویس‌هایی که از استخر لینک‌های دستی
    نیستند، بلکه زنده و خودکار در x-ui ساخته شده‌اند — تست/هدیه‌ی Referral).
    ``kind`` نوع ماشین‌خوان سرویس است (test/paid/gift)؛ اگر داده نشود از
    روی ``service_type`` قدیمی («test»/«paid») استنتاج می‌شود تا فراخوانی‌های
    قبلی (پرداختی) بدون تغییر کار کنند.
    """
    now = jdatetime.datetime.now()
    start_date = now.strftime("%Y/%m/%d %H:%M:%S")
    expiry = now + jdatetime.timedelta(days=duration_days)
    expiry_date = expiry.strftime("%Y/%m/%d %H:%M:%S")

    resolved_kind = kind or ("test" if service_type == "test" else "paid")

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO user_services
            (user_id, username, service_type, product_key, config_id, link, size,
             duration_days, start_date, expiry_date, remaining_volume, status,
             kind, xui_client_uuid, xui_inbound_id, xui_email, total_bytes, expiry_ms, protocol)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                service_type,
                product_key,
                config_id,
                link,
                size,
                duration_days,
                start_date,
                expiry_date,
                size,
                resolved_kind,
                xui_client_uuid,
                xui_inbound_id,
                xui_email,
                total_bytes,
                expiry_ms,
                protocol,
            ),
        )
        conn.commit()
        return c.lastrowid


def get_user_services_list(limit: int = 10, offset: int = 0) -> List[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT s.id, s.user_id, s.username, s.service_type, s.product_key,
                   s.size, s.expiry_date, s.remaining_volume, s.status, s.link, u.full_name
            FROM user_services s
            LEFT JOIN users u ON s.user_id = u.user_id
            WHERE s.status = 'active'
            ORDER BY s.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        columns = [col[0] for col in c.description]
        return [dict(zip(columns, row)) for row in c.fetchall()]


def count_active_user_services() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM user_services WHERE status = 'active'")
        return c.fetchone()[0]


def get_all_user_ids() -> List[int]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        return [row[0] for row in c.fetchall()]


# ---------------------------------------------------------------------------
# سرویس‌های فعال کاربر (برای بخش «سرویس‌های من» در منوی کاربر)
# ---------------------------------------------------------------------------

def get_services_by_user(user_id: int) -> List[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, user_id, username, service_type, product_key, config_id, link,
                   size, duration_days, start_date, expiry_date, remaining_volume, status,
                   xui_email
            FROM user_services
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        )
        columns = [col[0] for col in c.description]
        return [dict(zip(columns, row)) for row in c.fetchall()]


def get_user_service_by_id(service_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, user_id, username, service_type, product_key, config_id, link,
                   size, duration_days, start_date, expiry_date, remaining_volume, status,
                   xui_email
            FROM user_services
            WHERE id = ?
            """,
            (service_id,),
        )
        row = c.fetchone()
        if not row:
            return None
        columns = [col[0] for col in c.description]
        return dict(zip(columns, row))


def set_service_xui_email(service_id: int, email: str) -> None:
    """
    ایمیل کلاینت x-ui را برای یک سرویس کش می‌کند تا دفعات بعد لازم نباشد
    دوباره کل inbound ها برای پیدا کردن subId اسکن شوند.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE user_services SET xui_email = ? WHERE id = ?", (email, service_id))
        conn.commit()


def update_service_status(service_id: int, status: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE user_services SET status = ? WHERE id = ?", (status, service_id))
        conn.commit()


def update_service_expiry(service_id: int, expiry_date: str, expiry_ms: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE user_services SET expiry_date = ?, expiry_ms = ? WHERE id = ?",
            (expiry_date, expiry_ms, service_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# اکانت‌های تست خودکار (بخش ۱) — لیست/شمارش برای پنل ادمین
# ---------------------------------------------------------------------------

def get_test_services_page(limit: int = 8, offset: int = 0) -> List[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT s.id, s.user_id, s.username, s.link, s.start_date, s.expiry_date,
                   s.status, s.xui_email, u.full_name
            FROM user_services s
            LEFT JOIN users u ON s.user_id = u.user_id
            WHERE s.kind = 'test'
            ORDER BY s.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        columns = [col[0] for col in c.description]
        return [dict(zip(columns, row)) for row in c.fetchall()]


def count_test_services() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM user_services WHERE kind = 'test'")
        return c.fetchone()[0]


def count_expired_services() -> int:
    now_str = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM user_services WHERE status = 'active' AND expiry_date < ?",
            (now_str,),
        )
        return c.fetchone()[0]


# ---------------------------------------------------------------------------
# سیستم Referral (بخش ۶)
# ---------------------------------------------------------------------------

def record_referral(inviter_id: int, invited_id: int) -> bool:
    """
    یک دعوت موفق را ثبت می‌کند و شمارنده‌ی دعوت‌کننده را یکی زیاد می‌کند.
    اگر invited_id قبلاً ثبت شده باشد (یعنی این کاربر قبلاً یک‌بار به‌عنوان
    «دعوت‌شده» حساب شده)، False برمی‌گرداند و چیزی تغییر نمی‌کند — این همان
    قانونی است که «اگر کاربر قبلاً ربات را start کرده بود، حساب نشود» را
    تضمین می‌کند.
    """
    now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO referrals (inviter_id, invited_id, created_at) VALUES (?, ?, ?)",
                (inviter_id, invited_id, now),
            )
        except sqlite3.IntegrityError:
            return False
        c.execute("UPDATE users SET invite_count = invite_count + 1 WHERE user_id = ?", (inviter_id,))
        conn.commit()
        return True


def get_invite_count(user_id: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT invite_count FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        return row[0] if row else 0


def get_referral_rewards_given(user_id: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT referral_rewards_given FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        return row[0] if row else 0


def increment_referral_rewards_given(user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET referral_rewards_given = referral_rewards_given + 1 WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()


def add_reward_log(user_id: int, reward_type: str, service_id: Optional[int] = None) -> int:
    now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO rewards (user_id, reward_type, service_id, created_at) VALUES (?, ?, ?, ?)",
            (user_id, reward_type, service_id, now),
        )
        conn.commit()
        return c.lastrowid


def get_referral_stats(limit: int = 10, offset: int = 0) -> List[dict]:
    """لیست کاربرانی که حداقل یک دعوت موفق دارند، برای نمایش در پنل ادمین."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT u.user_id, u.username, u.full_name, u.invite_count, u.referral_rewards_given
            FROM users u
            WHERE u.invite_count > 0
            ORDER BY u.invite_count DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        columns = [col[0] for col in c.description]
        return [dict(zip(columns, row)) for row in c.fetchall()]


def count_users_with_invites() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE invite_count > 0")
        return c.fetchone()[0]


# ---------------------------------------------------------------------------
# سیستم تیکت پشتیبانی (بخش ۳)
# ---------------------------------------------------------------------------

def create_ticket(user_id: int, username: Optional[str], message: str) -> int:
    now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO tickets (user_id, username, message, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'open', ?, ?)",
            (user_id, username, message, now, now),
        )
        conn.commit()
        return c.lastrowid


def get_ticket(ticket_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        row = c.fetchone()
        if not row:
            return None
        columns = [col[0] for col in c.description]
        return dict(zip(columns, row))


def list_tickets(status: Optional[str] = None, limit: int = 8, offset: int = 0) -> List[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if status:
            c.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            c.execute("SELECT * FROM tickets ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        columns = [col[0] for col in c.description]
        return [dict(zip(columns, row)) for row in c.fetchall()]


def count_tickets(status: Optional[str] = None) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if status:
            c.execute("SELECT COUNT(*) FROM tickets WHERE status = ?", (status,))
        else:
            c.execute("SELECT COUNT(*) FROM tickets")
        return c.fetchone()[0]


def set_ticket_reply(ticket_id: int, reply_text: str) -> None:
    now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE tickets SET admin_reply = ?, status = 'answered', updated_at = ? WHERE id = ?",
            (reply_text, now, ticket_id),
        )
        conn.commit()


def close_ticket(ticket_id: int) -> None:
    now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE tickets SET status = 'closed', updated_at = ? WHERE id = ?",
            (now, ticket_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# مانیتورینگ سرور (بخش ۲) — فقط لاگ اسنپ‌شات؛ خواندن لحظه‌ای در handlers/utils
# ---------------------------------------------------------------------------

def log_server_stats(cpu_percent: float, ram_percent: float, disk_percent: float, uptime_seconds: int) -> None:
    now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO server_stats (cpu_percent, ram_percent, disk_percent, uptime_seconds, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cpu_percent, ram_percent, disk_percent, uptime_seconds, now),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# لاگ نوتیفیکیشن‌های ادمین (بخش ۵ و غیره)
# ---------------------------------------------------------------------------

def log_notification(notif_type: str, payload: str = "") -> None:
    now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO notifications (type, payload, created_at) VALUES (?, ?, ?)",
            (notif_type, payload, now),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# آمار فروش حرفه‌ای (بخش ۴)
# ---------------------------------------------------------------------------

def _today_jalali_prefix() -> str:
    return jdatetime.datetime.now().strftime("%Y/%m/%d")


def _this_month_jalali_prefix() -> str:
    return jdatetime.datetime.now().strftime("%Y/%m")


def get_daily_sales_report() -> dict:
    today = _today_jalali_prefix()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        c.execute(
            "SELECT COUNT(*), COALESCE(SUM(price), 0) FROM orders "
            "WHERE status = 'completed' AND product_key != 'topup' AND order_date LIKE ?",
            (f"{today}%",),
        )
        purchase_count, revenue = c.fetchone()

        c.execute("SELECT COUNT(*) FROM users WHERE join_date LIKE ?", (f"{today}%",))
        new_users = c.fetchone()[0]

        c.execute(
            "SELECT COUNT(*) FROM notifications WHERE type = 'test_renew' AND created_at LIKE ?",
            (f"{today}%",),
        )
        renewals = c.fetchone()[0]

        c.execute(
            "SELECT COUNT(*) FROM user_services WHERE kind = 'test' AND start_date LIKE ?",
            (f"{today}%",),
        )
        test_count = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM user_services WHERE status = 'active'")
        active_services = c.fetchone()[0]

        now_str = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        c.execute(
            "SELECT COUNT(*) FROM user_services WHERE status = 'active' AND expiry_date < ?",
            (now_str,),
        )
        expired_services = c.fetchone()[0]

    return {
        "purchase_count": purchase_count,
        "revenue": revenue,
        "new_users": new_users,
        "renewals": renewals,
        "test_count": test_count,
        "active_services": active_services,
        "expired_services": expired_services,
    }


def get_monthly_sales_report() -> dict:
    month_prefix = _this_month_jalali_prefix()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        c.execute(
            "SELECT COALESCE(SUM(price), 0), COUNT(*) FROM orders "
            "WHERE status = 'completed' AND product_key != 'topup' AND order_date LIKE ?",
            (f"{month_prefix}%",),
        )
        revenue, purchase_count = c.fetchone()

        c.execute(
            """
            SELECT product_key, COUNT(*) as cnt, COALESCE(SUM(price), 0) as rev
            FROM orders
            WHERE status = 'completed' AND product_key != 'topup' AND order_date LIKE ?
            GROUP BY product_key
            ORDER BY cnt DESC
            LIMIT 5
            """,
            (f"{month_prefix}%",),
        )
        top_products = [{"product_key": r[0], "count": r[1], "revenue": r[2]} for r in c.fetchall()]

        c.execute(
            """
            SELECT o.user_id, COUNT(*) as cnt, u.username, u.full_name
            FROM orders o
            LEFT JOIN users u ON o.user_id = u.user_id
            WHERE o.status = 'completed' AND o.product_key != 'topup' AND o.order_date LIKE ?
            GROUP BY o.user_id
            ORDER BY cnt DESC
            LIMIT 5
            """,
            (f"{month_prefix}%",),
        )
        top_users = [{"user_id": r[0], "count": r[1], "username": r[2], "full_name": r[3]} for r in c.fetchall()]

    return {
        "revenue": revenue,
        "purchase_count": purchase_count,
        "top_products": top_products,
        "top_users": top_users,
    }