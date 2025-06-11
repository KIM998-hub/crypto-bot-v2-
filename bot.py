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
            coin_match = re.search(r"Coin:\s*(\w+/\w+)", text, re.IGNORECASE) or re.search(r"Pair:\s*(\w+/\w+)", text, re.IGNORECASE)
            entry_match = re.search(r"Entry Point:\s*(\d+\.\d+)", text, re.IGNORECASE)
            sl_match = re.search(r"Stop Loss:\s*(\d+\.\d+)", text, re.IGNORECASE)
            
            # استخراج أهداف الربح بعد كلمة Targets:
            tp_section = re.search(r"Targets:\s*([\d\s\.]+)", text, re.IGNORECASE)
            tp_matches = re.finditer(r"(\d+)\s+(\d+\.\d+)", text)
            
            if not (coin_match and entry_match and sl_match):
                await update.message.reply_text("⚠️ Could not parse the signal. Please check the format")
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
            
            if not tp_levels and tp_section:
                # محاولة بديلة لاستخراج الأرقام إذا كان التنسيق مختلفاً
                tp_prices = re.findall(r"\d+\.\d+", tp_section.group(1))
                for i, price in enumerate(tp_prices, 1):
                    tp_levels[f"tp{i}"] = float(price)
            
            if not tp_levels:
                await update.message.reply_text("⚠️ No profit targets found")
                return

            active_signals[coin] = {
                "entry": entry,
                "sl": sl,
                **tp_levels,
                "message_id": update.message.forward_from_message_id
            }
            
            await update.message.reply_text(f"✅ Started tracking {coin}\nEntry: {entry}\nSL: {sl}\nTargets: {len(tp_levels)}")

    except Exception as e:
        logging.error(f"Signal handling error: {str(e)}")
        await update.message.reply_text("❌ Error processing the signal")

async def check_prices(context: CallbackContext):
    try:
        for coin, data in list(active_signals.items()):
            try:
                ticker = ccxt.binance().fetch_ticker(coin)
                current_price = ticker['last']
                
                # Check SL first
                if current_price <= data['sl']:
                    loss_pct = ((data['entry'] - current_price) / data['entry']) * 100
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=f"🛑 STOP LOSS triggered for {coin}\n"
                             f"Current Price: {current_price:.4f}\n"
                             f"Loss: {loss_pct:.2f}%\n"
                             f"Entry: {data['entry']} | SL: {data['sl']}",
                        reply_to_message_id=data['message_id']
                    )
                    del active_signals[coin]
                    continue
                
                # Check TP levels
                triggered = False
                for tp_num in sorted([k for k in data.keys() if k.startswith('tp')]):
                    tp_price = data[tp_num]
                    if current_price >= tp_price:
                        profit_pct = ((current_price - data['entry']) / data['entry']) * 100
                        await context.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=f"🎯 TARGET {tp_num.upper()} HIT for {coin}\n"
                                 f"Current Price: {current_price:.4f}\n"
                                 f"Profit: +{profit_pct:.2f}%\n"
                                 f"Entry: {data['entry']} | Target: {tp_price}",
                            reply_to_message_id=data['message_id']
                        )
                        triggered = True
                        break
                
                if triggered:
                    del active_signals[coin]
                        
            except ccxt.NetworkError as e:
                logging.warning(f"Network error for {coin}: {str(e)}")
            except Exception as e:
                logging.error(f"Price check error for {coin}: {str(e)}")
                del active_signals[coin]
                
    except Exception as e:
        logging.critical(f"Global price check error: {str(e)}")

def main():
    # Initialize application
    app = Application.builder().token(TOKEN).build()
    
    # Add handlers
    app.add_handler(MessageHandler(filters.TEXT & filters.FORWARDED, handle_forwarded_message))
    
    # Set up periodic job
    job_queue = app.job_queue
    job_queue.run_repeating(
        callback=check_prices,
        interval=60.0,
        first=10
    )
    
    # Configure logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    logging.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
