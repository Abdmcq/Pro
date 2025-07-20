# -*- coding: utf-8 -*-
import logging
import uuid
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiohttp import web
import os # للوصول إلى متغيرات البيئة

# --- إعدادات البوت الأساسية ---
# يفضل الحصول على التوكن من متغيرات البيئة في الإنتاج لأمان أفضل.
# إذا لم يتم العثور عليه في متغيرات البيئة، سيتم استخدام القيمة المباشرة (للاستخدام الشخصي كما طلبت).
API_TOKEN = os.getenv("API_TOKEN", "7487838353:AAFmFXZ0PzjeFCz3x6rorCMlN_oBBzDyzEQ")
OWNER_ID = 1749717270 # معرف المالك

# إعدادات Webhook
# سيتم الحصول على WEBHOOK_HOST من متغيرات البيئة في Render.
# تأكد من إضافة متغير بيئة باسم WEBHOOK_HOST في إعدادات Render لتطبيقك.
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')
if not WEBHOOK_HOST:
    logging.error("WEBHOOK_HOST environment variable is not set. Webhook will not function correctly.")
    # يمكنك وضع قيمة افتراضية هنا للاختبار المحلي إذا أردت، لكنها غير مستحبة للإنتاج
    # WEBHOOK_HOST = "http://localhost:8080"

WEBHOOK_PATH = f"/webhook/{API_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# إعداد التسجيل (Logging)
logging.basicConfig(level=logging.INFO)

# تهيئة البوت والـ Dispatcher
dp = Dispatcher()
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# --- تخزين الرسائل (في الذاكرة) ---
# ملاحظة: ستفقد الرسائل عند إعادة تشغيل البوت. هذا ليس مثاليًا للإنتاج.
message_store = {}

# --- Callback Data (aiogram 3.x with Pydantic v2) ---
class WhisperCallbackFactory(CallbackData, prefix="whisper"):
    msg_id: str

# --- معالج الأوامر ---
@dp.message(CommandStart())
async def send_welcome_start(message: types.Message):
    """معالج لأمر /start"""
    if message.from_user.id != OWNER_ID:
        logging.info(f"Ignoring /start from non-owner: {message.from_user.id}")
        return
    await send_welcome(message)

@dp.message(Command("help"))
async def send_welcome_help(message: types.Message):
    """معالج لأمر /help"""
    if message.from_user.id != OWNER_ID:
        logging.info(f"Ignoring /help from non-owner: {message.from_user.id}")
        return
    await send_welcome(message)

async def send_welcome(message: types.Message):
    """الدالة المشتركة لعرض رسالة الترحيب والمساعدة"""
    await message.reply(
        "أهلاً بك في بوت الهمس!\n\n"
        "لإرسال رسالة سرية في مجموعة، اذكرني في شريط الرسائل بالصيغة التالية:\n"
        "`@اسم_البوت username1,username2 || الرسالة السرية || الرسالة العامة`\n\n"
        "- استبدل `username1,username2` بأسماء المستخدمين أو معرفاتهم (IDs) مفصولة بفواصل.\n"
        "- `الرسالة السرية` هي النص الذي سيظهر فقط للمستخدمين المحددين.\n"
        "- `الرسالة العامة` هي النص الذي سيظهر لبقية أعضاء المجموعة عند محاولة قراءة الرسالة.\n"
        "- يجب أن يكون طول الرسالة السرية أقل من 200 حرف، والطول الإجمالي أقل من 255 حرفًا.\n"
        "\nملاحظة: لا تحتاج لإضافة البوت إلى المجموعة لاستخدامه.",
        parse_mode=ParseMode.MARKDOWN
    )

# --- معالج الاستعلامات المضمنة (Inline Mode) ---
@dp.inline_query()
async def inline_whisper_handler(inline_query: types.InlineQuery):
    """معالج للاستعلامات المضمنة لإنشاء رسائل الهمس"""
    if inline_query.from_user.id != OWNER_ID:
        logging.info(f"Ignoring inline query from non-owner: {inline_query.from_user.id}")
        result = InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="غير مصرح لك",
            description="هذا البوت مخصص للمالك فقط.",
            input_message_content=InputTextMessageContent(message_text="عذراً، لا يمكنك استخدام هذا البوت.")
        )
        try:
            await inline_query.answer(results=[result], cache_time=60)
        except Exception as e:
            logging.error(f"Error sending unauthorized message to non-owner {inline_query.from_user.id}: {e}")
        return
    try:
        query_text = inline_query.query.strip()
        sender_id = str(inline_query.from_user.id)
        sender_username = inline_query.from_user.username.lower() if inline_query.from_user.username else None

        parts = query_text.split("||")
        if len(parts) != 3:
            result = InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="خطأ في التنسيق",
                description="يرجى استخدام: مستخدمين || رسالة سرية || رسالة عامة",
                input_message_content=InputTextMessageContent(message_text="تنسيق خاطئ. يرجى مراجعة /help")
            )
            await inline_query.answer(results=[result], cache_time=1)
            return

        target_users_str = parts[0].strip()
        secret_message = parts[1].strip()
        public_message = parts[2].strip()

        if len(secret_message) >= 200 or len(query_text) >= 255:
            result = InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="خطأ: الرسالة طويلة جدًا",
                description=f"السرية: {len(secret_message)}/199, الإجمالي: {len(query_text)}/254",
                input_message_content=InputTextMessageContent(message_text="الرسالة طويلة جدًا. يرجى مراجعة /help")
            )
            await inline_query.answer(results=[result], cache_time=1)
            return

        target_users = [user.strip().lower().lstrip("@") for user in target_users_str.split(",") if user.strip()]
        if not target_users:
             result = InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="خطأ: لم يتم تحديد مستخدمين",
                description="يجب تحديد مستخدم واحد على الأقل.",
                input_message_content=InputTextMessageContent(message_text="لم يتم تحديد مستخدمين. يرجى مراجعة /help")
            )
             await inline_query.answer(results=[result], cache_time=1)
             return

        target_mentions = []
        for user in target_users:
            if user.isdigit():
                target_mentions.append(f'<a href="tg://user?id={user}">المستخدم {user}</a>')
            else:
                target_mentions.append(f'@{user}')
        mentions_str = ', '.join(target_mentions)

        msg_id = str(uuid.uuid4())
        message_store[msg_id] = {
            "sender_id": sender_id,
            "sender_username": sender_username,
            "target_users": target_users,
            "secret_message": secret_message,
            "public_message": public_message
        }
        logging.info(f"Stored message {msg_id}: {message_store[msg_id]}")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="اظهار الهمسة العامة", callback_data=WhisperCallbackFactory(msg_id=msg_id).pack())]
        ])

        result = InlineQueryResultArticle(
            id=msg_id,
            title="رسالة همس جاهزة للإرسال",
            description=f"موجهة إلى: {', '.join(target_users)}",
            input_message_content=InputTextMessageContent(
                message_text=f"همسة عامة لهذا {mentions_str}\n\nاضغط على الزر أدناه لقراءتها.",
            ),
            reply_markup=keyboard
        )

        await inline_query.answer(results=[result], cache_time=1)

    except Exception as e:
        logging.error(f"Error in inline handler: {e}", exc_info=True)

# --- معالج ردود الأزرار المضمنة (Callback Query) ---
@dp.callback_query(WhisperCallbackFactory.filter())
async def handle_whisper_callback(call: types.CallbackQuery, callback_data: CallbackData):
    """معالج لردود الأزرار المضمنة لعرض الرسالة المناسبة"""
    try:
        msg_id = callback_data.msg_id
        clicker_id = str(call.from_user.id)
        clicker_username = call.from_user.username.lower() if call.from_user.username else None

        logging.info(f"Callback received for msg_id: {msg_id} from user: {clicker_id} (@{clicker_username})")

        message_data = message_store.get(msg_id)

        if not message_data:
            await call.answer("عذراً، هذه الرسالة لم تعد متوفرة أو انتهت صلاحيتها.", show_alert=True)
            logging.warning(f"Message ID {msg_id} not found in store.")
            return

        is_authorized = False
        if clicker_id == message_data["sender_id"]:
            is_authorized = True
        else:
            for target in message_data["target_users"]:
                if target == clicker_id or (clicker_username and target == clicker_username):
                    is_authorized = True
                    break

        logging.info(f"User {clicker_id} authorization status for msg {msg_id}: {is_authorized}")

        if is_authorized:
            message_to_show = message_data["secret_message"]
            message_to_show += f"\n\n(ملاحظة بقية الطلاب يشوفون هاي الرسالة مايشوفون الرسالة الفوگ: '{message_data['public_message']}')"
            if len(message_to_show) > 200:
                 message_to_show = message_data["secret_message"][:150] + "... (الرسالة أطول من اللازم للعرض الكامل هنا)"
            await call.answer(message_to_show, show_alert=True)
            logging.info(f"Showing secret message for {msg_id} to user {clicker_id}")
        else:
            await call.answer(message_data["public_message"], show_alert=True)
            logging.info(f"Showing public message for {msg_id} to user {clicker_id}")

    except Exception as e:
        logging.error(f"Error in callback handler: {e}", exc_info=True)
        await call.answer("حدث خطأ ما أثناء معالجة طلبك.", show_alert=True)

# --- نقطة تشغيل البوت (aiogram v3) باستخدام Webhook ---
async def on_startup(dispatcher: Dispatcher, bot: Bot):
    """دالة يتم تشغيلها عند بدء تشغيل التطبيق."""
    if not WEBHOOK_HOST:
        logging.error("WEBHOOK_HOST is not set. Skipping webhook setup.")
        return

    logging.info("جارٍ حذف Webhook القديم (إذا وجد)...")
    await bot.delete_webhook()

    logging.info(f"جارٍ إعداد Webhook على: {WEBHOOK_URL}")
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("تم إعداد Webhook بنجاح.")

async def on_shutdown(dispatcher: Dispatcher, bot: Bot):
    """دالة يتم تشغيلها عند إيقاف تشغيل التطبيق."""
    logging.info("جارٍ حذف Webhook عند إيقاف التشغيل...")
    await bot.delete_webhook()
    logging.info("تم حذف Webhook.")

async def main():
    # تهيئة تطبيق aiohttp
    app = web.Application()
    # ربط مسار الويب هوك بمعالج التحديثات من aiogram
    app.router.add_post(WEBHOOK_PATH, dp.web_hook_handler)

    # تسجيل دوال بدء وإيقاف التشغيل
    app.on_startup.append(lambda app: on_startup(dp, bot))
    app.on_shutdown.append(lambda app: on_shutdown(dp, bot))

    # الحصول على المنفذ من متغيرات البيئة (Render يحدد المنفذ)
    port = int(os.getenv("PORT", 8080))
    logging.info(f"بدء تشغيل خادم الويب على المنفذ: {port}")

    # بدء خادم الويب
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=port)
    await site.start()

    # ابقِ التطبيق يعمل إلى الأبد
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("تم إيقاف البوت يدوياً.")
    finally:
        logging.info("تم إيقاف البوت.")

