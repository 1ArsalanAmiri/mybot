from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from config import BOT_TOKEN
from db import init_db
from handlers import (
    WAITING_FOR_RECEIPT,
    button_handler,
    debug_get_chat_id,
    receipt_handler,
    start,
    start_receipt_conversation,
    admin_add_config,
    admin_delete_config,
    admin_list_keys,
    admin_list_configs,
    admin_help,
)
import logging


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.ERROR
)
logger = logging.getLogger(__name__)


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    receipt_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_receipt_conversation, pattern="^send_receipt_step")
        ],
        states={
            WAITING_FOR_RECEIPT: [
                MessageHandler(filters.ALL & ~filters.COMMAND, receipt_handler),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addconfig", admin_add_config))
    app.add_handler(CommandHandler("delconfig", admin_delete_config))
    app.add_handler(CommandHandler("listkeys", admin_list_keys))
    app.add_handler(CommandHandler("listconfigs", admin_list_configs))
    app.add_handler(CommandHandler("adminhelp", admin_help))
    app.add_handler(receipt_conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, debug_get_chat_id))

    print("BOT STARTED WITH DATABASE...")
    app.run_polling()


if __name__ == "__main__":
    main()