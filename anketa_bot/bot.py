"""
Бот-анкета на aiogram 3.x.

Что он делает:
  1. По команде /start начинает опрос.
  2. Задаёт 5 вопросов ПО ОЧЕРЕДИ (имя, город, возраст, язык, "о себе").
  3. Запоминает ответы с помощью FSM (машины состояний).
  4. В конце показывает человеку итог и (если задан ADMIN_ID)
     присылает собранную анкету администратору.

FSM (Finite State Machine) — это и есть "пошаговый диалог":
бот помнит, на каком шаге находится пользователь, и ждёт ответ
именно на текущий вопрос.
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

# --- Настройки ------------------------------------------------------------

# Токен бота берём из переменной окружения BOT_TOKEN (так его не видно в коде).
# Получить токен: напиши @BotFather в Telegram -> /newbot.
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ID твоего личного чата, куда бот пришлёт готовую анкету.
# Узнать свой ID можно у бота @userinfobot. Если не задан — бот просто
# покажет анкету самому пользователю и никуда не отправит.
ADMIN_ID = os.getenv("ADMIN_ID")
ADMIN_ID = int(ADMIN_ID) if ADMIN_ID else None

logging.basicConfig(level=logging.INFO)
router = Router()


# --- Состояния (шаги анкеты) ---------------------------------------------

# Каждый State — это один шаг. Бот последовательно переходит
# от одного к следующему.
class Form(StatesGroup):
    name = State()      # шаг 1: ждём имя
    city = State()      # шаг 2: ждём город
    age = State()       # шаг 3: ждём возраст
    language = State()  # шаг 4: ждём язык программирования
    about = State()     # шаг 5: ждём "о себе"


# --- Шаг 0: старт ---------------------------------------------------------

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    # На всякий случай сбрасываем прошлый незаконченный опрос.
    await state.clear()
    await message.answer(
        "Привет! Давай заполним небольшую анкету 📝\n\n"
        "Как тебя зовут?"
    )
    # Ставим бота в состояние "жду имя".
    await state.set_state(Form.name)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    # Позволяем пользователю прервать анкету в любой момент.
    await state.clear()
    await message.answer("Анкета отменена. Чтобы начать заново — /start")


# --- Шаг 1: получили имя -> спрашиваем город ------------------------------

@router.message(Form.name)
async def step_name(message: Message, state: FSMContext):
    # Сохраняем ответ в "память" FSM под ключом "name".
    await state.update_data(name=message.text)
    await message.answer("Из какого ты города?")
    await state.set_state(Form.city)


# --- Шаг 2: получили город -> спрашиваем возраст --------------------------

@router.message(Form.city)
async def step_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text)
    await message.answer("Сколько тебе лет?")
    await state.set_state(Form.age)


# --- Шаг 3: возраст (с простой проверкой) -> спрашиваем язык --------------

@router.message(Form.age)
async def step_age(message: Message, state: FSMContext):
    # Пример валидации: возраст должен быть числом.
    if not message.text.isdigit():
        await message.answer("Введи возраст числом, пожалуйста 🙂")
        return  # остаёмся на этом же шаге, вопрос повторять не нужно
    await state.update_data(age=message.text)
    await message.answer("Твой любимый язык программирования?")
    await state.set_state(Form.language)


# --- Шаг 4: язык -> спрашиваем "о себе" -----------------------------------

@router.message(Form.language)
async def step_language(message: Message, state: FSMContext):
    await state.update_data(language=message.text)
    await message.answer("Коротко расскажи о себе:")
    await state.set_state(Form.about)


# --- Шаг 5: "о себе" -> завершаем анкету ----------------------------------

@router.message(Form.about)
async def step_about(message: Message, state: FSMContext):
    await state.update_data(about=message.text)

    # Забираем все накопленные ответы.
    data = await state.get_data()

    # Собираем красивый текст анкеты.
    summary = (
        "✅ Анкета заполнена!\n\n"
        f"👤 Имя: {data['name']}\n"
        f"🏙 Город: {data['city']}\n"
        f"🎂 Возраст: {data['age']}\n"
        f"💻 Язык: {data['language']}\n"
        f"📄 О себе: {data['about']}"
    )

    # Показываем итог самому пользователю.
    await message.answer(summary)

    # Если задан ADMIN_ID — отправляем копию анкеты администратору.
    # Пользователь сам осознанно заполнил и отправил эту форму.
    if ADMIN_ID:
        user = message.from_user
        await message.bot.send_message(
            ADMIN_ID,
            f"📬 Новая анкета от @{user.username or 'без_username'} "
            f"(id {user.id}):\n\n{summary}",
        )

    # Опрос закончен — очищаем состояние.
    await state.clear()


# --- Запуск бота ----------------------------------------------------------

async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Запусти так:\n"
            "  BOT_TOKEN=твой_токен python bot.py"
        )
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    # start_polling — бот постоянно спрашивает Telegram о новых сообщениях.
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
