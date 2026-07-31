import os
import sys
import time
import logging
import json
import asyncio
import subprocess
import requests
import telebot
from telebot import apihelper, types
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

ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
if not ADMIN_ID:
    sys.exit("❌ ADMIN_ID не задан")

SERVER_ADDRESS = os.environ.get("SERVER_ADDRESS", "WWCraft-48Fh.aternos.me")
COOKIE_FILE = "cookies.json"

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

# ---------- НОРМАЛИЗАЦИЯ КУК ----------
def normalize_cookies(cookies):
    """
    Приводит куки к формату, который принимает Playwright:
    - sameSite: одно из 'Strict', 'Lax', 'None'
    - проверяет наличие обязательных полей
    """
    normalized = []
    for cookie in cookies:
        # Приводим sameSite
        same_site = cookie.get("sameSite", "Lax")
        if same_site.lower() == "no_restriction":
            same_site = "None"
        elif same_site.lower() == "unspecified":
            same_site = "Lax"
        elif same_site not in ("Strict", "Lax", "None"):
            # по умолчанию ставим Lax
            same_site = "Lax"

        # Обеспечиваем наличие обязательных полей
        new_cookie = {
            "name": cookie.get("name", ""),
            "value": cookie.get("value", ""),
            "domain": cookie.get("domain", ""),
            "path": cookie.get("path", "/"),
            "sameSite": same_site,
            "secure": cookie.get("secure", False),
            "httpOnly": cookie.get("httpOnly", False),
        }
        # expires может быть необязательным, но если есть – передаём
        if "expires" in cookie:
            new_cookie["expires"] = cookie["expires"]
        if "expiry" in cookie:  # иногда называется expiry
            new_cookie["expires"] = cookie["expiry"]

        normalized.append(new_cookie)
    return normalized

def save_cookies(cookies):
    """Сохраняет нормализованные куки в файл."""
    normalized = normalize_cookies(cookies)
    with open(COOKIE_FILE, 'w') as f:
        json.dump(normalized, f, indent=2)
    logger.info(f"🍪 Сохранено {len(normalized)} кук в файл")

def load_cookies():
    """Загружает куки из файла и нормализует их."""
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, 'r') as f:
            cookies = json.load(f)
        normalized = normalize_cookies(cookies)
        logger.info(f"🍪 Загружено {len(normalized)} кук из файла")
        return normalized
    return None

def notify_admin(text):
    try:
        bot.send_message(ADMIN_ID, text)
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")

# ---------- ОСНОВНАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ СТАТУСА ----------
async def get_aternos_status():
    cookies = load_cookies()
    if not cookies:
        logger.warning("⚠️ Куки не найдены!")
        return None, "no_cookies"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-blink-features=AutomationControlled',
            ],
            timeout=30000
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        try:
            server_url = f"https://aternos.org/server/{SERVER_ADDRESS}"
            logger.info(f"🌐 Переход на {server_url}")

            # 1. Загружаем страницу (ждем только HTML)
            await page.goto(server_url, timeout=60000, wait_until='domcontentloaded')
            logger.info(f"✅ Страница загружена, URL: {page.url}")

            # 2. Ждем появления элемента со статусом (или другого ключевого элемента)
            try:
                await page.wait_for_selector('span.statuslabel-label', timeout=30000)
                logger.info("✅ Элемент статуса найден")
            except Exception as e:
                logger.warning(f"⚠️ Элемент статуса не найден: {e}")
                return None, "unknown"

            status_element = await page.query_selector('span.statuslabel-label')
            if status_element:
                status_text = await status_element.inner_text()
                status_text = status_text.strip().lower()
                logger.info(f"🔍 Статус: '{status_text}'")
                if 'онлайн' in status_text or 'online' in status_text:
                    return 'online', "ok"
                elif 'офлайн' in status_text or 'offline' in status_text:
                    return 'offline', "ok"
                else:
                    return status_text, "ok"
            else:
                return None, "unknown"

        except Exception as e:
            logger.error(f"❌ Ошибка при запросе: {e}")
            return None, "error"
        finally:
            await browser.close()
            import gc
            gc.collect()

def get_status_sync():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result, code = loop.run_until_complete(get_aternos_status())
        loop.close()
        return result, code
    except Exception as e:
        logger.error(f"Ошибка в синхронной обёртке: {e}")
        return None, "error"

# ---------- КОМАНДЫ ----------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, "Привет! Я бот для управления сервером Aternos.\n"
                          "/status – проверить статус\n"
                          "/update_cookies – обновить куки (только для админа)")

@bot.message_handler(commands=['status'])
def cmd_status(message):
    bot.reply_to(message, "⏳ Проверяю статус...")
    status, code = get_status_sync()

    if code == "no_cookies":
        bot.reply_to(message, "❌ Куки не найдены. Используйте /update_cookies для их загрузки.")
        notify_admin("⚠️ Куки не найдены. Загрузите новые через /update_cookies.")
        return
    elif code == "invalid_cookies":
        bot.reply_to(message, "❌ Куки истекли или невалидны. Обновите через /update_cookies.")
        notify_admin("⚠️ Куки Aternos истекли! Обновите их через /update_cookies.")
        return
    elif code == "unknown":
        bot.reply_to(message, "❌ Не удалось определить статус (возможно, изменилась структура страницы).")
        return
    elif code == "error":
        bot.reply_to(message, "❌ Ошибка при получении статуса. Проверьте логи.")
        return

    if status is None:
        bot.reply_to(message, "❌ Статус не определён.")
    else:
        bot.reply_to(message, f"🟢 Статус сервера: {status}")

@bot.message_handler(commands=['update_cookies'])
def cmd_update_cookies(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для этой команды.")
        return

    bot.reply_to(message, "📩 Отправьте файл cookies.json или вставьте JSON-текст с куками.")
    bot.register_next_step_handler(message, process_cookies_input)

def process_cookies_input(message):
    try:
        cookies = None
        if message.document:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            try:
                cookies = json.loads(downloaded_file.decode('utf-8'))
            except:
                bot.reply_to(message, "❌ Не удалось распарсить JSON из файла.")
                return
        elif message.text:
            try:
                cookies = json.loads(message.text)
            except:
                bot.reply_to(message, "❌ Не удалось распарсить JSON.")
                return
        else:
            bot.reply_to(message, "❌ Отправьте файл или JSON-текст.")
            return

        if not isinstance(cookies, list):
            bot.reply_to(message, "❌ Неверный формат: ожидается массив кук.")
            return

        save_cookies(cookies)
        bot.reply_to(message, f"✅ Куки успешно обновлены ({len(cookies)} шт.)! Теперь используйте /status.")
        logger.info("✅ Куки обновлены администратором")

    except Exception as e:
        logger.error(f"Ошибка при обновлении кук: {e}")
        bot.reply_to(message, f"❌ Ошибка: {e}")

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
        traceback.print_exc()
        sys.exit(1)