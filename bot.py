import os
import sys
import time
import logging
import asyncio
import subprocess
import json
import requests
import telebot
from telebot import apihelper
from playwright.async_api import async_playwright

# ---------- УСТАНОВКА БРАУЗЕРА ----------
def install_browser():
    try:
        subprocess.run(["playwright", "install", "chromium", "--with-deps"], check=True, capture_output=True)
        print("✅ Chromium установлен")
    except Exception as e:
        print(f"❌ Ошибка установки Chromium: {e}")

if not os.path.exists("/root/.cache/ms-playwright"):
    install_browser()
# ---------------------------------------

apihelper.CONNECT_TIMEOUT = 40
apihelper.READ_TIMEOUT = 40

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    sys.exit("❌ BOT_TOKEN не задан")

ATERNOS_USERNAME = os.environ.get("ATERNOS_USERNAME")
ATERNOS_PASSWORD = os.environ.get("ATERNOS_PASSWORD")
if not ATERNOS_USERNAME or not ATERNOS_PASSWORD:
    sys.exit("❌ ATERNOS_USERNAME или ATERNOS_PASSWORD не заданы")

SERVER_ADDRESS = "WWCraft-48Fh.aternos.me"  # замените на ваш

# ---------- ЛОГИРОВАНИЕ ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot_errors.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)

COOKIE_FILE = "aternos_cookies.json"

# ---------- ФУНКЦИИ РАБОТЫ С КУКАМИ ----------
def save_cookies(cookies):
    """Сохраняет куки в файл в формате Playwright."""
    with open(COOKIE_FILE, 'w') as f:
        json.dump(cookies, f, indent=2)
    print("🍪 Куки сохранены в файл")

def load_cookies():
    """Загружает куки из файла, если он существует."""
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, 'r') as f:
            cookies = json.load(f)
        print("🍪 Куки загружены из файла")
        return cookies
    return None

# ---------- ОСНОВНАЯ ФУНКЦИЯ ----------
async def get_aternos_status():
    print("🚀 Запуск get_aternos_status")
    async with async_playwright() as p:
        # Запускаем браузер с параметрами для обхода детекции
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
            ],
            timeout=30000
        )
        # Создаем контекст с реалистичным User-Agent
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='ru-RU',
            timezone_id='Europe/Moscow',
        )
        page = await context.new_page()

        try:
            # Пробуем загрузить сохранённые куки
            cookies = load_cookies()
            if cookies:
                await context.add_cookies(cookies)

            server_url = f"https://aternos.org/server/{SERVER_ADDRESS}"
            print(f"🌐 Переход на {server_url}")
            await page.goto(server_url, timeout=60000, wait_until='networkidle')
            print(f"✅ Страница загружена, URL: {page.url}")

            # Ждём 3 секунды для стабилизации
            await page.wait_for_timeout(3000)

            # Проверяем, не попали ли на /go/ или страницу логина
            if "/go/" in page.url:
                print("⚠️ Перенаправлен на /go/ — сессия невалидна, пробуем логин")
                # Если есть куки, но они не работают, удаляем их
                if cookies:
                    os.remove(COOKIE_FILE)
                    print("🗑️ Удалены невалидные куки")
                # Переходим на страницу логина
                await page.goto("https://aternos.org/login/", timeout=60000, wait_until='networkidle')
                await page.wait_for_timeout(2000)

            # Если на странице логина — выполняем вход
            if "login" in page.url or "signin" in page.url:
                print("🔑 Требуется логин")
                # Заполняем форму
                await page.fill('input[name="username"]', ATERNOS_USERNAME)
                await page.fill('input[name="password"]', ATERNOS_PASSWORD)
                # Жмём кнопку входа
                await page.click('button[type="submit"]')
                print("⏳ Ожидаем входа...")
                await page.wait_for_timeout(5000)  # ждём редиректа
                # После логина сохраняем куки
                new_cookies = await context.cookies()
                save_cookies(new_cookies)
                print(f"✅ После логина URL: {page.url}")
                # Если после логина нас не перенаправило на страницу сервера, идём туда
                if "/server/" not in page.url:
                    await page.goto(server_url, timeout=60000, wait_until='networkidle')
                    await page.wait_for_timeout(3000)

            # Теперь мы должны быть на странице сервера. Ждём появления элемента статуса.
            print("⏳ Ожидаем элемент статуса...")
            try:
                # Ждём появления span.statuslabel-label с таймаутом 30 секунд
                await page.wait_for_selector('span.statuslabel-label', timeout=30000)
                print("✅ Элемент статуса найден")
            except Exception as e:
                print(f"❌ Элемент статуса не появился: {e}")
                # Сохраняем скриншот и HTML для отладки
                screenshot = await page.screenshot()
                with open("error_screenshot.png", "wb") as f:
                    f.write(screenshot)
                html = await page.content()
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(html)
                raise RuntimeError("Не удалось дождаться элемента статуса")

            # Получаем статус
            status_element = await page.query_selector('span.statuslabel-label')
            if status_element:
                status_text = await status_element.inner_text()
                status_text = status_text.strip().lower()
                print(f"🔍 Найден статус: '{status_text}'")
                if 'онлайн' in status_text or 'online' in status_text:
                    return 'online'
                elif 'офлайн' in status_text or 'offline' in status_text:
                    return 'offline'
                else:
                    return status_text
            else:
                print("⚠️ Элемент статуса не найден после ожидания")
                return 'unknown'

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            # Сохраняем скриншот и HTML для анализа
            try:
                screenshot = await page.screenshot()
                with open("error_screenshot.png", "wb") as f:
                    f.write(screenshot)
                html = await page.content()
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("📸 Скриншот и HTML сохранены для отладки")
            except:
                pass
            raise
        finally:
            await browser.close()
            import gc
            gc.collect()

# ---------- СИНХРОННАЯ ОБЁРТКА ----------
def get_status_sync():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(get_aternos_status())
        loop.close()
        return result
    except Exception as e:
        print(f"Ошибка в синхронной обёртке: {e}")
        return None

# ---------- КОМАНДЫ ----------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, "Привет! Я бот для управления сервером Aternos.\n"
                          "/status – проверить статус\n"
                          "/start_server – запуск (в разработке)\n"
                          "/stop_server – остановка (в разработке)")

@bot.message_handler(commands=['status'])
def cmd_status(message):
    bot.reply_to(message, "⏳ Проверяю статус, подождите... (до 30 секунд)")
    status = get_status_sync()
    if status is None:
        bot.reply_to(message, "❌ Не удалось получить статус (ошибка или таймаут)")
    else:
        bot.reply_to(message, f"🟢 Статус сервера: {status}")

@bot.message_handler(commands=['start_server'])
def cmd_start_server(message):
    bot.reply_to(message, "⏳ Функция запуска в разработке")

@bot.message_handler(commands=['stop_server'])
def cmd_stop_server(message):
    bot.reply_to(message, "⏳ Функция остановки в разработке")

# ---------- ЗАПУСК БОТА ----------
def run_bot():
    restart_count = 0
    base_wait = 2
    while restart_count < 50:
        try:
            restart_count += 1
            print(f"🔄 Попытка #{restart_count}")
            bot.polling(none_stop=True, interval=1, timeout=30, long_polling_timeout=5)
        except requests.exceptions.ConnectionError as e:
            print(f"🌐 Сетевая ошибка: {e}. Переподключение через {base_wait}с")
            time.sleep(base_wait)
            base_wait = min(base_wait * 1.5, 30)
        except Exception as e:
            print(f"💥 Критическая ошибка: {e}")
            time.sleep(10)

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        print("Бот остановлен вручную")
    except Exception as e:
        print(f"💥 ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)