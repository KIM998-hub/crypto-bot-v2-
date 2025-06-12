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
            
            # تنظيف المحتوى الإعلاني
            cleaned_text = re.sub(r'Быстрый, и стабильный.*?vpn\.arturshi\.ru', '', text, flags=re.DOTALL)
            cleaned_text = re.sub(r'Попробуйте 7 дней.*?Поддерживаются все устройства.*?\[YouTube 💬\].*?Резервная ссылка.*', 
                                '', cleaned_text, flags=re.DOTALL)
            
            # استخراج البيانات الأساسية مع دعم جميع التنسيقات
            coin_match = re.search(r'(?:📊 Coin:|Coin:|\[Coin:)\s*(\w+/\w+)\]?', cleaned_text, re.IGNORECASE)
            entry_match = re.search(r'(?:🎯 Entry Point:|Entry Point:|\[Entry Point:)\s*(\d+\.\d+)\]?', cleaned_text, re.IGNORECASE)
            sl_match = re.search(r'(?:🛡️ Stop Loss:|Stop Loss:|\[Stop Loss:)\s*(\d+\.\d+)\]?', cleaned_text, re.IGNORECASE)
            
            # استخراج أهداف الربح
            tp_levels = {}
            targets_section = re.search(r'(?:🎯 Targets:|Targets:|\[Targets:)\s*((?:.+\n)+)', cleaned_text, re.IGNORECASE)
            
            if targets_section:
                tp_content = targets_section.group(1).strip()
                # استخراج جميع الأسعار من القسم
                tp_matches = re.finditer(r'(\d+)\s+(\d+\.\d+)', tp_content)
                for match in tp_matches:
                    tp_num = int(match.group(1))
                    tp_price = float(match.group(2))
                    tp_levels[tp_num] = tp_price

            if not coin_match:
                await update.message.reply_text("⚠️ Could not find Coin information")
                return
            if not entry_match:
                await update.message.reply_text("⚠️ Could not find Entry Point")
                return
            if not sl_match:
                await update.message.reply_text("⚠️ Could not find Stop Loss")
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
                "targets": tp_levels,  # تخزين جميع الأهداف
                "achieved": [],        # قائمة بالأهداف المحققة
                "message_id": update.message.forward_from_message_id
            }
            
            response = f"""✅ تم تسجيل الإشارة بنجاح: {coin}
نقطة الدخول: {entry}
وقف الخسارة: {sl}
عدد الأهداف: {len(tp_levels)}"""
            
            await update.message.reply_text(response)

    except Exception as e:
        logging.error(f"خطأ في معالجة الإشارة: {str(e)}")
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

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
                for tp_num, tp_price in data['targets'].items():
                    # تخطي الأهداف المحققة سابقاً
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
                        
                        # إضافة الهدف المحقق إلى القائمة
                        active_signals[coin]['achieved'].append(tp_num)
                        
                        # حذف الإشارة إذا تحققت جميع الأهداف
                        if len(active_signals[coin]['achieved']) == len(data['targets']):
                            del active_signals[coin]
                            break
                            
            except ccxt.NetworkError as e:
                logging.warning(f"خطأ في الشبكة لـ {coin}: {str(e)}")
            except Exception as e:
                logging.error(f"خطأ في فحص السعر لـ {coin}: {str(e)}")
                del active_signals[coin]
                
    except Exception as e:
        logging.critical(f"خطأ عام في فحص الأسعار: {str(e)}")

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
