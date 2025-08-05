import telebot
from sqlalchemy import func
from telebot.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import configparser
from models import User, Category, CategoryType, Transaction
from db import SessionLocal
from contextlib import closing
import logging
from datetime import datetime, timedelta
from calendar import monthrange

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

config = configparser.ConfigParser()
config.read('settings.ini')
token = config["TOKEN"]['token']
bot = telebot.TeleBot(token)

# Глобальные переменные для управления состоянием отчета
user_report_state = {}
DATE_FORMAT = "%Y-%m-%d"


# Создание клавиатуры
def create_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton('Добавить трату'),
        KeyboardButton('Добавить доход'),
        KeyboardButton('Отчёт'),
        KeyboardButton('Добавить категорию'),
        KeyboardButton('Помощь')
    )
    return markup


def get_user(session, message):
    telegram_id = message.from_user.id
    user = session.query(User).filter_by(telegram_id=telegram_id).first()
    if not user:
        bot.reply_to(message, "⚠️ Сначала нужно зарегистрироваться командой /start", reply_markup=create_keyboard())
        return None
    return user


@bot.message_handler(commands=['start'])
def handle_start(message: Message):
    try:
        with closing(SessionLocal()) as session:
            telegram_id = message.from_user.id
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                user = User(
                    telegram_id=telegram_id,
                    username=message.from_user.username,
                    first_name=message.from_user.first_name,
                    last_name=message.from_user.last_name
                )
                session.add(user)
                session.commit()
                logger.info(f"Создан новый пользователь: {telegram_id}")
                help_text = (
                    "✅ Регистрация прошла успешно! Теперь ты можешь добавлять категории и транзакции.\n\n"
                    "💡 Для справки используй /help"
                )
                bot.reply_to(message, help_text, reply_markup=create_keyboard())
            else:
                logger.info(f"Пользователь уже существует: {telegram_id}")
                show_help(message)
    except Exception as e:
        logger.error(f"Ошибка в /start: {str(e)}")
        bot.reply_to(message, "❌ Произошла ошибка при регистрации. Попробуй снова.",
                     reply_markup=create_keyboard())


def show_help(message: Message):
    help_text = (
        "💡 Справка по боту\n\n"
        "💸 Добавить трату:\n"
        "трата <сумма> <категория>\n"
        "Пример: трата 300 продукты\n\n"
        "💰 Добавить доход:\n"
        "доход <сумма> <категория>\n"
        "Пример: доход 50000 зарплата\n\n"
        "📊 Показать отчёт: нажми кнопку 'Отчёт' или отправь /report\n"
        "📁 Добавить категорию: нажми кнопку 'Добавить категорию' или отправь /add_category\n\n"
        "Используй кнопки ниже для быстрого доступа 👇"
    )
    bot.reply_to(message, help_text, reply_markup=create_keyboard())


@bot.message_handler(commands=['help'])
@bot.message_handler(func=lambda m: m.text and m.text.strip().lower() == 'помощь')
def handle_help(message: Message):
    show_help(message)


@bot.message_handler(commands=['add_category'])
@bot.message_handler(func=lambda m: m.text and m.text.strip().lower() == 'добавить категорию')
def handle_add_category(message: Message):
    bot.reply_to(message,
                 "Напиши новую категорию в формате:\n\nтип название\n\nПримеры:\nтрата аптека\nдоход фриланс")
    bot.register_next_step_handler(message, save_new_category)


def save_new_category(message: Message):
    try:
        with closing(SessionLocal()) as session:
            user = get_user(session, message)
            if not user:
                return

            parts = message.text.strip().lower().split()
            if len(parts) != 2:
                bot.reply_to(message, "❌ Неверный формат. Попробуй ещё раз.", reply_markup=create_keyboard())
                return

            type_text, category_name = parts
            type_map = {"трата": CategoryType.expense, "доход": CategoryType.income}

            if type_text not in type_map:
                bot.reply_to(message, "❌ Тип должен быть 'трата' или 'доход'.", reply_markup=create_keyboard())
                return

            # Проверка существования категории
            exists = session.query(Category).filter_by(
                user_id=user.id,
                name=category_name,
                type=type_map[type_text]
            ).first()

            if exists:
                bot.reply_to(message, f"ℹ️ Категория '{category_name}' уже существует.", reply_markup=create_keyboard())
            else:
                category = Category(
                    user_id=user.id,
                    name=category_name,
                    type=type_map[type_text]
                )
                session.add(category)
                session.commit()
                logger.info(f"Добавлена категория: {category_name} для пользователя {user.id}")
                bot.reply_to(message, f"✅ Категория '{category_name}' добавлена!", reply_markup=create_keyboard())
    except Exception as e:
        logger.error(f"Ошибка при добавлении категории: {str(e)}")
        bot.reply_to(message, "❌ Произошла ошибка при добавлении категории. Попробуй снова.",
                     reply_markup=create_keyboard())


@bot.message_handler(func=lambda m: m.text and m.text.strip().lower() in ['добавить трату', 'добавить доход'] or
                                    (len(m.text.split()) > 0 and m.text.split()[0].lower() in ['трата', 'доход']))
def handle_transaction(message: Message):
    try:
        with closing(SessionLocal()) as session:
            user = get_user(session, message)
            if not user:
                return

            # Если нажата кнопка, просим ввести данные
            if message.text.strip().lower() in ['добавить трату', 'добавить доход']:
                example = "трата 300 продукты" if "трату" in message.text.lower() else "доход 50000 зарплата"
                bot.reply_to(message, f"Введи данные в формате:\n{example}")
                return

            parts = message.text.strip().lower().split()
            if len(parts) < 3:
                bot.reply_to(message, "❌ Неверный формат. Пример: трата 300 кафе",
                             reply_markup=create_keyboard())
                return

            type_text = parts[0]
            try:
                amount = float(parts[1])
                category_name = parts[2]
            except ValueError:
                bot.reply_to(message, "❌ Неверный формат суммы. Пример: трата 300 кафе",
                             reply_markup=create_keyboard())
                return

            type_map = {"трата": CategoryType.expense, "доход": CategoryType.income}

            if type_text not in type_map:
                bot.reply_to(message, "❌ Первое слово должно быть 'трата' или 'доход'. Пример: трата 300 кафе",
                             reply_markup=create_keyboard())
                return

            # Найти категорию
            category = session.query(Category).filter_by(
                user_id=user.id,
                name=category_name,
                type=type_map[type_text]
            ).first()

            if not category:
                bot.reply_to(message, f"❌ Категория '{category_name}' не найдена. Добавь её через /add_category",
                             reply_markup=create_keyboard())
                return

            # Добавить транзакцию
            transaction = Transaction(
                user_id=user.id,
                category_id=category.id,
                amount=amount,
                date=datetime.now()
            )
            session.add(transaction)
            session.commit()
            logger.info(f"Добавлена транзакция: {amount}₽ по категории {category_name} для пользователя {user.id}")

            emoji = "💸" if type_text == "трата" else "💰"
            bot.reply_to(message,
                         f"{emoji} {'Доход' if type_text == 'доход' else 'Трата'} {amount}₽ по категории '{category_name}' сохранена.",
                         reply_markup=create_keyboard())
    except Exception as e:
        logger.error(f"Ошибка при добавлении транзакции: {str(e)}")
        bot.reply_to(message, "❌ Произошла ошибка при сохранении транзакции. Попробуй снова.",
                     reply_markup=create_keyboard())


@bot.message_handler(commands=['report'])
@bot.message_handler(func=lambda m: m.text and m.text.strip().lower() == 'отчёт')
def handle_report(message: Message):
    try:
        # Сохраняем состояние пользователя
        user_report_state[message.from_user.id] = {
            'step': 'select_period_type',
            'start_date': None,
            'end_date': None
        }

        # Создаем клавиатуру для выбора типа периода
        markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add(
            KeyboardButton('Произвольный период'),
            KeyboardButton('Текущий день'),
            KeyboardButton('Текущая неделя'),
            KeyboardButton('Текущий месяц'),
            KeyboardButton('Текущий год'),
            KeyboardButton('Все время'),
            KeyboardButton('Назад')
        )

        bot.reply_to(message, "📆 Выбери тип периода для отчёта:", reply_markup=markup)
    except Exception as e:
        logger.error(f"Ошибка при формировании отчёта: {str(e)}")
        bot.reply_to(message, "❌ Произошла ошибка. Попробуй позже.", reply_markup=create_keyboard())


@bot.message_handler(func=lambda m: user_report_state.get(m.from_user.id, {}).get('step') == 'select_period_type')
def handle_period_type_selection(message: Message):
    try:
        user_id = message.from_user.id
        period_type = message.text.strip().lower()
        state = user_report_state.get(user_id, {})

        if period_type == 'назад':
            bot.reply_to(message, "Возвращаемся в главное меню", reply_markup=create_keyboard())
            if user_id in user_report_state:
                del user_report_state[user_id]
            return

        today = datetime.now().date()

        if period_type == 'текущий день':
            state['start_date'] = today
            state['end_date'] = today + timedelta(days=1)
            state['step'] = 'generate_report'
            generate_report(message, state)

        elif period_type == 'текущая неделя':
            # Начало недели (понедельник)
            start_date = today - timedelta(days=today.weekday())
            state['start_date'] = start_date
            state['end_date'] = start_date + timedelta(days=7)
            state['step'] = 'generate_report'
            generate_report(message, state)

        elif period_type == 'текущий месяц':
            start_date = today.replace(day=1)
            # Конец месяца
            _, last_day = monthrange(today.year, today.month)
            state['start_date'] = start_date
            state['end_date'] = start_date + timedelta(days=last_day)
            state['step'] = 'generate_report'
            generate_report(message, state)

        elif period_type == 'текущий год':
            start_date = today.replace(month=1, day=1)
            end_date = today.replace(month=12, day=31)
            state['start_date'] = start_date
            state['end_date'] = end_date
            state['step'] = 'generate_report'
            generate_report(message, state)

        elif period_type == 'все время':
            state['start_date'] = None
            state['end_date'] = None
            state['step'] = 'generate_report'
            generate_report(message, state)

        elif period_type == 'произвольный период':
            state['step'] = 'select_start_date'
            bot.reply_to(message, "📅 Введи начальную дату в формате ГГГГ-ММ-ДД (например, 2025-07-01):")

        else:
            bot.reply_to(message, "❌ Неизвестный тип периода. Попробуй еще раз.")

    except Exception as e:
        logger.error(f"Ошибка при выборе типа периода: {str(e)}")
        bot.reply_to(message, "❌ Произошла ошибка. Попробуй позже.", reply_markup=create_keyboard())


@bot.message_handler(func=lambda m: user_report_state.get(m.from_user.id, {}).get('step') == 'select_start_date')
def handle_start_date_selection(message: Message):
    try:
        user_id = message.from_user.id
        state = user_report_state.get(user_id, {})

        try:
            start_date = datetime.strptime(message.text, DATE_FORMAT).date()
            state['start_date'] = start_date
            state['step'] = 'select_end_date'
            bot.reply_to(message, "📅 Введи конечную дату в формате ГГГГ-ММ-ДД (например, 2025-07-15):")
        except ValueError:
            bot.reply_to(message, "❌ Неверный формат даты. Используй формат ГГГГ-ММ-ДД (например, 2025-07-15)")

    except Exception as e:
        logger.error(f"Ошибка при выборе начальной даты: {str(e)}")
        bot.reply_to(message, "❌ Произошла ошибка. Попробуй позже.", reply_markup=create_keyboard())


@bot.message_handler(func=lambda m: user_report_state.get(m.from_user.id, {}).get('step') == 'select_end_date')
def handle_end_date_selection(message: Message):
    try:
        user_id = message.from_user.id
        state = user_report_state.get(user_id, {})

        try:
            end_date = datetime.strptime(message.text, DATE_FORMAT).date()
            state['end_date'] = end_date + timedelta(days=1)  # Чтобы включить весь конечный день
            state['step'] = 'generate_report'
            generate_report(message, state)
        except ValueError:
            bot.reply_to(message, "❌ Неверный формат даты. Используй формат ГГГГ-ММ-ДД (например, 2025-07-15)")

    except Exception as e:
        logger.error(f"Ошибка при выборе конечной даты: {str(e)}")
        bot.reply_to(message, "❌ Произошла ошибка. Попробуй позже.", reply_markup=create_keyboard())


def generate_report(message: Message, state: dict):
    try:
        with closing(SessionLocal()) as session:
            user = get_user(session, message)
            if not user:
                if message.from_user.id in user_report_state:
                    del user_report_state[message.from_user.id]
                return

            start_date = state.get('start_date')
            end_date = state.get('end_date')

            # Запрос для сумм по категориям
            query = session.query(
                Category.name,
                Category.type,
                func.sum(Transaction.amount).label('total')
            ).join(Transaction.category).filter(
                Transaction.user_id == user.id
            )

            if start_date and end_date:
                # Преобразуем в datetime для сравнения
                start_datetime = datetime.combine(start_date, datetime.min.time())
                end_datetime = datetime.combine(end_date, datetime.min.time())

                query = query.filter(Transaction.date >= start_datetime, Transaction.date < end_datetime)
                period_title = f"📊 Отчёт за период с {start_date.strftime('%d.%m.%Y')} по {(end_date - timedelta(days=1)).strftime('%d.%m.%Y')}"
            else:
                period_title = "📊 Отчёт за всё время"

            results = query.group_by(Category.name, Category.type).all()

            if not results:
                bot.reply_to(message, "📭 Нет данных за выбранный период", reply_markup=create_keyboard())
                if message.from_user.id in user_report_state:
                    del user_report_state[message.from_user.id]
                return

            # Собираем данные
            income_total = 0
            expense_total = 0
            income_details = []
            expense_details = []

            for name, ctype, total in results:
                if ctype == CategoryType.income:
                    income_total += total
                    income_details.append((name, total))
                else:
                    expense_total += total
                    expense_details.append((name, total))

            balance = income_total - expense_total

            # Формируем отчёт
            report = [period_title]

            if income_details:
                report.append("\n💰 Доходы:")
                for name, amount in income_details:
                    report.append(f"  - {name}: {amount:.2f}₽")
                report.append(f"  Итого доходы: {income_total:.2f}₽")

            if expense_details:
                report.append("\n💸 Расходы:")
                for name, amount in expense_details:
                    report.append(f"  - {name}: {amount:.2f}₽")
                report.append(f"  Итого расходы: {expense_total:.2f}₽")

            report.append(f"\n📈 Баланс: {balance:.2f}₽")

            # Добавляем общее количество транзакций за период
            if start_date and end_date:
                tx_count = session.query(Transaction).filter(
                    Transaction.user_id == user.id,
                    Transaction.date >= start_datetime,
                    Transaction.date < end_datetime
                ).count()
            else:
                tx_count = session.query(Transaction).filter_by(user_id=user.id).count()

            report.append(f"Всего транзакций: {tx_count}")

            bot.reply_to(message, "\n".join(report), reply_markup=create_keyboard())

            # Очищаем состояние
            if message.from_user.id in user_report_state:
                del user_report_state[message.from_user.id]

    except Exception as e:
        logger.error(f"Ошибка при формировании отчёта: {str(e)}")
        bot.reply_to(message, "❌ Произошла ошибка при формировании отчёта. Попробуй позже.",
                     reply_markup=create_keyboard())
        if message.from_user.id in user_report_state:
            del user_report_state[message.from_user.id]


@bot.message_handler(func=lambda m: True)
def handle_other_messages(message: Message):
    """Обработчик для любых других сообщений"""
    # Проверяем, есть ли текст в сообщении
    if not message.text:
        return

    if message.text.startswith('/'):
        bot.reply_to(message, "❌ Неизвестная команда. Используй /help для списка команд.",
                     reply_markup=create_keyboard())
    else:
        bot.reply_to(message, "Я тебя не понимаю 😢\nИспользуй кнопки или команду /help", reply_markup=create_keyboard())


if __name__ == '__main__':
    logger.info("Бот запущен. Ожидаю команды...")
    bot.infinity_polling()