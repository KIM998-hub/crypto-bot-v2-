import logging
from telegram.ext import Application, CommandHandler
from telegram import Update

TOKEN = "7935798222:AAG66GadO-yyPoNxudhRLncjPgW4O3n4p6A"

async def start(update: Update, context):
    await update.message.reply_text('✅ البوت يعمل الآن بكل سلاسة!')

def main():
    # إنشاء التطبيق باستخدام الأنماط الحديثة
    application = Application.builder().token(TOKEN).build()
    
    # إضافة الأمر start
    application.add_handler(CommandHandler("start", start))
    
    # تهيئة نظام التسجيل
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    logger = logging.getLogger(__name__)
    
    # بدء البوت
    application.run_polling()
    logger.info("🟢 البوت يعمل بدون مشاكل")

if __name__ == '__main__':
    main()
