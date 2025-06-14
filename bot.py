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
    # تنظيف النص من المحتوى الإعلاني الروسي
    cleaned_text = re.sub(r'Быстрый, и стабильный.*?vpn\.arturshi\.ru', '', text, flags=re.DOTALL)
    cleaned_text = re.sub(r'Попробуйте 7 дней.*?Резервная ссылка.*', '', cleaned_text, flags=re.DOTALL)
    
    # البحث عن الزوج (Coin)
    coin_match = re.search(r'Coin:\s*(\w+/\w+)', cleaned_text, re.IGNORECASE)
    if not coin_match:
        # محاولة ثانية: البحث عن الزوج بدون كلمة Coin
        coin_match = re.search(r'\b(\w+/\w+)\b', cleaned_text)
    
    # البحث عن نقطة الدخول (Entry Point)
    entry_match = re.search(r'Entry Point:\s*(\d+\.\d+)', cleaned_text, re.IGNORECASE)
    if not entry_match:
        entry_match = re.search(r'Entry:\s*(\d+\.\d+)', cleaned_text, re.IGNORECASE)
    
    # البحث عن وقف الخسارة (Stop Loss)
    sl_match = re.search(r'Stop Loss:\s*(\d+\.\d+)', cleaned_text, re.IGNORECASE)
    if not sl_match:
        sl_match = re.search(r'SL:\s*(\d+\.\d+)', cleaned_text, re.IGNORECASE)
    
    # استخراج أهداف الربح (Targets)
    tp_levels = {}
    targets_section = re.search(r'Targets:\s*((?:\d+\s+\d+\.\d+\s*)+)', cleaned_text, re.IGNORECASE)
    if not targets_section:
        # محاولة بديلة: البحث عن أرقام الأسعار فقط في قسم الأهداف
        targets_section = re.search(r'Targets:([\s\S]*?)(?:\n\n|\Z)', cleaned_text, re.IGNORECASE)
    
    if targets_section:
        tp_content = targets_section.group(1)
        # استخراج جميع أزواج (رقم الهدف والسعر)
        tp_matches = re.finditer(r'(\d+)\s+(\d+\.\d+)', tp_content)
        for match in tp_matches:
            tp_num = int(match.group(1))
            tp_price = float(match.group(2))
            tp_levels[tp_num] = tp_price
        
        # إذا لم نجد بهذه الطريقة، نجرب استخراج الأسعار فقط
        if not tp_levels:
            tp_prices = re.findall(r'\d+\.\d+', tp_content)
            for i, price in enumerate(tp_prices, 1):
                tp_levels[i] = float(price)

    # إرجاع البيانات المستخرجة
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
            
            # استخراج بيانات الإشارة
            signal_data = extract_signal_data(text)
            
            # التحقق من وجود بيانات كافية
            if not signal_data["coin"] or not signal_data["entry"] or not signal_data["sl"] or not signal_data["targets"]:
                logging.warning("⚠️ Could not extract valid signal data from message")
                return
            
            coin = signal_data["coin"]
            entry = signal_data["entry"]
            sl = signal_data["sl"]
            tp_levels = signal_data["targets"]
            
            # تخزين الإشارة في الذاكرة
            active_signals[coin] = {
                "entry": entry,
                "sl": sl,
                "targets": tp_levels,
                "achieved": set(),  # لتتبع الأهداف المحققة
                "message_id": update.message.forward_from_message_id
            }
            
            # إرسال رسالة تأكيد
            response = f"""✅ بدأ تتبع {coin}
الدخول: {entry}
وقف الخسارة: {sl}
عدد الأهداف: {len(tp_levels)}"""
            await update.message.reply_text(response)
            
    except Exception as e:
        logging.error(f"Error handling signal: {str(e)}", exc_info=True)

async def check_prices(context: CallbackContext):
    try:
        # نسخة من الإشارات النشطة لتجنب تغيير القاموس أثناء التكرار
        signals = list(active_signals.items())
        
        for coin, data in signals:
            try:
                # الحصول على السعر الحالي من Binance
                exchange = ccxt.binance()
                ticker = exchange.fetch_ticker(coin)
                current_price = ticker['last']
                
                # التحقق من وقف الخسارة (Stop Loss)
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
                    del active_signals[coin]  # إزالة الإشارة من التتبع
                    continue
                
                # التحقق من أهداف الربح (Targets)
                new_achievement = False
                for tp_num, tp_price in data['targets'].items():
                    if tp_num in data['achieved']:
                        continue  # تخطي الأهداف المحققة مسبقاً
                    
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
                        # تسجيل الهدف كمحقق
                        active_signals[coin]['achieved'].add(tp_num)
                        new_achievement = True
                
                # إذا تحققت جميع الأهداف، نوقف التتبع
                if len(active_signals[coin]['achieved']) == len(data['targets']):
                    del active_signals[coin]
                elif new_achievement:
                    # إذا تم تحقيق هدف جديد، نحدث البيانات (اختياري)
                    pass
                    
            except ccxt.NetworkError as e:
                logging.warning(f"Network error for {coin}: {str(e)}")
            except Exception as e:
                logging.error(f"Error checking price for {coin}: {str(e)}")
                # في حالة خطأ غير متوقع، نوقف التتبع
                del active_signals[coin]
                
    except Exception as e:
        logging.critical(f"Error in price check job: {str(e)}", exc_info=True)

def main():
    # إنشاء تطبيق البوت
    app = Application.builder().token(TOKEN).build()
    
    # حذف أي ويب هوك سابق لتجنب التعارض
    loop = asyncio.get_event_loop()
    loop.run_until_complete(app.bot.delete_webhook())
    
    # إضافة معالج الرسائل
    app.add_handler(MessageHandler(filters.TEXT & filters.FORWARDED, handle_forwarded_message))
    
    # جدولة مهمة التحقق من الأسعار كل دقيقة
    job_queue = app.job_queue
    job_queue.run_repeating(check_prices, interval=60, first=10)
    
    # تهيئة التسجيل
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)
    
    # بدء البوت
    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
