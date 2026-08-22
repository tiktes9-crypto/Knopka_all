import logging
import os
import json
import asyncio
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from aiohttp import web

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Словарь для хранения участников {chat_id: {user_id: user_data}}
chat_members = {}

def save_members():
    """Сохраняем участников в файл"""
    try:
        with open('members.json', 'w', encoding='utf-8') as f:
            json.dump(chat_members, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения участников: {e}")

def load_members():
    """Загружаем участников из файла"""
    global chat_members
    try:
        if os.path.exists('members.json'):
            with open('members.json', 'r', encoding='utf-8') as f:
                chat_members = json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки участников: {e}")

async def track_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отслеживаем активных участников"""
    if update.message and update.effective_user and update.effective_chat:
        chat_id = str(update.effective_chat.id)
        user = update.effective_user

        if not user.is_bot:
            if chat_id not in chat_members:
                chat_members[chat_id] = {}

            chat_members[chat_id][str(user.id)] = {
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name
            }
            save_members()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Привет! Используй команду /all чтобы упомянуть всех участников группы.\n\n'
        'Бот запоминает участников по их сообщениям в чате.'
    )

async def mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type in ['group', 'supergroup']:
        chat_id = str(chat.id)

        if chat_id in chat_members and chat_members[chat_id]:
            mentions = []
            for user_data in chat_members[chat_id].values():
                if user_data.get('username'):
                    mentions.append(f"@{user_data['username']}")
                else:
                    first_name = user_data.get('first_name', 'User')
                    mentions.append(f"[{first_name}](tg://user?id={user_data['id']})")

            if mentions:
                message = "📢 Призываю всех:\n\n" + " ".join(mentions)

                if context.args:
                    message += f"\n\n💬 {' '.join(context.args)}"

                await update.message.reply_text(message, parse_mode='Markdown')
            else:
                await update.message.reply_text("Список участников пуст.")
        else:
            await update.message.reply_text(
                "Еще не собрал участников. Бот запоминает пользователей по их сообщениям в чате."
            )
    else:
        await update.message.reply_text("Эта команда работает только в группах!")

async def clear_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить список участников для этого чата"""
    chat_id = str(update.effective_chat.id)

    if chat_id in chat_members:
        del chat_members[chat_id]
        save_members()
        await update.message.reply_text("Список участников очищен.")
    else:
        await update.message.reply_text("Список участников уже пуст.")

async def setup_commands(application: Application):
    """Устанавливаем меню команд для бота"""
    commands = [
        BotCommand("start", "Информация о боте"),
        BotCommand("all", "Упомянуть всех участников группы"),
        BotCommand("clear", "Очистить список участников"),
    ]
    await application.bot.set_my_commands(commands)

# Обработчик для пингов от cron-job.org / Render
async def health_check(request):
    return web.Response(text="OK", status=200)

async def main():
    TOKEN = os.getenv("BOT_TOKEN")
    PORT = int(os.getenv("PORT", "10000"))

    if not TOKEN:
        logger.error("Переменная BOT_TOKEN не задана!")
        return

    load_members()

    # Инициализация Telegram Application
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("all", mention_all))
    application.add_handler(CommandHandler("clear", clear_members))
    application.add_handler(MessageHandler(filters.ALL, track_members))
    
    await setup_commands(application)

    # Настройка aiohttp веб-сервера для ответа 200 OK на главный URL
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_head('/', health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {PORT}...")

    # Запуск Telegram бота
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Бот запущен в режиме polling...")

    # Держим процесс активным
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
