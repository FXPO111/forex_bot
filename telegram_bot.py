from telegram import Update, ReplyKeyboardMarkup, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
from core import get_best_answer, normalize_text
from quiz import get_quiz_question
import asyncio
import time
import os

TOKEN = os.getenv("BOT_TOKEN")
IMAGE_DIR = "images"

# Клавиатуры
start_only_keyboard = ReplyKeyboardMarkup([['▶️ Старт']], resize_keyboard=True)
start_keyboard = ReplyKeyboardMarkup([['Простой', 'Развернутый']], resize_keyboard=True)
mode_keyboard = ReplyKeyboardMarkup([['Простой', 'Развернутый']], resize_keyboard=True)

terms_keyboard_simple = ReplyKeyboardMarkup(
    [['маржа', 'плечо'], ['имбаланс', 'ликвидность'], ['волатильность', 'своп'], ['Сменить режим', '/help']],
    resize_keyboard=True
)

terms_keyboard_detailed = ReplyKeyboardMarkup(
    [['маржа', 'плечо'], ['имбаланс', 'ликвидность'], ['волатильность', 'своп'], ['quiz', 'train'], ['Сменить режим', '/help']],
    resize_keyboard=True
)

user_last_message_time = {}

def find_image_file(query: str):
    fname = query.replace(" ", "_") + ".png"
    path = os.path.join(IMAGE_DIR, fname)
    if os.path.exists(path):
        return path
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["started"] = False
    await update.message.reply_text(
        "👋 Добро пожаловать! Нажмите '▶️ Старт' для начала.",
        reply_markup=start_only_keyboard
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Доступные команды:\n"
        "/start - начать работу\n"
        "/help - помощь\n"
        "В простом режиме доступны базовые термины.\n"
        "В развернутом - дополнительные функции: quiz и train.\n"
        "В режиме train можно выйти командой 'Выйти из тренинга'."
    )
    await update.message.reply_text(help_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = time.time()
    if now - user_last_message_time.get(user_id, 0) < 1:
        await update.message.reply_text("⏳ Подождите секунду перед следующим сообщением.")
        return
    user_last_message_time[user_id] = now

    raw = update.message.text.strip()
    low = raw.lower()

    if not context.user_data.get("started"):
        if low == "▶️ старт":
            context.user_data["started"] = True
            await update.message.reply_text("Выберите режим:", reply_markup=mode_keyboard)
        else:
            await update.message.reply_text("👋 Пожалуйста, нажмите '▶️ Старт' для начала.", reply_markup=start_only_keyboard)
        return

    if context.user_data.get("in_train_mode"):
        if low == "выйти из тренинга":
            context.user_data["in_train_mode"] = False
            context.user_data.pop("correct", None)
            context.user_data.pop("explanation", None)
            context.user_data.pop("answered", None)
            await update.message.reply_text("Вы вышли из режима тренировки.", reply_markup=terms_keyboard_detailed)
            return
        await update.message.reply_text("Пожалуйста, отвечайте на вопросы с кнопок или нажмите 'Выйти из тренинга' для выхода.")
        return

    if low == "сменить режим":
        context.user_data.clear()
        context.user_data["started"] = True
        await update.message.reply_text("Режим сброшен. Выберите новый:", reply_markup=mode_keyboard)
        return
    if low == "простой":
        context.user_data["detailed"] = False
        await update.message.reply_text("✅ Простой режим.", reply_markup=terms_keyboard_simple)
        return
    if low == "развернутый":
        context.user_data["detailed"] = True
        await update.message.reply_text("✅ Развернутый режим.", reply_markup=terms_keyboard_detailed)
        return
    if "detailed" not in context.user_data:
        await update.message.reply_text("Сначала нажмите /start и выберите режим.", reply_markup=start_keyboard)
        return

    if context.user_data.get("detailed") and low in ["quiz", "train"]:
        if low == "quiz":
            await handle_quiz(update, context)
        elif low == "train":
            await handle_train(update, context)
        return

    query = normalize_text(raw)
    detailed = context.user_data["detailed"]
    answer, source = get_best_answer(query, detailed=detailed)
    response = f"📘 <b>Ответ:</b>\n{answer}\n\n<i>Источник: {source}</i>"
    await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    if detailed:
        img_path = find_image_file(query)
        if img_path:
            try:
                with open(img_path, "rb") as f:
                    await update.message.reply_photo(photo=InputFile(f))
            except Exception as e:
                print("Ошибка при отправке изображения:", e)

async def handle_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question_data = get_quiz_question()
    question = question_data["definition"]
    options = question_data["options"]
    correct_key = question_data["correct"]
    explanation = question_data.get("explanation", "")

    context.user_data["correct"] = correct_key
    context.user_data["explanation"] = explanation
    context.user_data["answered"] = False

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in options]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(f"🧠 Угадай термин:\n\n{question}", reply_markup=reply_markup)

    async def quiz_timeout():
        await asyncio.sleep(10)
        if not context.user_data.get("answered"):
            await update.message.reply_text(
                f"⏰ Время вышло! Правильный ответ: <b>{correct_key}</b>\n\n💡 {explanation}",
                parse_mode=ParseMode.HTML
            )
            context.user_data["answered"] = True

    context.user_data["quiz_task"] = asyncio.create_task(quiz_timeout())

async def handle_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["in_train_mode"] = True

    train_exit_keyboard = ReplyKeyboardMarkup([["Выйти из тренинга"]], resize_keyboard=True)

    chat_id = update.effective_chat.id

    await context.bot.send_message(
        chat_id=chat_id,
        text="🎯 Вы вошли в режим тренировки. Выберите тему или ответьте на вопрос.\n\nДля выхода нажмите 'Выйти из тренинга'.",
        reply_markup=train_exit_keyboard
    )

    question_data = get_quiz_question()
    question = question_data["definition"]
    options = question_data["options"]
    correct_key = question_data["correct"]
    explanation = question_data.get("explanation", "")

    context.user_data["correct"] = correct_key
    context.user_data["explanation"] = explanation
    context.user_data["answered"] = False

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in options]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🧠 Угадай термин:\n\n{question}",
        reply_markup=reply_markup
    )

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.callback_query.data
    correct = context.user_data.get("correct")
    explanation = context.user_data.get("explanation", "")
    context.user_data["answered"] = True

    quiz_task = context.user_data.get("quiz_task")
    if quiz_task and not quiz_task.done():
        quiz_task.cancel()

    if answer == correct:
        text = f"✅ Верно! Это <b>{correct}</b>.\n\n💡 {explanation}"
    else:
        text = f"❌ Неверно. Это был <b>{correct}</b>.\n\n💡 {explanation}"

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML)

    if context.user_data.get("in_train_mode"):
        await asyncio.sleep(1)
        await handle_train(update, context)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("quiz", handle_quiz))
    app.add_handler(CommandHandler("train", handle_train))
    app.add_handler(CallbackQueryHandler(handle_answer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()

