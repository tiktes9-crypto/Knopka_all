import logging
import os
import asyncio
import random
import asyncpg
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from aiohttp import web

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

db_pool = None

async def init_db(database_url: str):
    """Инициализация подключения к PostgreSQL и пересоздание правильной структуры"""
    global db_pool
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    db_pool = await asyncpg.create_pool(database_url)
    
    async with db_pool.acquire() as conn:
        # Создаем таблицу, где завязано на username
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_members_v2 (
                chat_id TEXT NOT NULL,
                username TEXT NOT NULL,
                first_name TEXT,
                PRIMARY KEY (chat_id, username)
            );
        ''')
    logger.info("Успешное подключение к PostgreSQL.")

async def track_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отслеживаем сообщения участников и сохраняем их юзернеймы"""
    if update.message and update.effective_user and update.effective_chat:
        chat_id = str(update.effective_chat.id)
        user = update.effective_user

        if not user.is_bot and user.username and db_pool:
            clean_username = user.username.replace('@', '').strip()
            
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO chat_members_v2 (chat_id, username, first_name)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (chat_id, username) 
                        DO UPDATE SET first_name = EXCLUDED.first_name;
                    ''', chat_id, clean_username, user.first_name)
            except Exception as e:
                logger.error(f"Ошибка автоматического сохранения: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Привет! Используй команду /all чтобы упомянуть всех участников группы.\n\n'
        'Добавляй участников через /add @username.'
    )

async def mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type in ['group', 'supergroup']:
        chat_id = str(chat.id)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    rows = await conn.fetch('''
                        SELECT username 
                        FROM chat_members_v2 
                        WHERE chat_id = $1;
                    ''', chat_id)

                if rows:
                    mentions = [f"@{row['username']}" for row in rows]
                    
                    message = "📢 Призываю всех:\n\n" + " ".join(mentions)
                    if context.args:
                        message += f"\n\n💬 {' '.join(context.args)}"

                    # Отправляем БЕЗ parse_mode, чтобы Telegram не портил знаки подчеркивания (_)
                    await update.message.reply_text(message)
                else:
                    await update.message.reply_text(
                        "Список участников пуст. Добавь их через /add @username!"
                    )
            except Exception as e:
                logger.error(f"Ошибка в mention_all: {e}")
                await update.message.reply_text("Произошла ошибка при получении списка участников.")
    else:
        await update.message.reply_text("Эта команда работает только в группах!")

async def clear_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить список участников для текущего чата"""
    chat = update.effective_chat
    if chat and db_pool:
        chat_id = str(chat.id)
        try:
            async with db_pool.acquire() as conn:
                await conn.execute('DELETE FROM chat_members_v2 WHERE chat_id = $1;', chat_id)
            await update.message.reply_text("База участников для этого чата полностью очищена!")
        except Exception as e:
            logger.error(f"Ошибка при очистке БД: {e}")
            await update.message.reply_text("Не удалось очистить базу данных.")

async def manual_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручное добавление/обновление участника по @username"""
    chat_id = str(update.effective_chat.id)
    
    if not context.args:
        await update.message.reply_text("Формат: /add @username\nПример: /add @kor_drums")
        return

    username = context.args[0].replace('@', '').strip()

    if not username:
        await update.message.reply_text("Укажите корректный юзернейм!")
        return

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO chat_members_v2 (chat_id, username, first_name)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (chat_id, username) DO NOTHING;
                ''', chat_id, username, username)
                
            await update.message.reply_text(f"Участник @{username} успешно добавлен!")
        except Exception as e:
            logger.error(f"Ошибка при добавлении пользователя: {e}")
            await update.message.reply_text("Ошибка при сохранении в базу данных.")

async def setup_commands(application: Application):
    """Установка меню команд"""
    commands = [
        BotCommand("start", "Информация о боте"),
        BotCommand("all", "Упомянуть всех участников группы"),
        BotCommand("add", "Добавить участника по @username"),
        BotCommand("clear", "Очистить список участников"),
    ]
    await application.bot.set_my_commands(commands)

async def health_check(request):
    return web.Response(text="OK", status=200)

async def main():
    TOKEN = os.getenv("BOT_TOKEN")
    DATABASE_URL = os.getenv("DATABASE_URL")
    PORT = int(os.getenv("PORT", "10000"))

    if not TOKEN or not DATABASE_URL:
        logger.error("Проверьте переменные BOT_TOKEN и DATABASE_URL!")
        return

    await init_db(DATABASE_URL)

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("all", mention_all))
    application.add_handler(CommandHandler("add", manual_add))
    application.add_handler(CommandHandler("clear", clear_members))
    application.add_handler(MessageHandler(filters.ALL, track_members))
    
    await setup_commands(application)

    app = web.Application()
    app.router.add_get('/', health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

    await application.initialize()
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Бот успешно запущен!")

    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
