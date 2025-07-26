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
    """Advanced signal data extraction with support for both Entry Point and Entry Zone"""
    # 1. Remove all links first
    text = re.sub(r'http\S+', '', text)
    
    # 2. Remove common Russian ad patterns
    russian_patterns = [
        r'VPN прямо', r'Быстрый VPN', r'Поддерживаются все устройства',
        r'Telgram BOT', r'Попробуйте 7 дней', r'Без карт и тд',
        r'@vpn_telegr_bot', r'vpn\.arturshi\.ru', r'Открыть VPN',
        r'Резервная ссылка', r'в Telegram', r'Menu', r'Message'
    ]
    for pattern in russian_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # 3. Remove Cyrillic text completely
    text = re.sub(r'[\u0400-\u04FF]+', '', text)
    
    # 4. Remove special formatting and symbols
    text = re.sub(r'[^\w\s\.\-:/]', '', text)
    
    # Extract basic data with robust patterns
    coin_match = re.search(r'Coin:\s*(\w+/\w+)', text, re.IGNORECASE)
    if not coin_match:
        coin_match = re.search(r'الزوج:\s*(\w+/\w+)', text)
    
    # Support both Entry Point (single value) and Entry Zone (range)
    entry_match = re.search(r'Entry Point:\s*(\d+\.\d+)', text, re.IGNORECASE)
    entry_zone_match = re.search(r'Entry Zone:\s*(\d+\.\d+)\s*-\s*(\d+\.\d+)', text, re.IGNORECASE)
    
    if not entry_match and not entry_zone_match:
        entry_match = re.search(r'الدخول:\s*(\d+\.\d+)', text)
    
    sl_match = re.search(r'Stop Loss:\s*(\d+\.\d+)', text, re.IGNORECASE)
    if not sl_match:
        sl_match = re.search(r'وقف الخسارة:\s*(\d+\.\d+)', text)
    
    # Extract profit targets with robust approach
    tp_levels = {}
    targets_section = re.search(r'Targets?:\s*((?:\d+\s*\.\d+\s*)+)', text, re.IGNORECASE)
    
    if targets_section:
        # Extract all decimal numbers in targets section
        prices = re.findall(r'\d+\.\d+', targets_section.group(1))
        
        # Filter only logical prices
        if (entry_match or entry_zone_match) and prices:
            entry_price = float(entry_match.group(1)) if entry_match else float(entry_zone_match.group(1))
            # Take only prices higher than entry
            filtered_prices = [p for p in prices if float(p) > entry_price]
            # Assign automatic target numbers
            for i, price in enumerate(filtered_prices, 1):
                tp_levels[i] = float(price)

    # Determine entry type and values
    entry_data = None
    if entry_zone_match:
        entry_data = {
            "type": "zone",
            "min": float(entry_zone_match.group(1)),
            "max": float(entry_zone_match.group(2)),
            "avg": (float(entry_zone_match.group(1)) + float(entry_zone_match.group(2))) / 2
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
            
            # First line of defense: reject any Russian messages
            if re.search(r'[\u0400-\u04FF]', text) or 'VPN' in text.upper():
                logging.warning("⛔ Blocked advertisement message")
                await update.message.delete()
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text="⚠️ تم حذف رسالة مشبوهة تحتوي على إعلان"
                )
                return
            
            # Extract signal data after thorough cleaning
            signal_data = extract_signal_data(text)
            
            # If extraction fails, try direct approach
            if not signal_data["coin"] or not signal_data["entry"] or not signal_data["sl"] or not signal_data["targets"]:
                # Alternative attempt: search for basic patterns directly
                coin_match = re.search(r'Coin:\s*(\w+/\w+)', text, re.IGNORECASE)
                entry_match = re.search(r'Entry Point:\s*(\d+\.\d+)', text, re.IGNORECASE)
                entry_zone_match = re.search(r'Entry Zone:\s*(\d+\.\d+)\s*-\s*(\d+\.\d+)', text, re.IGNORECASE)
                sl_match = re.search(r'Stop Loss:\s*(\d+\.\d+)', text, re.IGNORECASE)
                
                # Extract targets directly from original text
                tp_levels = {}
                prices = re.findall(r'\d+\.\d+', text)
                
                entry_value = None
                if entry_match:
                    entry_value = float(entry_match.group(1))
                elif entry_zone_match:
                    entry_value = (float(entry_zone_match.group(1)) + float(entry_zone_match.group(2))) / 2
                
                if entry_value and prices:
                    filtered_prices = [p for p in prices if float(p) > entry_value]
                    for i, price in enumerate(filtered_prices, 1):
                        tp_levels[i] = float(price)
                
                if coin_match and (entry_match or entry_zone_match) and sl_match and tp_levels:
                    entry_data = None
                    if entry_zone_match:
                        entry_data = {
                            "type": "zone",
                            "min": float(entry_zone_match.group(1)),
                            "max": float(entry_zone_match.group(2)),
                            "avg": (float(entry_zone_match.group(1)) + float(entry_zone_match.group(2))) / 2
                        }
                    else:
                        entry_data = {
                            "type": "point",
                            "value": float(entry_match.group(1))
                        }
                    
                    signal_data = {
                        "coin": coin_match.group(1).strip(),
                        "entry": entry_data,
                        "sl": float(sl_match.group(1)),
                        "targets": tp_levels
                    }
            
            # Final validation of valid data
            if not signal_data["coin"] or not signal_data["entry"] or not signal_data["sl"] or not signal_data["targets"]:
                logging.warning("⚠️ Failed to extract signal data after all attempts")
                return
            
            coin = signal_data["coin"]
            entry = signal_data["entry"]
            sl = signal_data["sl"]
            tp_levels = signal_data["targets"]
            
            # Store signal in memory
            active_signals[coin] = {
                "entry": entry,
                "sl": sl,
                "targets": tp_levels,
                "achieved": set(),
                "message_id": update.message.forward_from_message_id
            }
            
            # Send confirmation message
            entry_text = ""
            if entry["type"] == "zone":
                entry_text = f"منطقة الدخول: {entry['min']} - {entry['max']} (متوسط: {entry['avg']})"
            else:
                entry_text = f"نقطة الدخول: {entry['value']}"
            
            response = f"""✅ بدأ تتبع {coin}
{entry_text}
وقف الخسارة: {sl}
عدد الأهداف: {len(tp_levels)}"""
            await update.message.reply_text(response)
            
    except Exception as e:
        logging.error(f"Error processing signal: {str(e)}", exc_info=True)

async def check_prices(context: CallbackContext):
    try:
        # Copy of active signals to avoid changes during iteration
        signals = list(active_signals.items())
        
        for coin, data in signals:
            try:
                # Get current price from Binance
                exchange = ccxt.binance()
                ticker = exchange.fetch_ticker(coin)
                current_price = ticker['last']
                
                # Determine entry price for calculations
                entry_price = data['entry']['avg'] if data['entry']['type'] == 'zone' else data['entry']['value']
                
                # Check Stop Loss
                if current_price <= data['sl']:
                    loss_pct = ((entry_price - current_price) / entry_price) * 100
                    
                    entry_text = ""
                    if data['entry']['type'] == "zone":
                        entry_text = f"منطقة الدخول: {data['entry']['min']} - {data['entry']['max']}"
                    else:
                        entry_text = f"نقطة الدخول: {entry_price}"
                    
                    message = f"""🛑 تم تنفيذ وقف الخسارة لـ {coin}
السعر الحالي: {current_price:.4f}
الخسارة: {loss_pct:.2f}%
{entry_text}
وقف الخسارة: {data['sl']}"""
                    
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=message,
                        reply_to_message_id=data['message_id']
                    )
                    if coin in active_signals:
                        del active_signals[coin]
                    continue
                
                # Check Profit Targets
                new_achievement = False
                # Sort targets ascending
                sorted_targets = sorted(data['targets'].items(), key=lambda x: x[1])
                
                for tp_num, tp_price in sorted_targets:
                    if tp_num in data['achieved']:
                        continue
                    
                    if current_price >= tp_price:
                        profit_pct = ((current_price - entry_price) / entry_price) * 100
                        
                        entry_text = ""
                        if data['entry']['type'] == "zone":
                            entry_text = f"متوسط الدخول: {entry_price}"
                        else:
                            entry_text = f"نقطة الدخول: {entry_price}"
                        
                        message = f"""🎯 تم تحقيق الهدف {tp_num} لـ {coin}
السعر الحالي: {current_price:.4f}
الربح: +{profit_pct:.2f}%
{entry_text}
الهدف: {tp_price}"""
                        
                        await context.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=message,
                            reply_to_message_id=data['message_id']
                        )
                        active_signals[coin]['achieved'].add(tp_num)
                        new_achievement = True
                        # Break after achieving one target
                        break
                
                # If all targets achieved, stop tracking
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
    # Create bot application
    app = Application.builder().token(TOKEN).build()
    
    # Delete any previous webhook to avoid conflicts
    loop = asyncio.get_event_loop()
    loop.run_until_complete(app.bot.delete_webhook())
    
    # Add message handler
    app.add_handler(MessageHandler(filters.TEXT & filters.FORWARDED, handle_forwarded_message))
    
    # Schedule price checking job every minute
    job_queue = app.job_queue
    job_queue.run_repeating(check_prices, interval=60, first=10)
    
    # Initialize logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)
    
    # Start the bot
    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
