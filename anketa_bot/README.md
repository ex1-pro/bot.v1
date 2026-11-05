# Бот-анкета (пример FSM на aiogram)

Учебный бот: задаёт 5 вопросов по очереди и в конце присылает
собранную анкету администратору. Показывает, как работает FSM
(пошаговый диалог) в aiogram 3.x.

## Установка

```bash
cd anketa_bot
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Запуск

1. Получи токен бота у @BotFather (команда `/newbot`).
2. (необязательно) Узнай свой Telegram ID у @userinfobot — туда придут анкеты.
3. Запусти:

```bash
BOT_TOKEN=сюда_токен ADMIN_ID=сюда_твой_id python bot.py
```

Без `ADMIN_ID` бот просто покажет анкету самому пользователю.

## Команды в боте

- `/start` — начать анкету
- `/cancel` — отменить

## Как устроен код (кратко)

- `class Form(StatesGroup)` — список шагов (состояний).
- `state.set_state(...)` — перевести бота на нужный шаг.
- `state.update_data(...)` — запомнить ответ.
- `state.get_data()` — забрать все ответы в конце.
- хэндлер `@router.message(Form.city)` срабатывает, только когда
  пользователь находится именно на шаге `city`.
