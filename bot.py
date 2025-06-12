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
            logging.info(f"Received raw signal: {text}")
            
            # تنظيف النص من المحتوى الإعلاني غير المرغوب
            cleaned_text = re.sub(r'Быстрый, и стабильный.*?vpn\.arturshi\.ru', '', text, flags=re.DOTALL)
            cleaned_text = re.sub(r'Попробуйте 7 дней.*?Поддерживаются все устройства.*?\[YouTube 💬\].*?Резервная ссылка.*', 
                                '', cleaned_text, flags=re.DOTALL)
            
            # استخراج البيانات مع دعم الأقواس المربعة
            coin_match = re.search(r'(?:Coin:|\[Coin:)\s*(\w+/\w+)\]?', cleaned_text, re.IGNORECASE)
            entry_match = re.search(r'(?:Entry Point:|\[Entry Point:)\s*(\d+\.\d+)\]?', cleaned_text, re.IGNORECASE)
            sl_match = re.search(r'(?:Stop Loss:|\[Stop Loss:)\s*(\d+\.\d+)\]?', cleaned_text, re.IGNORECASE)
            
            # استخراج أهداف الربح
            tp_levels = {}
            targets_section = re.search(r'(?:Targets:|\[Targets:)\s*((?:\d+\.\d+\s*)+)', cleaned_text, re.IGNORECASE)
            
            if targets_section:
                # استخراج جميع الأرقام العشرية في قسم الأهداف
                tp_prices = re.findall(r'\d+\.\d+', targets_section.group(1))
                for i, price in enumerate(tp_prices, 1):
                    tp_levels[f"tp{i}"] = float(price)

            if not (coin_match and entry_match and sl_match):
                await update.message.reply_text("⚠️ Could not parse basic signal information (missing coin, entry or SL)")
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
        logging.error(f"Signal handling error: {str(e)}", exc_info=True)
        await update.message.reply_text(f"❌ Error processing signal: {str(e)}")

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
                for tp_num in sorted([k for k in data.keys() if k.startswith('tp')], 
                                    key=lambda x: int(x[2:])):
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
        logging.critical(f"Global price check error: {str(e)}", exc_info=True)

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
