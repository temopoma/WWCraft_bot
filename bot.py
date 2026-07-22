import os
import sys
import telebot
from telebot import types
from telebot import apihelper
import time
import logging
import re
import requests

apihelper.CONNECT_TIMEOUT = 40
apihelper.READ_TIMEOUT = 40

TOKEN = os.environ.get("BOT_TOKEN", "") #getting token
if not TOKEN:
    sys.exit(1)

bot = telebot.TeleBot(TOKEN)

# logging in file
LOG_FILE = "bot_errors.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),  # in file
        logging.StreamHandler(sys.stdout)                  # in console
    ]
)
logger = logging.getLogger(__name__)


logger.info("=" * 50)
logger.info("WISTERIA WHISPER BOT STARTING")
logger.info("=" * 50)


def run_bot():
    restart_count = 0
    base_wait = 2  # начальная задержка 2 секунды
    while restart_count < 50:
        try:
            restart_count += 1
            logger.info(f"🔄 Попытка #{restart_count}")
            bot.polling(none_stop=True, interval=1, timeout=30, long_polling_timeout=5)
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"🌐 Сетевая ошибка: {e}. Переподключение через {base_wait}с")
            time.sleep(base_wait)
            base_wait = min(base_wait * 1.5, 30)  # экспоненциально до 30 сек
        except Exception as e:
            logger.critical(f"💥 Критическая ошибка: {e}")
            time.sleep(10)



@bot.message_handler(commands=['start_server'])
def handle_server_start(message):
    start_server()

def start_server(seconds=0):
    time.sleep(seconds)
    pass


@bot.message_handler(commands=['start_server_in'])
def handle_server_start_in(message):
    start_server(int(message.text[:15]))



if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную")
    except Exception as e:
        # Этот блок перехватит ошибки, возникшие ДО запуска polling
        logger.critical(f"💥 ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        import traceback
        logger.critical(traceback.format_exc())
        sys.exit(1)