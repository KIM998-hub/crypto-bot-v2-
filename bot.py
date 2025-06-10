import logging
import re
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CallbackContext
import ccxt

TOKEN = "7935798222:AAG66GadO-yyPoNxudhRLncjPgW4O3n4p6A"
CHANNEL_ID = -1002509422719

active_signals = {}

async def handle_forwarded_message(update: Update, context: CallbackContext):
    try:
        if update.message.forward_from_chat and update.message.forward_from_chat.id == CHANNEL_ID:
            text = update.message.text
            logging.info(f"Received signal: {text}")
            
            # استخراج البيانات بدقة
            coin_match = re.search(r"الزوج:\s*(\w+/\w+)", text)
            entry_match = re.search(r"الدخول:\s*(\d+\.\d+)", text)
            sl_match = re.search(r"وقف الخسارة:\s*(\d+\.\d+)", text)
            tp_matches = re.finditer(r"(\d+)️⃣\s*(\d+\.\d+)", text)
            
            if not (coin_match and entry_match and sl_match):
                await update.message.reply_text("⚠️ تعذر تحليل التوصية، يرجى التأكد من التنسيق")
                return

            coin = coin_match.group(1).strip()
            entry = float(entry_match.group(1))
            sl = float(sl_match.group(1))
            
            # استخراج نقاط TP
            tp_levels = {}
            for match in tp_matches:
                tp_num = int(match.group(1))
                tp_price = float(match.group(2))
                tp_levels[f"tp{tp_num}"] = tp_price
            
            if not tp_levels:
                await update.message.reply_text("⚠️ لم يتم العثور على أهداف ربح")
                return

            active_signals[coin] = {
                "entry": entry,
                "sl": sl,
                **tp_levels,
                "message_id": update.message.forward_from_message_id
            }
            
            await update.message.reply_text(f"✅ بدأ تتبع {coin} | الدخول: {entry} | SL: {sl}")

    except Exception as e:
        logging.error(f"Signal handling error: {str(e)}")
        await update.message.reply_text("❌ حدث خطأ في معالجة التوصية")

async def check_prices(context: CallbackContext):
    try:
        for coin, data in list(active_signals.items()):
            try:
                ticker = ccxt.binance().fetch_ticker(coin)
                current_price = ticker['last']
                
                # التحقق من SL أولاً
                if current_price <= data['sl']:
                    loss_pct = ((data['entry'] - current_price) / data['entry']) * 100
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=f"🛑 وقف خسارة {coin}\n"
                             f"السعر: {current_price:.2f} | الخسارة: {loss_pct:.1f}%\n"
                             f"الدخول: {data['entry']} | SL: {data['sl']}",
                        reply_to_message_id=data['message_id']
                    )
                    del active_signals[coin]
                    continue
                
                # التحقق من نقاط TP
                for tp_num in sorted([k for k in data.keys() if k.startswith('tp')]):
                    tp_price = data[tp_num]
                    if current_price >= tp_price:
                        profit_pct = ((current_price - data['entry']) / data['entry']) * 100
                        await context.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=f"🎯 تحقيق {tp_num.upper()} لـ {coin}\n"
                                 f"السعر: {current_price:.2f} | الربح: +{profit_pct:.1f}%\n"
                                 f"الدخول: {data['entry']} | {tp_num.upper()}: {tp_price}",
                            reply_to_message_id=data['message_id']
                        )
                        del active_signals[coin]
                        break
                        
            except ccxt.NetworkError as e:
                logging.warning(f"Network error for {coin}: {str(e)}")
            except Exception as e:
                logging.error(f"Price check error for {coin}: {str(e)}")
                del active_signals[coin]
                
    except Exception as e:
        logging.critical(f"Global price check error: {str(e)}")

def main():
    # تهيئة التطبيق
    app = Application.builder().token(TOKEN).build()
    
    # إضافة المعالجات
    app.add_handler(MessageHandler(filters.TEXT & filters.FORWARDED, handle_forwarded_message))
    
    # ضبط المهمة الدورية
    job_queue = app.job_queue
    job_queue.run_repeating(
        callback=check_prices,
        interval=60.0,
        first=10
    )
    
    # التسجيل والبدء
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    logging.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
