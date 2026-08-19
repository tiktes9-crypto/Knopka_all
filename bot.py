import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Привет! Используй команду /all чтобы упомянуть всех участников группы.'
    )

async def mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type in ['group', 'supergroup']:
        try:
            administrators = await context.bot.get_chat_administrators(chat.id)

            mentions = []
            for admin in administrators:
                user = admin.user
                if not user.is_bot:
                    if user.username:
                        mentions.append(f"@{user.username}")
                    else:
                        mentions.append(f"[{user.first_name}](tg://user?id={user.id})")

            if mentions:
                message = "📢 Призываю всех:\n\n" + " ".join(mentions)

                if context.args:
                    message += f"\n\n💬 {' '.join(context.args)}"

                await update.message.reply_text(message, parse_mode='Markdown')
            else:
                await update.message.reply_text("Не удалось найти участников для упоминания.")

        except Exception as e:
            logger.error(f"Ошибка при получении участников: {e}")
            await update.message.reply_text("Произошла ошибка. Убедитесь, что бот является администратором группы.")
    else:
        await update.message.reply_text("Эта команда работает только в группах!")

def main():
    # Получаем новый токен из переменных окружения Render
    TOKEN = os.getenv("BOT_TOKEN")

    if not TOKEN:
        logger.error("Переменная BOT_TOKEN не задана!")
        return

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("all", mention_all))

    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
