import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler

TOKEN = "7935798222:AAG66GadO-yyPoNxudhRLncjPgW4O3n4p6A"

def start(update: Update, context):
    update.message.reply_text('✅ البوت يعمل!')

def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                       level=logging.INFO)
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
