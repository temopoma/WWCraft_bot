import os
import sys
import time
import logging
import asyncio
import subprocess
import requests
import telebot
from telebot import apihelper
from playwright.async_api import async_playwright

# ---------- УСТАНОВКА БРАУЗЕРА (однократно) ----------
def install_browser():
    try:
        subprocess.run(["playwright", "install", "chromium", "--with-deps"], check=True, capture_output=True)
        logging.info("✅ Chromium установлен")
    except Exception as e:
        logging.error(f"❌ Ошибка установки Chromium: {e}")

# Для Railway: выполняем установку при старте, если браузер ещё не установлен
if not os.path.exists("/root/.cache/ms-playwright"):
    install_browser()
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

SERVER_ADDRESS = "WWCraft-48Fh.aternos.me"  # без порта

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

# ---------- ГЛОБАЛЬНЫЙ КЕШ ДЛЯ COOKIES ----------
COOKIE_FILE = "aternos_cookies.json"

async def get_aternos_status():
    """Запускает браузер, логинится в Aternos и возвращает статус сервера."""
    async with async_playwright() as p:
        # Запускаем браузер с минимальными параметрами для экономии памяти
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--disable-features=BlockInsecurePrivateNetworkRequests',
                '--disable-features=OutOfBlinkCors',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=block-all-mixed-content',
                '--disable-web-security',
                '--disable-features=CrossOriginOpenerPolicy,CrossOriginEmbedderPolicy',
                '--disable-features=SharedArrayBuffer',
                '--disable-features=COOP,COEP',
            ],
            timeout=30000
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        try:
            # Пробуем загрузить сохранённые cookies
            if os.path.exists(COOKIE_FILE):
                import json
                with open(COOKIE_FILE, 'r') as f:
                    cookies = json.load(f)
                await context.add_cookies(cookies)
                logger.info("🍪 Загружены сохранённые cookies")

            # Переходим на страницу сервера
            await page.goto(f"https://aternos.org/server/{SERVER_ADDRESS}", timeout=60000)
            await page.wait_for_timeout(2000)

            # Проверяем, нужен ли логин
            if "login" in page.url or page.url.startswith("https://aternos.org/login"):
                logger.info("🔑 Требуется логин")
                await page.fill('input[name="username"]', ATERNOS_USERNAME)
                await page.fill('input[name="password"]', ATERNOS_PASSWORD)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(5000)

                # Сохраняем cookies после логина
                cookies = await context.cookies()
                import json
                with open(COOKIE_FILE, 'w') as f:
                    json.dump(cookies, f, indent=2)
                logger.info("🍪 Cookies сохранены")

            # Ждём загрузки страницы сервера
            await page.wait_for_selector('.server-status', timeout=30000)

            # Получаем статус
            status_element = await page.query_selector('.server-status')
            if status_element:
                status_text = await status_element.inner_text()
                status_text = status_text.strip().lower()
                if 'online' in status_text:
                    status = 'online'
                elif 'offline' in status_text:
                    status = 'offline'
                else:
                    status = status_text
            else:
                status = 'неизвестно'

            # Также можно проверить наличие кнопки запуска
            start_button = await page.query_selector('button[data-action="start"]')
            if start_button and status == 'offline':
                # Сервер офлайн, кнопка есть
                pass

            return status

        except Exception as e:
            logger.error(f"Ошибка при получении статуса: {e}")
            raise
        finally:
            await browser.close()
            # Принудительный сбор мусора
            import gc
            gc.collect()

# ---------- СИНХРОННАЯ ОБЁРТКА ДЛЯ TELEBOT ----------
def get_status_sync():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(get_aternos_status())
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Ошибка в синхронной обёртке: {e}")
        return None

# ---------- КОМАНДЫ ----------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, "Привет! Я бот для управления сервером Aternos.\n"
                          "/status – статус (может занять 20-30 секунд)\n"
                          "/start_server – запуск\n"
                          "/stop_server – остановка")

@bot.message_handler(commands=['status'])
def cmd_status(message):
    bot.reply_to(message, "⏳ Проверяю статус, подождите... (до 30 секунд)")
    status = get_status_sync()
    if status is None:
        bot.reply_to(message, "❌ Не удалось получить статус (ошибка или таймаут)")
    else:
        bot.reply_to(message, f"🟢 Статус сервера: {status}")

# Заглушки для start/stop (позже добавим)
@bot.message_handler(commands=['start_server'])
def cmd_start_server(message):
    bot.reply_to(message, "⏳ Функция запуска в разработке")

@bot.message_handler(commands=['stop_server'])
def cmd_stop_server(message):
    bot.reply_to(message, "⏳ Функция остановки в разработке")

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