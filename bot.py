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
    """استخراج بيانات الإشارة مع حماية كاملة ضد المحتوى الإعلاني"""
    # إزالة كافة الإعلانات الروسية باستخدام تعبيرات منتظمة دقيقة
    cleaned_text = re.sub(
        r'Быстрый, и стабильный.*?vpn\.arturshi\.ru|'
        r'Попробуйте 7 дней.*?Резервная ссылка.*|'
        r'📖 Telgram BOT.*?Поддерживаются все устройства.*?'
        r'(\[YouTube 💬\]|\[Instagram 💬\]).*?'
        r'Открыть VPN 💬',
        '', text, flags=re.DOTALL | re.IGNORECASE
    )
    
    # إزالة أي محتوى غير ضروري (رموز، تواريخ، إلخ)
    cleaned_text = re.sub(r'\d{1,2}:\d{1,2}\s*$', '', cleaned_text, flags=re.MULTILINE)
    cleaned_text = re.sub(r'\[Unread Messages\]|\[[x ]\]', '', cleaned_text)
    
    # استخراج البيانات الأساسية بأنماط مرنة
    coin_match = re.search(r'Coin:\s*(\w+/\w+)', cleaned_text) or \
                re.search(r'الزوج:\s*(\w+/\w+)', cleaned_text) or \
                re.search(r'\b([A-Z]{3,10}/[A-Z]{3,10})\b', cleaned_text)
    
    entry_match = re.search(r'Entry Point:\s*(\d+\.\d+)', cleaned_text) or \
                 re.search(r'الدخول:\s*(\d+\.\d+)', cleaned_text) or \
                 re.search(r'Entry:\s*(\d+\.\d+)', cleaned_text)
    
    sl_match = re.search(r'Stop Loss:\s*(\d+\.\d+)', cleaned_text) or \
               re.search(r'وقف الخسارة:\s*(\d+\.\d+)', cleaned_text) or \
               re.search(r'SL:\s*(\d+\.\d+)', cleaned_text)
    
    # استخراج أهداف الربح باستخدام نهج متعدد الطبقات
    tp_levels = {}
    
    # الطريقة 1: التنسيق المرقم
    targets_section = re.search(r'Targets:\s*((?:\d+\s+\d+\.\d+\s*)+)', cleaned_text)
    if targets_section:
        tp_matches = re.finditer(r'(\d+)\s+(\d+\.\d+)', targets_section.group(1))
        for match in tp_matches:
            tp_num = int(match.group(1))
            tp_price = float(match.group(2))
            tp_levels[tp_num] = tp_price
    
    # الطريقة 2: إذا فشلت الأولى، البحث عن قائمة الأسعار فقط
    if not tp_levels:
        prices = re.findall(r'\d+\.\d+', cleaned_text)
        # تصفية الأسعار غير المنطقية (أقل أو أعلى من السعر المتوقع)
        if entry_match and prices:
            entry_price = float(entry_match.group(1))
            filtered_prices = [p for p in prices if float(p) > entry_price * 0.9 and float(p) < entry_price * 3]
            for i, price in enumerate(filtered_prices, 1):
                tp_levels[i] = float(price)

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
            
            # محاولة استخراج البيانات مع إعادة المحاولة التلقائية
            signal_data = None
            for attempt in range(3):  # 3 محاولات
                signal_data = extract_signal_data(text)
                if signal_data["coin"] and signal_data["entry"] and signal_data["sl"] and signal_data["targets"]:
                    break
                # إذا فشلت المحاولة، تنظيف إضافي للنص
                text = re.sub(r'[^\w\s./:\d]', '', text)  # إزالة الرموز غير الضرورية
            
            # التحقق من وجود بيانات صالحة
            if not signal_data["coin"] or not signal_data["entry"] or not signal_data["sl"] or not signal_data["targets"]:
                logging.warning("⚠️ تعذر استخراج بيانات الإشارة بعد 3 محاولات")
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
                "achieved": set(),
                "message_id": update.message.forward_from_message_id
            }
            
            # إرسال رسالة تأكيد
            response = f"""✅ بدأ تتبع {coin}
الدخول: {entry}
وقف الخسارة: {sl}
عدد الأهداف: {len(tp_levels)}"""
            await update.message.reply_text(response)
            
    except Exception as e:
        logging.error(f"خطأ في معالجة الإشارة: {str(e)}", exc_info=True)

async def check_prices(context: CallbackContext):
    try:
        # نسخة من الإشارات النشطة لتجنب تغييرات أثناء التكرار
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
                    if coin in active_signals:
                        del active_signals[coin]
                    continue
                
                # التحقق من أهداف الربح (Targets)
                new_achievement = False
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
                        new_achievement = True
                
                # إذا تحققت جميع الأهداف، نوقف التتبع
                if coin in active_signals and len(active_signals[coin]['achieved']) == len(data['targets']):
                    del active_signals[coin]
                    
            except ccxt.NetworkError as e:
                logging.warning(f"خطأ في الشبكة لـ {coin}: {str(e)}")
            except Exception as e:
                logging.error(f"خطأ في فحص السعر لـ {coin}: {str(e)}")
                if coin in active_signals:
                    del active_signals[coin]
                
    except Exception as e:
        logging.critical(f"خطأ عام في فحص الأسعار: {str(e)}", exc_info=True)

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
