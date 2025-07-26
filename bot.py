import logging
import re
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CallbackContext
import ccxt

# تكوينات البوت
TOKEN = "7935798222:AAFoiJJhw1bHVpLlsm_eG8HFUkQbZA0A8ik"
CHANNEL_ID = -1002509422719
ADMIN_ID = 123456789  # أضف أي دي المشرف هنا

# تهيئة السجل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

active_signals = {}
exchange = ccxt.binance({'enableRateLimit': True})

async def send_admin_alert(context: CallbackContext, message: str):
    """إرسال تنبيه للمشرف عند حدوث خطأ"""
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ تنبيه البوت:\n{message}")
    except Exception as e:
        logger.error(f"فشل في إرسال تنبيه للمشرف: {e}")

def extract_signal_data(text: str):
    """استخراج بيانات الإشارة من النص"""
    try:
        # تنظيف النص من المحتوى غير المرغوب
        text = re.sub(r'http\S+|[\u0400-\u04FF]+|[^\w\s\.\-:/]', '', text, flags=re.IGNORECASE)
        
        # استخراج الزوج
        coin_match = re.search(r'Coin:\s*(\w+/\w+)', text, re.IGNORECASE) or re.search(r'الزوج:\s*(\w+/\w+)', text)
        if not coin_match:
            return None

        # استخراج منطقة الدخول أو نقطة الدخول
        entry_zone_match = re.search(r'Entry Zone:\s*(\d+\.\d+)\s*-\s*(\d+\.\d+)', text, re.IGNORECASE)
        entry_match = re.search(r'Entry Point:\s*(\d+\.\d+)', text, re.IGNORECASE) if not entry_zone_match else None
        
        # استخراج وقف الخسارة
        sl_match = re.search(r'Stop Loss:\s*(\d+\.\d+)', text, re.IGNORECASE) or re.search(r'وقف الخسارة:\s*(\d+\.\d+)', text)
        
        # استخراج الأهداف
        targets = {}
        targets_section = re.search(r'Targets?:\s*((?:\d+\.\d+\s*)+)', text, re.IGNORECASE)
        if targets_section:
            prices = re.findall(r'\d+\.\d+', targets_section.group(1))
            entry_value = float(entry_zone_match.group(2)) if entry_zone_match else float(entry_match.group(1))
            targets = {i+1: float(price) for i, price in enumerate([p for p in prices if float(p) > entry_value])}

        if not all([coin_match, (entry_zone_match or entry_match), sl_match, targets]):
            return None

        return {
            "coin": coin_match.group(1).strip().upper(),
            "entry": {
                "type": "zone" if entry_zone_match else "point",
                "min": float(entry_zone_match.group(1)) if entry_zone_match else None,
                "max": float(entry_zone_match.group(2)) if entry_zone_match else None,
                "value": float(entry_zone_match.group(2)) if entry_zone_match else float(entry_match.group(1))
            },
            "sl": float(sl_match.group(1)),
            "targets": targets
        }
    except Exception as e:
        logger.error(f"خطأ في استخراج البيانات: {e}")
        return None

async def handle_forwarded_message(update: Update, context: CallbackContext):
    try:
        if not (update.message and update.message.forward_from_chat and update.message.forward_from_chat.id == CHANNEL_ID):
            return

        text = update.message.text or update.message.caption
        if not text:
            return

        # التحقق من الإعلانات
        if re.search(r'VPN|إعلان|advertisement', text, re.IGNORECASE):
            await update.message.delete()
            return

        signal_data = extract_signal_data(text)
        if not signal_data:
            logger.warning(f"فشل تحليل الإشارة: {text[:100]}...")
            return

        coin = signal_data["coin"]
        active_signals[coin] = {
            **signal_data,
            "achieved": set(),
            "message_id": update.message.forward_from_message_id,
            "chat_id": update.message.forward_from_chat.id
        }

        response = f"""✅ بدأ تتبع {coin}
نقطة الدخول: {signal_data['entry']['value']}
وقف الخسارة: {signal_data['sl']}
عدد الأهداف: {len(signal_data['targets'])}"""
        
        await update.message.reply_text(response)
        logger.info(f"تم تسجيل إشارة جديدة: {coin}")

    except Exception as e:
        logger.error(f"خطأ في معالجة الرسالة: {e}", exc_info=True)
        await send_admin_alert(context, f"خطأ في معالجة الرسالة: {e}")

async def check_prices(context: CallbackContext):
    if not active_signals:
        return

    for coin, data in list(active_signals.items()):
        try:
            ticker = await asyncio.to_thread(exchange.fetch_ticker, coin)
            current_price = ticker['last']
            entry_price = data['entry']['value']
            
            # التحقق من وقف الخسارة
            if current_price <= data['sl']:
                loss_pct = ((entry_price - current_price) / entry_price) * 100
                message = f"""🛑 تم تنفيذ وقف الخسارة لـ {coin}
السعر الحالي: {current_price:.8f}
الخسارة: {loss_pct:.2f}%
وقف الخسارة: {data['sl']}"""
                
                await context.bot.send_message(
                    chat_id=data['chat_id'],
                    text=message,
                    reply_to_message_id=data['message_id']
                )
                del active_signals[coin]
                continue

            # التحقق من الأهداف
            for tp_num, tp_price in sorted(data['targets'].items(), key=lambda x: x[1]):
                if tp_num in data['achieved']:
                    continue

                if current_price >= tp_price:
                    profit_pct = ((current_price - entry_price) / entry_price) * 100
                    message = f"""🎯 تم تحقيق الهدف {tp_num} لـ {coin}
السعر الحالي: {current_price:.8f}
الربح: +{profit_pct:.2f}%
الهدف: {tp_price}"""
                    
                    await context.bot.send_message(
                        chat_id=data['chat_id'],
                        text=message,
                        reply_to_message_id=data['message_id']
                    )
                    active_signals[coin]['achieved'].add(tp_num)
                    break

            # إذا تم تحقيق جميع الأهداف
            if len(active_signals[coin]['achieved']) == len(data['targets']):
                del active_signals[coin]

        except ccxt.NetworkError as e:
            logger.warning(f"خطأ في الشبكة لـ {coin}: {e}")
        except ccxt.ExchangeError as e:
            logger.warning(f"خطأ في البورصة لـ {coin}: {e}")
            await send_admin_alert(context, f"خطأ في البورصة لـ {coin}: {e}")
        except Exception as e:
            logger.error(f"خطأ غير متوقع لـ {coin}: {e}", exc_info=True)
            await send_admin_alert(context, f"خطأ غير متوقع لـ {coin}: {e}")

async def error_handler(update: Update, context: CallbackContext):
    logger.error(f"حدث خطأ: {context.error}", exc_info=True)
    await send_admin_alert(context, f"حدث خطأ: {context.error}")

def main():
    app = Application.builder().token(TOKEN).build()
    
    # معالجات الرسائل
    app.add_handler(MessageHandler(filters.TEXT & filters.FORWARDED, handle_forwarded_message))
    
    # معالج الأخطاء
    app.add_error_handler(error_handler)
    
    # مهمة التحقق من الأسعار
    app.job_queue.run_repeating(check_prices, interval=30, first=10)
    
    # بدء البوت
    logger.info("Starting bot in polling mode...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
