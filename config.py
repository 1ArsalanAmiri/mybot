import os

BOT_TOKEN = "8773239091:AAETY7lxUm1JmydlkW2J8k2cu5gYjG2-S4M"
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN تنظیم نشده است. لطفاً توکن را به صورت Environment Variable ست کن."
    )

CHANNEL_ID = os.getenv("CHANNEL_ID", "@Trapxan")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5737414011"))
TRANSACTION_LOG_CHANNEL_ID = int(os.getenv("TRANSACTION_LOG_CHANNEL_ID", "-1004491596177"))
TOMAN_PER_STAR = int(os.getenv("TOMAN_PER_STAR", "2000"))

DB_PATH = os.getenv("DB_PATH", "bot_database.db")