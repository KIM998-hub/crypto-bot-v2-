import logging
import re
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CallbackContext
import ccxt

# Bot Token and Channel ID
TOKEN = "7935798222:AAFoiJJhw1bHVpLlsm_eG8HFUkQbZA0A8ik"
CHANNEL_ID = -1002509422719

active_signals = {}

def extract_signal_data(text):
    """استخراج بيانات الإشارة مع دعم Entry Zone و Entry Point"""
    # تنظيف النص من الإعلانات
    text = re.sub(r'http\S+', '', text)
    russian_patterns = [
        r'VPN прямо', r'Быстрый VPN', r'Поддерживаются все устройства',
        r'Telgram BOT', r'Попробуйте 7 дней', r'Без карт и тд',
        r'@vpn_telegr_bot', r'vpn\.arturshi\.ru', r'Открыть VPN',
        r'Резервная ссылка', r'в Telegram', r'Menu', r'Message'
    ]
    for pattern in russian_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    text = re.sub(r'[\u0400-\u04FF]+', '', text)
    text = re.sub(r'[^\w\s\.\-:/]', '', text)
    
    # استخراج البيانات الأساسية
    coin_match = re.search(r'Coin:\s*(\w+/\w+)', text, re.IGNORECASE)
    if not coin_match:
        coin_match = re.search(r'الزوج:\s*(\w+/\w+)', text)
    
    # دعم كلا النوعين Entry Point و Entry Zone
    entry_match = re.search(r'Entry Point:\s*(\d+\.\d+)', text, re.IGNORECASE)
    entry_zone_match = re.search(r'Entry Zone:\s*(\d+\.\d+)\s*-\s*(\d+\.\d+)', text, re.IGNORECASE)
    
    if not entry_match and not entry_zone_match:
        entry_match = re.search(r'الدخول:\s*(\d+\.\d+)', text)
    
    sl_match = re.search(r'Stop Loss:\s*(\d+\.\d+)', text, re.IGNORECASE)
    if not sl_match:
        sl_match = re.search(r'وقف الخسارة:\s*(\d+\.\d+)', text)
    
    # استخراج أهداف الربح
    tp_levels = {}
    targets_section = re.search(r'Targets?:\s*((?:\d+\s*\.\d+\s*)+)', text, re.IGNORECASE)
    
    if targets_section:
        prices = re.findall(r'\d+\.\d+', targets_section.group(1))
        if (entry_match or entry_zone_match) and prices:
            entry_price = float(entry_zone_match.group(2)) if entry_zone_match else float(entry_match.group(1))
            filtered_prices = [p for p in prices if float(p) > entry_price]
            for i, price in enumerate(filtered_prices, 1):
                tp_levels[i] = float(price)

    # تحديد نوع ونقطة الدخول
    entry_data = None
    if entry_zone_match:
        entry_data = {
            "type": "zone",
            "min": float(entry_zone_match.group(1)),
            "max": float(entry_zone_match.group(2)),
            "value": float(entry_zone_match.group(2))  # نستخدم أعلى قيمة في المنطقة
        }
    elif entry_match:
        entry_data = {
            "type": "point",
            "value": float(entry_match.group(1))
        }

    return {
        "coin": coin_match.group(1).strip() if coin_match else None,
        "entry": entry_data,
        "sl": float(sl_match.group(1)) if sl_match else None,
        "targets": tp_levels
    }

async def handle_forwarded_message(update: Update, context: CallbackContext):
    try:
        if update.message.forward_from_chat and update.message.forward_from_chat.id == CHANNEL_ID:
            text = update.message.text
            logging.info(f"Received signal: {text}")
            
            if re.search(r'[\u0400-\u04FF]', text) or 'VPN' in text.upper():
                logging.warning("⛔ Blocked advertisement message")
                await update.message.delete()
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text="⚠️ تم حذف رسالة مشبوهة تحتوي على إعلان"
                )
                return
            
            signal_data = extract_signal_data(text)
            
            if not signal_data["coin"] or not signal_data["entry"] or not signal_data["sl"] or not signal_data["targets"]:
                logging.warning("⚠️ Failed to extract signal data")
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
            
            # رسالة التأكيد
            entry_text = f"نقطة الدخول: {entry['value']}"  # نعرض فقط أعلى قيمة
            response = f"""✅ بدأ تتبع {coin}
{entry_text}
وقف الخسارة: {sl}
عدد الأهداف: {len(tp_levels)}"""
            await update.message.reply_text(response)
            
    except Exception as e:
        logging.error(f"Error processing signal: {str(e)}", exc_info=True)

async def check_prices(context: CallbackContext):
    try:
        signals = list(active_signals.items())
        
        for coin, data in signals:
            try:
                exchange = ccxt.binance()
                ticker = exchange.fetch_ticker(coin)
                current_price = ticker['last']
                entry_price = data['entry']['value']  # نستخدم أعلى قيمة دائماً
                
                # التحقق من وقف الخسارة
                if current_price <= data['sl']:
                    loss_pct = ((entry_price - current_price) / entry_price) * 100
                    
                    message = f"""🛑 تم تنفيذ وقف الخسارة لـ {coin}
السعر الحالي: {current_price:.4f}
الخسارة: {loss_pct:.2f}%
وقف الخسارة: {data['sl']}"""
                    
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=message,
                        reply_to_message_id=data['message_id']
                    )
                    if coin in active_signals:
                        del active_signals[coin]
                    continue
                
                # التحقق من أهداف الربح
                new_achievement = False
                sorted_targets = sorted(data['targets'].items(), key=lambda x: x[1])
                
                for tp_num, tp_price in sorted_targets:
                    if tp_num in data['achieved']:
                        continue
                    
                    if current_price >= tp_price:
                        profit_pct = ((current_price - entry_price) / entry_price) * 100
                        
                        message = f"""🎯 تم تحقيق الهدف {tp_num} لـ {coin}
السعر الحالي: {current_price:.4f}
الربح: +{profit_pct:.2f}%
الهدف: {tp_price}"""
                        
                        await context.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=message,
                            reply_to_message_id=data['message_id']
                        )
                        active_signals[coin]['achieved'].add(tp_num)
                        new_achievement = True
                        break
                
                if coin in active_signals and len(active_signals[coin]['achieved']) == len(data['targets']):
                    del active_signals[coin]
                    
            except ccxt.NetworkError as e:
                logging.warning(f"Network error for {coin}: {str(e)}")
            except Exception as e:
                logging.error(f"Price check error for {coin}: {str(e)}")
                if coin in active_signals:
                    del active_signals[coin]
                
    except Exception as e:
        logging.critical(f"General price check error: {str(e)}", exc_info=True)

def main():
    app = Application.builder().token(TOKEN).build()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(app.bot.delete_webhook())
    app.add_handler(MessageHandler(filters.TEXT & filters.FORWARDED, handle_forwarded_message))
    job_queue = app.job_queue
    job_queue.run_repeating(check_prices, interval=60, first=10)
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
