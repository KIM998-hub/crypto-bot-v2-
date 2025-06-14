import logging
import re
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CallbackContext
import ccxt

TOKEN = "7935798222:AAG66GadO-yyPoNxudhRLncjPgW4O3n4p6A"
CHANNEL_ID = -1002509422719

active_signals = {}

def extract_signal_data(text):
    """استخراج بيانات الإشارة بدقة مع تجنب المحتوى الإعلاني"""
    # محاولة تحديد بداية ونهاية الإشارة الحقيقية
    signal_start = re.search(r'Dream crypto spot signals\s+New Spot Signal', text)
    if not signal_start:
        return None
        
    # أخذ جزء النص بعد بداية الإشارة
    signal_text = text[signal_start.end():]
    
    # إيجاد نهاية الإشارة (قبل بداية الإعلان الروسي)
    signal_end = re.search(r'(Быстрый, и стабильный|Попробуйте 7 дней|Открыть VPN)', signal_text)
    if signal_end:
        signal_text = signal_text[:signal_end.start()]
    
    # الآن استخراج البيانات من الجزء النظيف
    coin_match = re.search(r'Coin:\s*(\w+/\w+)', signal_text, re.IGNORECASE)
    entry_match = re.search(r'Entry Point:\s*(\d+\.\d+)', signal_text, re.IGNORECASE)
    sl_match = re.search(r'Stop Loss:\s*(\d+\.\d+)', signal_text, re.IGNORECASE)
    
    # استخراج أهداف الربح بدقة
    tp_levels = {}
    targets_section = re.search(r'Targets:\s*((?:\d+\s+\d+\.\d+\s*)+)', signal_text, re.IGNORECASE)
    if targets_section:
        tp_lines = targets_section.group(1).strip().split('\n')
        for line in tp_lines:
            match = re.match(r'(\d+)\s+(\d+\.\d+)', line.strip())
            if match:
                tp_num = int(match.group(1))
                tp_price = float(match.group(2))
                tp_levels[tp_num] = tp_price

    return {
        "coin": coin_match.group(1).strip() if coin_match else None,
        "entry": float(entry_match.group(1)) if entry_match else None,
        "sl": float(sl_match.group(1)) if sl_match else None,
        "targets": tp_levels
    }

async def handle_forwarded_message(update: Update, context: CallbackContext):
    try:
        if update.message.forward_from_chat and update.message.forward_from_chat.id == CHANNEL_ID:
            text = update.message.text
            logging.info(f"Received signal: {text}")
            
            # استخراج بيانات الإشارة باستخدام الدالة الجديدة
            signal_data = extract_signal_data(text)
            
            if not signal_data or not signal_data["coin"] or not signal_data["entry"] or not signal_data["sl"] or not signal_data["targets"]:
                logging.warning("⚠️ Could not extract valid signal data")
                return

            coin = signal_data["coin"]
            entry = signal_data["entry"]
            sl = signal_data["sl"]
            tp_levels = signal_data["targets"]

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
        logging.error(f"خطأ في معالجة الإشارة: {str(e)}", exc_info=True)

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
                    # تحديث حالة الإشارة
                    active_signals[coin] = data
                            
            except ccxt.NetworkError as e:
                logging.warning(f"خطأ في الشبكة لـ {coin}: {str(e)}")
            except Exception as e:
                logging.error(f"خطأ في فحص السعر لـ {coin}: {str(e)}", exc_info=True)
                del active_signals[coin]
                
    except Exception as e:
        logging.critical(f"خطأ عام في فحص الأسعار: {str(e)}", exc_info=True)

def main():
    # حل مشكلة التعارض بين webhook و polling
    app = Application.builder().token(TOKEN).build()
    
    # حذف أي webhook موجود مسبقاً
    loop = asyncio.get_event_loop()
    loop.run_until_complete(app.bot.delete_webhook())
    
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
