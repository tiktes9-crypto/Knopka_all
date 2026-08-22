import logging
import os
import asyncio
import asyncpg
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from aiohttp import web

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Глобальный пул соединений с БД
db_pool = None

async def init_db(database_url: str):
    """Инициализация подключения к PostgreSQL и создание таблицы"""
    global db_pool
    # Render выдает URL вида postgres://, asyncpg требует postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    db_pool = await asyncpg.create_pool(database_url)
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_members (
                chat_id TEXT NOT NULL,
                user_id BIGINT NOT NULL,
                username TEXT,
                first_name TEXT,
                PRIMARY KEY (chat_id, user_id)
            );
        ''')
    logger.info("Успешное подключение к PostgreSQL и проверка таблиц.")

async def track_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отслеживаем и сохраняем участников в БД"""
    if update.message and update.effective_user and update.effective_chat:
        chat_id = str(update.effective_chat.id)
        user = update.effective_user

        if not user.is_bot and db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO chat_members (chat_id, user_id, username, first_name)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (chat_id, user_id) 
                    DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name;
                ''', chat_id, user.id, user.username, user.first_name)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Привет! Используй команду /all чтобы упомянуть всех участников группы.\n\n'
        'Бот запоминает участников по их сообщениям в чате и хранит их в базе данных.'
    )

async def mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type in ['group', 'supergroup']:
        chat_id = str(chat.id)

        if db_pool:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT user_id, username, first_name 
                    FROM chat_members 
                    WHERE chat_id = $1;
                ''', chat_id)

            if rows:
                mentions = []
                for row in rows:
                    if row['username']:
                        mentions.append(f"@{row['username']}")
                    else:
                        first_name = row['first_name'] or 'User'
                        mentions.append(f"[{first_name}](tg://user?id={row['user_id']})")

                message = "📢 Призываю всех:\n\n" + " ".join(mentions)
                if context.args:
                    message += f"\n\n💬 {' '.join(context.args)}"

                await update.message.reply_text(message, parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    "Еще не собрал участников. Бот запоминает пользователей по их сообщениям в чате."
                )
    else:
        await update.message.reply_text("Эта команда работает только в группах!")

async def clear_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить список участников для текущего чата"""
    chat_id = str(chat.id) if (chat := update.effective_chat) else None

    if chat_id and db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute('DELETE FROM chat_members WHERE chat_id = $1;', chat_id)
        await update.message.reply_text("Список участников для этого чата очищен.")

async def setup_commands(application: Application):
    """Установка меню команд"""
    commands = [
        BotCommand("start", "Информация о боте"),
        BotCommand("all", "Упомянуть всех участников группы"),
        BotCommand("clear", "Очистить список участников"),
    ]
    await application.bot.set_my_commands(commands)

async def health_check(request):
    return web.Response(text="OK", status=200)

async def main():
    TOKEN = os.getenv("BOT_TOKEN")
    DATABASE_URL = os.getenv("DATABASE_URL")
    PORT = int(os.getenv("PORT", "10000"))

    if not TOKEN:
        logger.error("Переменная BOT_TOKEN не задана!")
        return

    if not DATABASE_URL:
        logger.error("Переменная DATABASE_URL не задана!")
        return

    # Подключаемся к базе данных
    await init_db(DATABASE_URL)

    # Инициализация Telegram Application
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("all", mention_all))
    application.add_handler(CommandHandler("clear", clear_members))
    application.add_handler(MessageHandler(filters.ALL, track_members))
    
    await setup_commands(application)

    # Веб-сервер для Render / cron-job.org
    app = web.Application()
    app.router.add_get('/', health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {PORT}...")

    # Старт бота в режиме polling с очисткой вебхуков
    await application.initialize()
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Бот запущен с подключенной базой PostgreSQL!")

    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
