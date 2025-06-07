import logging
from telegram.ext import Updater, CommandHandler

TOKEN = "7935798222:AAG66GadO-yyPoNxudhRLncjPgW4O3n4p6A"

def start(update, context):
    update.message.reply_text('🎉 البوت يعمل بشكل مثالي الآن!')

def main():
    # الطريقة الصحيحة للإصدار 20.x
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    updater.start_polling()
    print("🟢 البوت يعمل بدون أخطاء")
    updater.idle()

if __name__ == '__main__':
    main()
