import logging
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import ccxt

TOKEN = "7935798222:AAG66GadO-yyPoNxudhRLncjPgW4O3n4p6A"
CHANNEL_ID = -1002509422719

active_signals = {}

async def handle_forwarded_message(update: Update, context: CallbackContext):
    if update.message.forward_from_chat and update.message.forward_from_chat.id == CHANNEL_ID:
        text = update.message.text
        try:
            # استخراج البيانات باستخدام التعابير النمطية
            coin_match = re.search(r"الزوج: (\w+/\w+)", text)
            entry_match = re.search(r"نقطة الدخول: (\d+\.\d+)", text)
            sl_match = re.search(r"وقف الخسارة: (\d+\.\d+)", text)
            tp_matches = re.findall(r"(\d+)️⃣ (\d+\.\d+) USDT", text)
            
            if coin_match and entry_match and sl_match:
                coin = coin_match.group(1)
                entry = float(entry_match.group(1))
                sl = float(sl_match.group(1))
                
                # استخراج جميع نقاط TP
                tp_levels = {}
                for i, match in enumerate(tp_matches, start=1):
                    tp_levels[f"tp{i}"] = float(match[1])
                
                active_signals[coin] = {
                    "entry": entry,
                    "sl": sl,
                    **tp_levels,
                    "message_id": update.message.forward_from_message_id
                }
                
                await update.message.reply_text(f"✅ بدأ تتبع {coin} بنجاح!")
                
        except Exception as e:
            logging.error(f"Error parsing signal: {e}")

async def check_prices(context: CallbackContext):
    for coin, data in list(active_signals.items()):
        try:
            ticker = ccxt.binance().fetch_ticker(coin)
            current_price = ticker['last']
            
            # التحقق من SL أولاً
            if current_price <= data['sl']:
                loss = ((data['entry'] - current_price) / data['entry']) * 100
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=f"🛑 وقف خسارة {coin}\n📉 الخسارة: {loss:.1f}%\nالسعر الحالي: {current_price}",
                    reply_to_message_id=data['message_id']
                )
                del active_signals[coin]
                continue
                
            # التحقق من نقاط TP
            for i in range(1, 8):
                tp_key = f"tp{i}"
                if tp_key in data and current_price >= data[tp_key]:
                    profit = ((current_price - data['entry']) / data['entry']) * 100
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=f"🎯 تحقيق TP{i} لـ {coin}\n📈 الربح: +{profit:.1f}%\nالسعر الحالي: {current_price}",
                        reply_to_message_id=data['message_id']
                    )
                    del active_signals[coin]
                    break
                    
        except Exception as e:
            logging.error(f"Error checking prices: {e}")

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(MessageHandler(filters.TEXT & filters.FORWARDED, handle_forwarded_message))
    
    # فحص الأسعار كل دقيقة (60 ثانية)
    app.job_queue.run_repeating(check_prices, interval=60.0)
    
    app.run_polling()

if __name__ == "__main__":
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    main()
