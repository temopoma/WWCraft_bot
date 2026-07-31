import os
import sys
import time
import logging
import requests
import telebot
from telebot import apihelper

# ---------- УНИВЕРСАЛЬНЫЙ ИМПОРТ ДЛЯ ATERNOS ----------
from python_aternos import Client

try:
    from python_aternos import CloudflareError
except ImportError:
    try:
        from python_aternos.aterrors import CloudflareError
    except ImportError:
        # fallback – определяем свой класс для проверки по тексту
        class CloudflareError(Exception):
            pass
# ----------------------------------------------------

apihelper.CONNECT_TIMEOUT = 40
apihelper.READ_TIMEOUT = 40

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    sys.exit("❌ BOT_TOKEN не задан")

ATERNOS_USERNAME = os.environ.get("ATERNOS_USERNAME")
ATERNOS_PASSWORD = os.environ.get("ATERNOS_PASSWORD")
if not ATERNOS_USERNAME or not ATERNOS_PASSWORD:
    sys.exit("❌ ATERNOS_USERNAME или ATERNOS_PASSWORD не заданы")

SERVER_ADDRESS = "WWCraft-48Fh.aternos.me"   # без порта

# ---------- ЛОГИРОВАНИЕ ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot_errors.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)

# ---------- ГЛОБАЛЬНЫЙ КЕШ ----------
_client = None
_server = None

def ensure_client():
    global _client
    if _client is None:
        try:
            import cloudscraper
            session = cloudscraper.create_scraper()
            _client = Client(session=session)
            logger.info("🔑 Логинимся в Aternos...")
            _client.login(ATERNOS_USERNAME, ATERNOS_PASSWORD)
            logger.info("✅ Успешный вход")
        except CloudflareError as e:
            logger.error(f"CloudflareError: {e}")
            raise
        except Exception as e:
            logger.error(f"Ошибка при логине: {e}")
            raise
    return _client

def ensure_server():
    global _server
    if _server is None:
        client = ensure_client()
        servers = client.list_servers()           # правильный метод
        if not servers:
            raise RuntimeError("Список серверов пуст")
        for s in servers:
            if s.address == SERVER_ADDRESS:
                _server = s
                break
        if _server is None:
            logger.warning(f"Сервер {SERVER_ADDRESS} не найден, беру первый: {servers[0].address}")
            _server = servers[0]
        logger.info(f"✅ Выбран сервер: {_server.address}")
    return _server

def safe_server_call(message, action_func, success_msg, error_msg="❌ Ошибка"):
    try:
        server = ensure_server()
        action_func(server)
        bot.reply_to(message, success_msg)
    except CloudflareError:
        # сброс кеша и повтор
        global _client, _server
        _client = None
        _server = None
        try:
            server = ensure_server()
            action_func(server)
            bot.reply_to(message, success_msg)
        except Exception as e:
            logger.error(f"CloudflareError после перелогина: {e}")
            bot.reply_to(message, "❌ Aternos временно недоступен для ботов (Cloudflare). Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        bot.reply_to(message, f"{error_msg}: {e}")

# ---------- КОМАНДЫ ----------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, "Привет! Я бот для управления сервером Aternos.\n"
                          "/status – статус\n"
                          "/start_server – запуск\n"
                          "/stop_server – остановка")

@bot.message_handler(commands=['status'])
def cmd_status(message):
    try:
        server = ensure_server()
        server.fetch()
        bot.reply_to(message, f"🟢 Статус сервера: {server.status}")
    except CloudflareError:
        global _client, _server
        _client = None
        _server = None
        try:
            server = ensure_server()
            server.fetch()
            bot.reply_to(message, f"🟢 Статус сервера: {server.status}")
        except Exception as e:
            bot.reply_to(message, "❌ Ошибка Cloudflare, попробуйте позже.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['start_server'])
def cmd_start_server(message):
    safe_server_call(
        message,
        lambda s: s.start(),
        "✅ Сервер запускается...",
        "❌ Не удалось запустить сервер"
    )

@bot.message_handler(commands=['stop_server'])
def cmd_stop_server(message):
    safe_server_call(
        message,
        lambda s: s.stop(),
        "✅ Сервер останавливается...",
        "❌ Не удалось остановить сервер"
    )

# ---------- ЗАПУСК ----------
def run_bot():
    restart_count = 0
    base_wait = 2
    while restart_count < 50:
        try:
            restart_count += 1
            logger.info(f"🔄 Попытка #{restart_count}")
            bot.polling(none_stop=True, interval=1, timeout=30, long_polling_timeout=5)
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"🌐 Сетевая ошибка: {e}. Переподключение через {base_wait}с")
            time.sleep(base_wait)
            base_wait = min(base_wait * 1.5, 30)
        except Exception as e:
            logger.critical(f"💥 Критическая ошибка: {e}")
            time.sleep(10)

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную")
    except Exception as e:
        logger.critical(f"💥 ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        import traceback
        logger.critical(traceback.format_exc())
        sys.exit(1)