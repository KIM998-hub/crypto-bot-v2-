import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

TOKEN = "7935798222:AAG66GadO-yyPoNxudhRLncjPgW4O3n4p6A"

def start(update: Update, context: CallbackContext):
    update.message.reply_text('✅ البوت يعمل الآن بشكل صحيح!')

def main():
    # الطريقة الحديثة لتهيئة Updater
    updater = Updater(token=TOKEN, use_context=True)
    
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    updater.start_polling()
    print("🟢 البوت يعمل بدون أخطاء...")
    updater.idle()

if __name__ == '__main__':
    main()
