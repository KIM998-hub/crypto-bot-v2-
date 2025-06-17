import logging
import re
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CallbackContext
import ccxt

# التوكن الجديد (آمن)
TOKEN = "7935798222:AAFoiJJhw1bHVpLlsm_eG8HFUkQbZA0A8ik"
CHANNEL_ID = -1002509422719

active_signals = {}

def extract_signal_data(text):
    """فلتر متقدم ضد الإعلانات الروسية"""
    # 1. حذف جميع الروابط أولاً
    text = re.sub(r'http\S+', '', text)
    
    # 2. حذف العلامات الروسية النموذجية
    russian_patterns = [
        r'VPN прямо', r'Быстрый VPN', r'Поддерживаются все устройства',
        r'Telgram BOT', r'Попробуйте 7 дней', r'Без карт и тд',
        r'@vpn_telegr_bot', r'vpn\.arturshi\.ru', r'Открыть VPN',
        r'Резервная ссылка', r'в Telegram', r'Menu', r'Message'
    ]
    for pattern in russian_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # 3. حذف المحتوى السيريلي (الروسي) بشكل كامل
    text = re.sub(r'[\u0400-\u04FF]+', '', text)  # أهم تعديل!
    
    # 4. إزالة التنسيقات الخاصة والرموز
    text = re.sub(r'[^\w\s\.:/]', '', text)  # حذف الرموز غير الأبجدية
    
    # استخراج البيانات الأساسية بأنماط قوية
    coin_match = re.search(r'Coin:\s*(\w+/\w+)', text, re.IGNORECASE)
    if not coin_match:
        coin_match = re.search(r'الزوج:\s*(\w+/\w+)', text)
    
    entry_match = re.search(r'Entry Point:\s*(\d+\.\d+)', text, re.IGNORECASE)
    if not entry_match:
        entry_match = re.search(r'الدخول:\s*(\d+\.\d+)', text)
    
    sl_match = re.search(r'Stop Loss:\s*(\d+\.\d+)', text, re.IGNORECASE)
    if not sl_match:
        sl_match = re.search(r'وقف الخسارة:\s*(\d+\.\d+)', text)
    
    # استخراج أهداف الربح باستخدام نهج متين
    tp_levels = {}
    targets_section = re.search(r'Targets?:\s*((?:\d+\s*\.\d+\s*)+)', text, re.IGNORECASE)
    
    if targets_section:
        # استخراج جميع الأرقام العشرية في قسم الأهداف
        prices = re.findall(r'\d+\.\d+', targets_section.group(1))
        # تصفية الأسعار المنطقية فقط
        if entry_match and prices:
            entry_price = float(entry_match.group(1))
            # نأخذ فقط الأسعار الأعلى من سعر الدخول
            filtered_prices = [p for p in prices if float(p) > entry_price]
            # تعيين أرقام تلقائية للأهداف
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
            
            # خط دفاع أول: رفض أي رسالة روسية
            if re.search(r'[\u0400-\u04FF]', text) or 'VPN' in text.upper():
                logging.warning("⛔ تم حظر رسالة إعلانية")
                await update.message.delete()  # احذف الرسالة فوراً
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text="⚠️ تم حذف رسالة مشبوهة تحتوي على إعلان"
                )
                return
            
            # استخراج بيانات الإشارة بعد التنظيف الشديد
            signal_data = extract_signal_data(text)
            
            # إذا فشل الاستخراج، نستخدم الطريقة المباشرة
            if not signal_data["coin"] or not signal_data["entry"] or not signal_data["sl"] or not signal_data["targets"]:
                # محاولة بديلة: البحث عن الأنماط الأساسية مباشرة
                coin_match = re.search(r'Coin:\s*(\w+/\w+)', text, re.IGNORECASE)
                entry_match = re.search(r'Entry Point:\s*(\d+\.\d+)', text, re.IGNORECASE)
                sl_match = re.search(r'Stop Loss:\s*(\d+\.\d+)', text, re.IGNORECASE)
                
                # استخراج الأهداف مباشرة من النص الأصلي
                tp_levels = {}
                prices = re.findall(r'\d+\.\d+', text)
                if entry_match and prices:
                    entry_price = float(entry_match.group(1))
                    filtered_prices = [p for p in prices if float(p) > entry_price]
                    for i, price in enumerate(filtered_prices, 1):
                        tp_levels[i] = float(price)
                
                if coin_match and entry_match and sl_match and tp_levels:
                    signal_data = {
                        "coin": coin_match.group(1).strip(),
                        "entry": float(entry_match.group(1)),
                        "sl": float(sl_match.group(1)),
                        "targets": tp_levels
                    }
            
            # التحقق النهائي من وجود بيانات صالحة
            if not signal_data["coin"] or not signal_data["entry"] or not signal_data["sl"] or not signal_data["targets"]:
                logging.warning("⚠️ تعذر استخراج بيانات الإشارة بعد كل المحاولات")
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
                # ترتيب الأهداف تصاعدياً
                sorted_targets = sorted(data['targets'].items(), key=lambda x: x[1])
                
                for tp_num, tp_price in sorted_targets:
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
                        # كسر الحلقة بعد تحقيق هدف واحد
                        break
                
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
