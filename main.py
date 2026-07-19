try:
    # اگر python-dotenv نصب باشد، متغیرهای فایل .env را قبل از import شدن
    # config.py در os.environ می‌ریزد. کاملاً اختیاری است: اگر نصب نباشد یا
    # فایل .env نباشد (مثلاً چون متغیرها از طریق systemd EnvironmentFile
    # ست شده‌اند)، بی‌سروصدا رد می‌شود و رفتار قبلی حفظ می‌شود.
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)
from config import BOT_TOKEN
from db import init_db
from handlers import (
    WAITING_FOR_RECEIPT,
    WAITING_FOR_TOPUP_AMOUNT,
    button_handler,
    debug_get_chat_id,
    receipt_handler,
    start,
    start_receipt_conversation,
    start_topup_conversation,
    topup_amount_handler,
    precheckout_handler,
    successful_payment_handler,
    admin_add_config,
    admin_delete_config,
    admin_list_keys,
    admin_list_configs,
    admin_help,
    admin_panel,
    admin_cancel,
    admin_xui_debug,
)
import logging


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.ERROR,
)
logger = logging.getLogger(__name__)


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    receipt_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_receipt_conversation, pattern="^send_receipt_step$")
        ],
        states={
            WAITING_FOR_RECEIPT: [
                MessageHandler(filters.ALL & ~filters.COMMAND, receipt_handler),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    topup_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_topup_conversation, pattern="^add_balance$")
        ],
        states={
            WAITING_FOR_TOPUP_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount_handler),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("adminpanel", admin_panel))
    app.add_handler(CommandHandler("addconfig", admin_add_config))
    app.add_handler(CommandHandler("delconfig", admin_delete_config))
    app.add_handler(CommandHandler("listkeys", admin_list_keys))
    app.add_handler(CommandHandler("listconfigs", admin_list_configs))
    app.add_handler(CommandHandler("adminhelp", admin_help))
    app.add_handler(CommandHandler("helpadmin", admin_help))
    app.add_handler(CommandHandler("cancel", admin_cancel))
    app.add_handler(CommandHandler("xuidebug", admin_xui_debug))
    app.add_handler(receipt_conv_handler)
    app.add_handler(topup_conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, debug_get_chat_id))

    print("BOT STARTED WITH DATABASE...")
    app.run_polling()


if __name__ == "__main__":
    main()