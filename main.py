# -*- coding: utf-8 -*-
import logging
import uuid
import asyncio
import os
import threading # لاستخدام المسارات المتعددة لتشغيل Flask و Polling معًا
from flask import Flask, request # استيراد Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

OWNER_ID = 1749717270

# --- إعدادات البوت الأساسية ---
API_TOKEN = "7487838353:AAFmFXZ0PzjeFCz3x6rorCMlN_oBBzDyzEQ" # تم وضع التوكن هنا مباشرة

# إعداد التسجيل (Logging)
logging.basicConfig(level=logging.INFO)

# تهيئة البوت والـ Dispatcher
# في aiogram 3.x، يتم تمرير الـ Bot إلى الـ Dispatcher عند الإنشاء
dp = Dispatcher()
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) # استخدام HTML كوضع افتراضي للتنسيق عبر DefaultBotProperties

# --- تخزين الرسائل (في الذاكرة) ---
# لتسهيل التشغيل على Pydroid، سنستخدم قاموس في الذاكرة بدلاً من قاعدة بيانات.
# ملاحظة: ستفقد الرسائل عند إعادة تشغيل البوت.
message_store = {}

# --- Callback Data (aiogram 3.x with Pydantic v2) ---
# لتمييز بيانات الأزرار المضمنة، نستخدم الآن تعريف class
class WhisperCallbackFactory(CallbackData, prefix="whisper"):
    msg_id: str

# --- معالج الأوامر ---
# استخدام مرشحات الأوامر الجديدة في v3
@dp.message(CommandStart())
async def send_welcome_start(message: types.Message):
    """معالج لأمر /start"""
    if message.from_user.id != OWNER_ID:
        logging.info(f"Ignoring /start from non-owner: {message.from_user.id}")
        return # Ignore silently
    await send_welcome(message)

@dp.message(Command("help"))
async def send_welcome_help(message: types.Message):
    """معالج لأمر /help"""
    if message.from_user.id != OWNER_ID:
        logging.info(f"Ignoring /help from non-owner: {message.from_user.id}")
        return # Ignore silently
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
        parse_mode=ParseMode.MARKDOWN # تحديد وضع التنسيق هنا أيضاً
    )

# --- معالج الاستعلامات المضمنة (Inline Mode) ---
# نفس طريقة التعريف تعمل في v3
@dp.inline_query()
async def inline_whisper_handler(inline_query: types.InlineQuery):
    """معالج للاستعلامات المضمنة لإنشاء رسائل الهمس"""
    if inline_query.from_user.id != OWNER_ID:
        logging.info(f"Ignoring inline query from non-owner: {inline_query.from_user.id}")
        # Optionally, provide a result indicating the user is not authorized
        result = InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="غير مصرح لك",
            description="هذا البوت مخصص للمالك فقط.",
            input_message_content=InputTextMessageContent(message_text="عذراً، لا يمكنك استخدام هذا البوت.")
        )
        try:
            await inline_query.answer(results=[result], cache_time=60) # Cache for a minute
        except Exception as e:
            logging.error(f"Error sending unauthorized message to non-owner {inline_query.from_user.id}: {e}")
        return # Stop processing for non-owner
    try:
        query_text = inline_query.query.strip()
        sender_id = str(inline_query.from_user.id)
        sender_username = inline_query.from_user.username.lower() if inline_query.from_user.username else None

        # تحليل النص المدخل
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

        # التحقق من طول الرسائل
        if len(secret_message) >= 200 or len(query_text) >= 255:
            result = InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="خطأ: الرسالة طويلة جدًا",
                description=f"السرية: {len(secret_message)}/199, الإجمالي: {len(query_text)}/254",
                input_message_content=InputTextMessageContent(message_text="الرسالة طويلة جدًا. يرجى مراجعة /help")
            )
            await inline_query.answer(results=[result], cache_time=1)
            return

        # تنظيف قائمة المستخدمين المستهدفين
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

        # --- Generate mentions ---
        target_mentions = []
        for user in target_users:
            if user.isdigit():
                # It's likely a user ID
                target_mentions.append(f'<a href="tg://user?id={user}">المستخدم {user}</a>')
            else:
                # Assume it's a username
                target_mentions.append(f'@{user}') # Add @ back
        mentions_str = ', '.join(target_mentions)
        # --- End Generate mentions ---

        # إنشاء معرف فريد للرسالة وتخزينها
        msg_id = str(uuid.uuid4())
        message_store[msg_id] = {
            "sender_id": sender_id,
            "sender_username": sender_username,
            "target_users": target_users, # قائمة بأسماء المستخدمين والمعرفات (صغيرة)
            "secret_message": secret_message,
            "public_message": public_message
        }
        logging.info(f"Stored message {msg_id}: {message_store[msg_id]}")

        # إنشاء الزر المضمن (استخدام builder أسلوب أحدث لكن الطريقة القديمة لا تزال تعمل)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="اظهار الهمسة العامة", callback_data=WhisperCallbackFactory(msg_id=msg_id).pack())]
        ])

        # إنشاء نتيجة الاستعلام المضمن
        result = InlineQueryResultArticle(
            id=msg_id,
            title="رسالة همس جاهزة للإرسال",
            description=f"موجهة إلى: {', '.join(target_users)}",
            input_message_content=InputTextMessageContent(
                message_text=f"همسة عامة لهذا {mentions_str}\n\nاضغط على الزر أدناه لقراءتها.",
                # parse_mode=ParseMode.HTML # تم تعيينه كوضع افتراضي للبوت
            ),
            reply_markup=keyboard
        )

        await inline_query.answer(results=[result], cache_time=1)

    except Exception as e:
        logging.error(f"Error in inline handler: {e}", exc_info=True)

# --- معالج ردود الأزرار المضمنة (Callback Query) ---
# استخدام مرشح F السحري لـ callback_data في v3
@dp.callback_query(WhisperCallbackFactory.filter())
async def handle_whisper_callback(call: types.CallbackQuery, callback_data: CallbackData):
    """معالج لردود الأزرار المضمنة لعرض الرسالة المناسبة"""
    try:
        # الوصول إلى البيانات من callback_data يكون كـ object attributes في v3
        msg_id = callback_data.msg_id
        clicker_id = str(call.from_user.id)
        clicker_username = call.from_user.username.lower() if call.from_user.username else None

        logging.info(f"Callback received for msg_id: {msg_id} from user: {clicker_id} (@{clicker_username})")

        # استرداد الرسالة من المخزن
        message_data = message_store.get(msg_id)

        if not message_data:
            await call.answer("عذراً، هذه الرسالة لم تعد متوفرة أو انتهت صلاحيتها.", show_alert=True)
            logging.warning(f"Message ID {msg_id} not found in store.")
            return

        # التحقق من صلاحية المستخدم
        is_authorized = False
        if clicker_id == message_data["sender_id"]:
            is_authorized = True
        else:
            for target in message_data["target_users"]:
                if target == clicker_id or (clicker_username and target == clicker_username):
                    is_authorized = True
                    break

        logging.info(f"User {clicker_id} authorization status for msg {msg_id}: {is_authorized}")

        # عرض الرسالة المناسبة
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

# --- نقطة تشغيل البوت (aiogram v3) ---
async def start_aiogram_polling():
    """الدالة التي ستقوم بتشغيل Polling لـ aiogram."""
    logging.info("بدء تشغيل البوت (aiogram v3) في مسار منفصل...")
    await dp.start_polling(bot)

# --- إعداد تطبيق Flask ---
app = Flask(__name__)

@app.route('/')
def home():
    """نقطة نهاية بسيطة لتجنب خمول خدمة الويب على Render."""
    return "Telegram Bot is running and polling!", 200

if __name__ == '__main__':
    # تشغيل Polling لـ aiogram في مسار منفصل
    # يجب استخدام asyncio.run داخل المسار لأنه يتعامل مع الأحداث غير المتزامنة
    polling_thread = threading.Thread(target=lambda: asyncio.run(start_aiogram_polling()))
    polling_thread.daemon = True # سيتم إنهاء المسار عند إنهاء التطبيق الرئيسي
    polling_thread.start()

    # تشغيل تطبيق Flask
    # Render تحدد المنفذ عبر متغير البيئة PORT
    port = int(os.environ.get("PORT", 5000)) # استخدام 5000 كمنفذ افتراضي إذا لم يتم تعيين PORT
    logging.info(f"بدء تشغيل خادم Flask على المنفذ {port}...")
    app.run(host='0.0.0.0', port=port)


