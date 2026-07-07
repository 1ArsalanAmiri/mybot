from html import escape

import jdatetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest, TelegramError

from config import ADMIN_ID, CHANNEL_ID, TRANSACTION_LOG_CHANNEL_ID
from db import (
    get_user_balance, get_or_create_user, has_used_test_account,
    get_available_config, get_user_orders,
    mark_test_account_used, assign_config_to_order,
    create_order,add_config, count_available_configs, get_stock_summary,
)
from utils import (
    build_admin_order_text,
    build_order_text,
    build_service_delivered_text,
    delete_message_safe,
    format_rial_from_toman,
    get_safe_username,
    send_new_message,
    format_toman,
    generate_qr_code,
)
import os
from keyboads import get_main_menu_keyboard, get_wallet_keyboard, get_support_keyboard, get_products_keyboard, \
    DURATION_CODE_TO_DAYS, get_duration_menu_keyboard, get_payment_method_keyboard, PRODUCTS

WAITING_FOR_RECEIPT = 1
users_seen_join = set()
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


async def check_user_membership(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except BadRequest:
        return False
    except TelegramError as e:
        print(f"Membership check error: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if CHANNEL_ID and not await check_user_membership(user.id, context.bot):
        await update.message.reply_text(
            "برای استفاده از ربات، ابتدا در کانال ما عضو شوید:\n"
            f"[کانال ما](https://t.me/{CHANNEL_ID.replace('@', '')})",
            parse_mode="Markdown"
        )
        return

    get_user_balance(user.id)

    first_name = escape(user.first_name or "داداش")

    welcome_text = (
        f"به به آقا <b>{first_name}</b> داداشم! 😃\n\n"
        "به ربات خودت خوشومدی عشق.💘\n"
        "با منوی زیر می‌تونی هرچی دلت خواست رو با بالاترین کیفیت و بهترین قیمت واسه خودت دست و پا کنی.\n\n"
        "🔸 واسه شروع، یکی از گزینه‌های زیرو خیلی یواش لمس کن:"
    )

    await update.message.reply_text(
        text=welcome_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# دستورات مخصوص ادمین: اضافه کردن لینک کانفیگ/ساب به انبار
# ---------------------------------------------------------------------------

async def admin_add_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    استفاده:
      /addconfig <product_key> <link>
      /addconfig test_config <link>

    مثال:
      /addconfig buy_1m_10gb https://main.projectv2.blog:2086/sub/xxxx
    """
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return  # فقط ادمین اصلی

    args = context.args
    if len(args) < 2:
        valid_keys = ", ".join(list(PRODUCTS.keys())[:5]) + " , ... , test_config"
        await update.message.reply_text(
            "❌ فرمت درست:\n"
            "<code>/addconfig product_key link</code>\n\n"
            "مثال:\n"
            "<code>/addconfig buy_1m_10gb https://example.com/sub/xxxx</code>\n\n"
            f"برای دیدن لیست کامل کلیدها از /listkeys استفاده کن.\nنمونه چند کلید: {escape(valid_keys)}",
            parse_mode="HTML",
        )
        return

    product_key = args[0].strip()
    link = " ".join(args[1:]).strip()

    if product_key != "test_config" and product_key not in PRODUCTS:
        await update.message.reply_text(
            "⚠️ این product_key معتبر نیست.\n"
            "برای دیدن لیست کلیدهای معتبر از دستور /listkeys استفاده کن."
        )
        return

    config_id = add_config(product_key, link)
    remaining = count_available_configs(product_key)

    await update.message.reply_text(
        f"✅ لینک با شناسه <code>{config_id}</code> برای محصول <code>{escape(product_key)}</code> ذخیره شد.\n"
        f"📦 موجودی فعلی این محصول: {remaining} عدد",
        parse_mode="HTML",
    )


async def admin_list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست کلیدهای معتبر محصولات + موجودی فعلی هرکدام، فقط برای ادمین."""
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return

    stock = {row["product_key"]: row["count"] for row in get_stock_summary()}

    lines = ["📋 <b>لیست کلیدهای محصولات و موجودی:</b>\n"]
    lines.append(f"• <code>test_config</code> → موجودی: {stock.get('test_config', 0)}")
    for key, product in PRODUCTS.items():
        count = stock.get(key, 0)
        lines.append(
            f"• <code>{key}</code> ({product['size']} / {product['duration']} روزه) → موجودی: {count}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return None
    await query.answer()

    user = query.from_user
    user_id = user.id
    data = query.data
    full_name = " ".join(filter(None, [user.first_name, user.last_name])).strip() or "کاربر"
    db_user = get_or_create_user(user_id, user.username, full_name)

    # ------------------ بخش تأیید و رد فاکتور توسط ادمین ------------------
    if data.startswith("approve_order_"):
        parts = data.split("_")
        if len(parts) < 4:
            await query.answer("خطای داخلی: شناسه سفارش نامعتبر است.", show_alert=True)
            return None

        product_key = parts[2]
        customer_id = int(parts[3])
        order_id = None
        if len(parts) == 5:
            order_id = int(parts[4])

        config_data = get_available_config(product_key)

        if not config_data:
            await query.answer("❌ موجودی این محصول در دیتابیس تمام شده است! از /addconfig برای اضافه کردن لینک استفاده کن.", show_alert=True)
            return None

        config_link = config_data['link']
        config_id = config_data['id']

        if order_id:
            assign_config_to_order(order_id, config_id)

        product = PRODUCTS.get(product_key, {})
        size = product.get("size", "نامشخص")
        duration_days = product.get("duration", "نامشخص")

        success_text = build_service_delivered_text(
            user_id=customer_id,
            config_id=config_id,
            size=size,
            duration_days=duration_days,
            link=config_link,
        )

        try:
            await context.bot.send_message(
                chat_id=customer_id,
                text=success_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📚 آموزش اتصال", callback_data="tutorial")],
                    [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
                ]),
            )
            await query.edit_message_caption(caption="✅ این فاکتور تأیید شد و لینک اشتراک برای کاربر ارسال گردید.")
        except Exception as e:
            print(f"Error sending config to customer {customer_id}: {e}")
            await query.answer("❌ خطا در ارسال پیام به کاربر. ممکن است ربات را بلاک کرده باشد.", show_alert=True)

        return None

    elif data.startswith("reject_order_"):
        parts = data.split("_")
        if len(parts) < 3:
            await query.answer("خطای داخلی: شناسه کاربر نامعتبر است.", show_alert=True)
            return None
        customer_id = int(parts[2])

        try:
            await context.bot.send_message(
                chat_id=customer_id,
                text="❌ رسید شما توسط مدیریت تأیید نشد. در صورت بروز مشکل با پشتیبانی در ارتباط باشید."
            )
            await query.edit_message_caption(caption="❌ این فاکتور رد شد و به کاربر اطلاع داده شد.")
        except TelegramError as e:
            print(f"Error notifying user {customer_id} about rejected order: {e}")
            await query.answer("❌ مشکلی در پردازش درخواست رد رخ داد.", show_alert=True)

        return None

    # ------------------ بخش اکانت تست ------------------
    elif data == "test_account":
        if has_used_test_account(user_id):
            await query.answer("شما قبلاً از سرویس تست استفاده کرده‌اید ❌", show_alert=True)
            return None

        test_config = get_available_config("test_config")
        if not test_config:
            await delete_message_safe(query)
            await send_new_message(
                update, context,
                text="در حال حاضر سرویس تستمون به اتمام رسیده، لطفاً در ساعات بعد تلاش کنید. ⏱",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]])
            )
            return None

        mark_test_account_used(user_id)

        text = (
            "✅ سرویس تست با موفقیت ایجاد شد\n\n"
            f"👤 نام کاربری سرویس : {user_id}_test\n"
            "🌿 نام سرویس: تست\n"
            "🇺🇳 لوکیشن: projectv\n"
            "⏳ مدت زمان: 100 ساعت\n"
            "🗜 حجم سرویس: 256 مگابایت\n\n"
            "لینک اتصال:\n"
            f"<code>{test_config['link']}</code>\n\n"
            "🧑‍🦯 شما میتوانید شیوه اتصال را با فشردن دکمه زیر دریافت کنید."
        )
        await delete_message_safe(query)
        await send_new_message(update, context, text=text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("آموزش اتصال", callback_data="tutorial")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]
        ]))
        return None

    # ------------------ بخش سرویس‌های من ------------------
    elif data == "my_services":
        orders = get_user_orders(user_id)
        text = "🛍 <b>اشتراک های خریداری شده توسط شما</b>\n\n⚠️ برای مشاهده اطلاعات و مدیریت روی نام کاربری کلیک کنید."

        buttons = []
        if orders:
            for order in orders:
                buttons.append([InlineKeyboardButton(f"سرویس {order['product_key']} - {order['date']}",
                                                     callback_data=f"show_service_{order['id']}")])
        else:
            buttons.append([InlineKeyboardButton("هنوز سفارشی ثبت نکرده‌اید 🙁", callback_data="#")])

        buttons.append([InlineKeyboardButton("🔙 بازگشت به صفحه اصلی", callback_data="main_menu")])

        await delete_message_safe(query)
        await send_new_message(update, context, text=text, reply_markup=InlineKeyboardMarkup(buttons))
        return None

    # ------------------ بخش حساب کاربری ------------------
    elif data == "wallet_profile":
        orders_count = len(get_user_orders(user_id))
        now = jdatetime.datetime.now().strftime("%Y/%m/%d → ⏰ %H:%M:%S")

        text = (
            "🗂 <b>اطلاعات حساب کاربری شما :</b>\n\n"
            f"🪪 شناسه کاربری: <code>{user_id}</code>\n"
            f"👤 نام: {escape(full_name)}\n"
            f"👥 کد معرف شما : <code>{db_user['referral_code']}</code>\n"
            f"📱 شماره تماس : {db_user.get('phone', 'ثبت نشده')}\n"
            f"⌚️زمان ثبت نام : {db_user['join_date']}\n"
            f"💰 موجودی: {format_toman(db_user['balance'])} تومان\n"
            f"🛒 تعداد سرویس های خریداری شده : {orders_count} عدد\n"
            f"📑 تعداد فاکتور های پرداخت شده : {orders_count} عدد\n"
            f"🤝 تعداد زیر مجموعه های شما : 0 نفر\n"
            "🔖 گروه کاربری : عادی\n\n"
            f"📆 {now}"
        )
        await delete_message_safe(query)
        await send_new_message(update, context, text=text, reply_markup=get_wallet_keyboard())
        return None

    # ------------------ بخش پشتیبانی و سوالات ------------------
    elif data == "support":
        text = "☎️ در دکمه زیر ( سوالات متداول ) سوالات پرتکرار شما آمده است. روی دکمه زیر کلیک کنید در صورت نیافتن سوال خود روی دکمه پشتیبانی کلیک کنید"
        await delete_message_safe(query)
        await send_new_message(update, context, text=text, reply_markup=get_support_keyboard())
        return None

    elif data == "faq":
        faq_text = (
            "💡 <b>سوالات متداول</b> ⁉️\n\n"
            "1️⃣ فیلترشکن شما آیپی ثابته؟ میتونم برای صرافی های ارز دیجیتال استفاده کنم؟\n"
            "✅ به دلیل وضعیت نت و محدودیت های کشور سرویس ما مناسب ترید نیست و فقط لوکیشن‌ ثابته.\n\n"
            "2️⃣ آیا امکان استفاده همزمان از چند دستگاه وجود دارد؟\n"
            "✅ خیر، هر اشتراک مخصوص یک دستگاه است.\n\n"
            "3️⃣ اگر مشکلی در اتصال داشتم چه کار کنم؟\n"
            "✅ ابتدا آموزش اتصال را مطالعه کنید. اگر مشکل حل نشد، به پشتیبانی پیام دهید.\n\n"
            "💡 در صورتی که جواب سوالتون رو نگرفتید میتونید به «پشتیبانی» مراجعه کنید."
        )
        await delete_message_safe(query)
        await send_new_message(update, context, text=faq_text, reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]]))
        return None

    # -------------- مدیریت دکمه خرید کانفیگ --------------
    elif data == "buy_config":
        await delete_message_safe(query)
        await send_new_message(
            update, context,
            text="⏳ لطفاً مدت زمان اشتراک مورد نظرتون رو انتخاب کنید:",
            reply_markup=get_duration_menu_keyboard()
        )
        return None

    # -------------- مدیریت دکمه انتخاب مدت زمان --------------
    elif data in DURATION_CODE_TO_DAYS:
        duration_days = DURATION_CODE_TO_DAYS[data]
        await delete_message_safe(query)
        await send_new_message(
            update, context,
            text="🛒 لطفاً یکی از طرح‌های زیر را انتخاب کنید:",
            reply_markup=get_products_keyboard(duration_days)
        )
        return None

    # -------------- مدیریت انتخاب یک پلن مشخص (مثلاً buy_1m_10gb) --------------
    # 👈 این بخش قبلاً وجود نداشت و دلیل اصلی کار نکردن دکمه‌ها بود
    elif data in PRODUCTS:
        product = PRODUCTS[data]
        size = product["size"]
        price = int(product["price"])
        duration_days = product["duration"]

        order_id = create_order(user_id, data, price)

        context.user_data["pending_order"] = {
            "product_key": data,
            "service_title": f"{size} / {duration_days} روزه",
            "duration_days": duration_days,
            "size": size,
            "price_toman": price,
            "order_id": order_id,
        }

        username_text = get_safe_username(user)
        order_text = build_order_text(
            username_text,
            f"{size} / {duration_days} روزه",
            duration_days,
            size,
            price,
        )

        await delete_message_safe(query)
        await send_new_message(
            update, context,
            text=order_text + "\n\n💳 لطفاً روش پرداخت رو انتخاب کن:",
            reply_markup=get_payment_method_keyboard(),
        )
        return None

    # -------------- مدیریت دکمه بازگشت به منوی اصلی --------------
    elif data == "main_menu":
        await delete_message_safe(query)
        await send_new_message(
            update, context,
            text="🔸 واسه شروع، یکی از گزینه‌های زیرو خیلی یواش لمس کن:",
            reply_markup=get_main_menu_keyboard()
        )
        return None

    # -------------- مدیریت دکمه های پرداخت (مثلا pay_card) --------------
    elif data == "pay_card":
        order_data = context.user_data.get("pending_order")
        if not order_data:
            await query.answer("خطا: سفارش فعالی یافت نشد. لطفاً مجدداً خرید را شروع کنید.")
            return None

        price_toman_int = order_data.get('price_toman')
        if price_toman_int is None:
            await query.answer("خطا: قیمت سفارش نامعتبر است.")
            return None

        formatted_rial = format_rial_from_toman(price_toman_int)
        formatted_toman = format_toman(price_toman_int)

        card_block = (
            "برای افزایش موجودی، مبلغ را به کارت زیر واریز کنید:\n\n"
            "<code>6219 8619 0176 8530</code>\n"
            "<b>بانک سامان - امیری اشکذری</b>\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

        text = (
            f"اگه میخای فوری تایید شه باید دقیقاً مبلغ <b>{formatted_rial}</b> ریال رو واریز کنی.\n"
            "در غیر این صورت باید وایسی خودم آنلاین شم و دستی تاییدت کنم! "
            "(معمولا آنلاینم) ⚠️\n\n"
            f"{card_block}\n\n"
            f"💰 معادل تومانی این مبلغ: <b>{formatted_toman}</b> تومان\n\n"
            "🔝 لزومی برای ارسال رسید نیست اگر پرداخت خودکار انجام بشه.\n"
            "ولی اگه بیشتر از 5 دقیقه گذشت و درخواستت تایید نشد، عکس رسیدتو ارسال کن."
        )

        await delete_message_safe(query)
        await send_new_message(
            update, context,
            text=text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 ارسال رسید", callback_data="send_receipt_step"),
                InlineKeyboardButton("🔙 بازگشت", callback_data="buy_config")
            ]])
        )
        return None

    return None


async def start_receipt_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    await query.answer()
    await delete_message_safe(query)

    await send_new_message(
        update,
        context,
        text="🖼 اسکرین‌شات رسید کارت به کارتتو ارسال کن عشق.\nدرضمن: رسید فیک بفرستی میفهمم😉",
    )
    return WAITING_FOR_RECEIPT


async def debug_get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return
    print(f"Chat ID: {chat.id} | Type: {chat.type} | Title: {chat.title}")


def _is_image_document(doc) -> bool:
    if not doc:
        return False

    mt = (doc.mime_type or "").lower().strip()
    if mt.startswith("image/"):
        return True

    filename = (doc.file_name or "").lower().strip()
    _, ext = os.path.splitext(filename)
    return ext in ALLOWED_IMAGE_EXTS


async def receipt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not message:
        return WAITING_FOR_RECEIPT

    file_id = None
    file_kind = None

    if message.photo:
        file_id = message.photo[-1].file_id
        file_kind = "photo"
    elif message.document and _is_image_document(message.document):
        file_id = message.document.file_id
        file_kind = "document-image"
    else:
        await message.reply_text(
            "دادا رسید باید «عکس» باشه.\n\n"
            "اگر داری فایل می‌فرستی، حتماً فایل باید یکی از این‌ها باشه: JPG / PNG / WEBP\n"
            "یا به صورت Photo ارسالش کن (نه PDF)."
        )
        return WAITING_FOR_RECEIPT

    order = context.user_data.get("pending_order", {})
    if not order:
        await message.reply_text("سفارش پیدا نشد. لطفاً دوباره از اول خرید را انجام بده.")
        return ConversationHandler.END

    username_text = get_safe_username(user)
    user_full_name = " ".join(filter(None, [user.first_name, user.last_name])).strip() or "نامشخص"

    user_details_text = (
        "👤 <b>مشخصات کاربر</b>\n\n"
        f"• نام: <b>{escape(user_full_name)}</b>\n"
        f"• یوزرنیم: {username_text}\n"
        f"• آیدی: <code>{user.id}</code>\n"
        f"• Chat ID: <code>{update.effective_chat.id if update.effective_chat else 'نامشخص'}</code>\n"
    )

    order_details_text = (
        "🛍 <b>مشخصات خرید</b>\n\n"
        f"• سرویس: <b>{escape(str(order.get('service_title', 'نامشخص')))}</b>\n"
        f"• مدت: <b>{escape(str(order.get('duration_days', 'نامشخص')))} روز</b>\n"
        f"• حجم: <b>{escape(str(order.get('size', 'نامشخص')))}</b>\n"
        f"• مبلغ: <b>{format_toman(order.get('price_toman', 'نامشخص'))} تومان</b>\n"
        f"• کد محصول: <code>{escape(str(order.get('product_key', 'نامشخص')))}</code>\n"
    )

    await message.reply_text("✅ رسید دریافت شد و برای بررسی ارسال شد.")

    admin_text = (
        "🚨 <b>رسید پرداخت جدید</b>\n\n"
        f"{user_details_text}\n"
        f"{order_details_text}\n"
        f"📎 <b>نوع ارسال:</b> <code>{file_kind}</code>\n\n"
        "برای تایید این رسید و شارژ حساب کاربر اقدام کنید."
    )

    product_key = escape(order.get('product_key', 'محصول'))
    admin_caption = f"رسید جدید پرداخت از کاربر {user.id} ({user_full_name})\nمحصول: {product_key}"

    order_id_for_admin = order.get('order_id')
    if not order_id_for_admin:
        print("Warning: order_id not found in pending_order. Cannot create approve button with order_id.")
        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأیید و ارسال کانفیگ",
                                  callback_data=f"approve_order_{product_key}_{user.id}")],
            [InlineKeyboardButton("❌ رد فاکتور", callback_data=f"reject_order_{user.id}")]
        ])
    else:
        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأیید و ارسال کانفیگ",
                                  callback_data=f"approve_order_{product_key}_{user.id}_{order_id_for_admin}")],
            [InlineKeyboardButton("❌ رد فاکتور", callback_data=f"reject_order_{user.id}")]
        ])

    try:
        if file_kind == "document-image":
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=file_id,
                caption=admin_caption,
                reply_markup=admin_keyboard,
                parse_mode="HTML",
            )
        else:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=admin_caption,
                reply_markup=admin_keyboard,
                parse_mode="HTML",
            )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            parse_mode="HTML",
        )
    except TelegramError as e:
        print(f"Error sending receipt to admin ({ADMIN_ID}): {e}")
        await message.reply_text("مشکلی در ارسال رسید به ادمین پیش اومد. لطفاً بعداً دوباره امتحان کنید.")

    if TRANSACTION_LOG_CHANNEL_ID:
        try:
            log_channel_id_int = int(TRANSACTION_LOG_CHANNEL_ID)
            log_caption = "🚨 کپی رسید پرداختی"
            if file_kind == "document-image":
                await context.bot.send_document(
                    chat_id=log_channel_id_int,
                    document=file_id,
                    caption=log_caption,
                    parse_mode="HTML",
                )
            else:
                await context.bot.send_photo(
                    chat_id=log_channel_id_int,
                    photo=file_id,
                    caption=log_caption,
                    parse_mode="HTML",
                )

            await context.bot.send_message(
                chat_id=log_channel_id_int,
                text=admin_text,
                parse_mode="HTML",
            )
        except (ValueError, TypeError):
            print("Warning: TRANSACTION_LOG_CHANNEL_ID is invalid or not set. Skipping log channel.")
        except TelegramError as e:
            print(f"Error sending receipt to log channel ({TRANSACTION_LOG_CHANNEL_ID}): {e}")
        except Exception as e:
            print(f"An unexpected error occurred while sending to log channel: {e}")

    return ConversationHandler.END