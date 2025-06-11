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
            
            # استخراج البيانات من التنسيق الجديد
            coin_match = re.search(r"Coin:\s*(\w+/\w+)", text, re.IGNORECASE)
            entry_match = re.search(r"Entry Point:\s*(\d+\.\d+)", text, re.IGNORECASE)
            sl_match = re.search(r"Stop Loss:\s*(\d+\.\d+)", text, re.IGNORECASE)
            
            # استخراج أهداف الربح بطرق مختلفة
            tp_levels = {}
            
            # الطريقة 1: البحث عن الأرقام بعد كلمة Targets
            targets_section = re.search(r"Targets:([\s\S]*?)(?:\n\n|\Z)", text, re.IGNORECASE)
            if targets_section:
                tp_lines = targets_section.group(1).strip().split('\n')
                for line in tp_lines:
                    # دعم التنسيقات: "1. 439.3" أو "1 439.3" أو "439.3"
                    match = re.search(r"(\d+)\.?\s*(\d+\.\d+)", line.strip())
                    if match:
                        tp_num = int(match.group(1))
                        tp_price = float(match.group(2))
                        tp_levels[f"tp{tp_num}"] = tp_price
                    else:
                        # إذا كان السطر يحتوي فقط على الرقم بدون ترقيم
                        price_match = re.search(r"(\d+\.\d+)", line.strip())
                        if price_match:
                            tp_num = len(tp_levels) + 1
                            tp_price = float(price_match.group(1))
                            tp_levels[f"tp{tp_num}"] = tp_price

            if not (coin_match and entry_match and sl_match):
                await update.message.reply_text("⚠️ Could not parse basic signal information")
                return

            coin = coin_match.group(1).strip()
            entry = float(entry_match.group(1))
            sl = float(sl_match.group(1))
            
            if not tp_levels:
                await update.message.reply_text("⚠️ No profit targets found in the message")
                return

            active_signals[coin] = {
                "entry": entry,
                "sl": sl,
                **tp_levels,
                "message_id": update.message.forward_from_message_id
            }
            
            response = f"""✅ Successfully parsed signal for {coin}
Entry: {entry}
SL: {sl}
Targets: {len(tp_levels)}"""
            
            await update.message.reply_text(response)

    except Exception as e:
        logging.error(f"Signal handling error: {str(e)}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def check_prices(context: CallbackContext):
    try:
        for coin, data in list(active_signals.items()):
            try:
                exchange = ccxt.binance()
                ticker = exchange.fetch_ticker(coin)
                current_price = ticker['last']
                
                # Check Stop Loss
                if current_price <= data['sl']:
                    loss_pct = ((data['entry'] - current_price) / data['entry']) * 100
                    message = f"""🛑 STOP LOSS triggered for {coin}
Current Price: {current_price:.4f}
Loss: {loss_pct:.2f}%
Entry: {data['entry']}
SL: {data['sl']}"""
                    
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=message,
                        reply_to_message_id=data['message_id']
                    )
                    del active_signals[coin]
                    continue
                
                # Check Take Profit targets
                for tp_num in sorted(data.keys()):
                    if tp_num.startswith('tp'):
                        tp_price = data[tp_num]
                        if current_price >= tp_price:
                            profit_pct = ((current_price - data['entry']) / data['entry']) * 100
                            message = f"""🎯 TARGET {tp_num.upper()} HIT for {coin}
Current Price: {current_price:.4f}
Profit: +{profit_pct:.2f}%
Entry: {data['entry']}
Target: {tp_price}"""
                            
                            await context.bot.send_message(
                                chat_id=CHANNEL_ID,
                                text=message,
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
    app = Application.builder().token(TOKEN).build()
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
