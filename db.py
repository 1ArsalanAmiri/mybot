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

        conn.commit()


def get_or_create_user(user_id: int, username: Optional[str], full_name: str) -> dict:
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
            return dict(zip([column[0] for column in c.description], updated_row))

        import uuid

        ref_code = str(uuid.uuid4().hex)[:12]
        now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        c.execute(
            "INSERT INTO users (user_id, username, full_name, balance, referral_code, join_date) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, full_name, 0, ref_code, now),
        )
        conn.commit()

        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        new_row = c.fetchone()
        return dict(zip([column[0] for column in c.description], new_row))


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
    config_id: int,
    link: str,
    size: str,
    duration_days: int,
) -> int:
    now = jdatetime.datetime.now()
    start_date = now.strftime("%Y/%m/%d %H:%M:%S")
    expiry = now + jdatetime.timedelta(days=duration_days)
    expiry_date = expiry.strftime("%Y/%m/%d %H:%M:%S")

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO user_services
            (user_id, username, service_type, product_key, config_id, link, size,
             duration_days, start_date, expiry_date, remaining_volume, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
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