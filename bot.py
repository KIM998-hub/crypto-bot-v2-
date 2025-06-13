import logging
import re
import asyncio
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
            
            # تنظيف المحتوى الإعلاني الروسي
            cleaned_text = re.sub(r'Быстрый, и стабильный.*?vpn\.arturshi\.ru', '', text, flags=re.DOTALL)
            cleaned_text = re.sub(r'Попробуйте 7 дней.*?Поддерживаются все устройства.*?\[YouTube 💬\].*?Резервная ссылка.*', 
                                '', cleaned_text, flags=re.DOTALL)
            
            # استخراج البيانات الأساسية
            coin_match = re.search(r'📊 Coin:\s*(\w+/\w+)|Coin:\s*(\w+/\w+)', cleaned_text, re.IGNORECASE)
            entry_match = re.search(r'🎯 Entry Point:\s*(\d+\.\d+)|Entry Point:\s*(\d+\.\d+)', cleaned_text, re.IGNORECASE)
            sl_match = re.search(r'🛡️ Stop Loss:\s*(\d+\.\d+)|Stop Loss:\s*(\d+\.\d+)', cleaned_text, re.IGNORECASE)
            
            # استخراج أهداف الربح
            tp_levels = {}
            targets_section = re.search(r'🎯 Targets:([\s\S]*?)(?:\n\n|\Z)|Targets:([\s\S]*?)(?:\n\n|\Z)', cleaned_text, re.IGNORECASE)
            
            if targets_section:
                tp_content = targets_section.group(1) or targets_section.group(2)
                if tp_content:
                    tp_lines = tp_content.strip().split('\n')
                    for line in tp_lines:
                        price_match = re.search(r'\d+\.\d+', line)
                        if price_match:
                            tp_num = len(tp_levels) + 1
                            tp_price = float(price_match.group(0))
                            tp_levels[f"tp{tp_num}"] = tp_price

            # التصحيح: استخراج القيم بشكل صحيح
            coin = None
            if coin_match:
                coin = coin_match.group(1) or coin_match.group(2)
            
            entry = None
            if entry_match:
                entry_val = entry_match.group(1) or entry_match.group(2)
                if entry_val:
                    entry = float(entry_val)
            
            sl = None
            if sl_match:
                sl_val = sl_match.group(1) or sl_match.group(2)
                if sl_val:
                    sl = float(sl_val)

            if not coin or not entry or not sl or not tp_levels:
                return

            active_signals[coin] = {
                "entry": entry,
                "sl": sl,
                "targets": tp_levels,
                "achieved": set(),
                "message_id": update.message.forward_from_message_id
            }
            
            response = f"""✅ بدأ تتبع {coin}
الدخول: {entry}
وقف الخسارة: {sl}
عدد الأهداف: {len(tp_levels)}"""
            
            await update.message.reply_text(response)

    except Exception as e:
        logging.error(f"خطأ في معالجة الإشارة: {str(e)}")

async def check_prices(context: CallbackContext):
    try:
        for coin, data in list(active_signals.items()):
            try:
                exchange = ccxt.binance()
                ticker = exchange.fetch_ticker(coin)
                current_price = ticker['last']
                
                # التحقق من وقف الخسارة
                if current_price <= data['sl']:
                    loss_pct = ((data['entry'] - current_price) / data['entry']) * 100
                    message = f"""🛑 تم تنفيذ وقف الخسارة لـ {coin}
السعر الحالي: {current_price:.4f}
الخسارة: {loss_pct:.2f}%
نقطة الدخول: {data['entry']}
وقف الخسارة: {data['sl']}"""
                    
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=message,
                        reply_to_message_id=data['message_id']
                    )
                    del active_signals[coin]
                    continue
                
                # التحقق من أهداف الربح
                new_achieved = False
                for tp_num, tp_price in data['targets'].items():
                    if tp_num in data['achieved']:
                        continue
                        
                    if current_price >= tp_price:
                        profit_pct = ((current_price - data['entry']) / data['entry']) * 100
                        message = f"""🎯 تم تحقيق الهدف {tp_num} لـ {coin}
السعر الحالي: {current_price:.4f}
الربح: +{profit_pct:.2f}%
نقطة الدخول: {data['entry']}
الهدف: {tp_price}"""
                        
                        await context.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=message,
                            reply_to_message_id=data['message_id']
                        )
                        active_signals[coin]['achieved'].add(tp_num)
                        new_achieved = True
                
                # حذف الإشارة إذا تحققت جميع الأهداف
                if len(active_signals[coin]['achieved']) == len(data['targets']):
                    del active_signals[coin]
                elif new_achieved:
                    active_signals[coin] = data
                            
            except ccxt.NetworkError as e:
                logging.warning(f"خطأ في الشبكة لـ {coin}: {str(e)}")
            except Exception as e:
                logging.error(f"خطأ في فحص السعر لـ {coin}: {str(e)}")
                del active_signals[coin]
                
    except Exception as e:
        logging.critical(f"خطأ عام في فحص الأسعار: {str(e)}")

def main():
    # حل مشكلة التعارض بين webhook و polling
    app = Application.builder().token(TOKEN).build()
    
    # 1. حذف أي webhook موجود مسبقاً
    loop = asyncio.get_event_loop()
    loop.run_until_complete(app.bot.delete_webhook())
    
    # 2. بدء البوت في وضع polling
    app.add_handler(MessageHandler(filters.TEXT & filters.FORWARDED, handle_forwarded_message))
    
    job_queue = app.job_queue
    job_queue.run_repeating(check_prices, interval=60.0, first=10)
    
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    logging.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
