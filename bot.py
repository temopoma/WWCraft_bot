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
    """Запускает браузер, логинится и возвращает статус сервера с расширенной отладкой."""
    async with async_playwright() as p:
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
            ],
            timeout=30000
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        try:
            # Загружаем сохранённые cookies
            if os.path.exists(COOKIE_FILE):
                import json
                with open(COOKIE_FILE, 'r') as f:
                    cookies = json.load(f)
                await context.add_cookies(cookies)
                logger.info("🍪 Загружены сохранённые cookies")

            server_url = f"https://aternos.org/server/{SERVER_ADDRESS}"
            logger.info(f"🌐 Переход на {server_url}")
            await page.goto(server_url, timeout=60000, wait_until='domcontentloaded')
            await page.wait_for_timeout(3000)

            # Проверяем логин
            if "login" in page.url or "signin" in page.url:
                logger.info("🔑 Требуется логин")
                try:
                    await page.fill('input[name="username"]', ATERNOS_USERNAME, timeout=5000)
                    await page.fill('input[name="password"]', ATERNOS_PASSWORD, timeout=5000)
                    await page.click('button[type="submit"]', timeout=5000)
                    await page.wait_for_timeout(5000)
                    cookies = await context.cookies()
                    import json
                    with open(COOKIE_FILE, 'w') as f:
                        json.dump(cookies, f, indent=2)
                    logger.info("🍪 Cookies сохранены")
                except Exception as e:
                    logger.error(f"Ошибка при логине: {e}")
                    raise

            # ---------- ОТЛАДКА: Сохраняем HTML страницы ----------
            html_content = await page.content()
            with open("page_debug.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info("📄 HTML-код страницы сохранён в page_debug.html")

            # ---------- ОТЛАДКА: Ищем элементы с ключевыми классами ----------
            # Получаем все элементы с классами, содержащими статус-слова
            elements_info = await page.evaluate('''() => {
                const results = [];
                const all = document.querySelectorAll('*');
                const keywords = ['status', 'online', 'offline', 'server', 'state', 'info'];
                for (const el of all) {
                    if (el.className && typeof el.className === 'string') {
                        const classes = el.className.split(' ');
                        for (const cls of classes) {
                            if (keywords.some(k => cls.toLowerCase().includes(k))) {
                                results.push({
                                    tag: el.tagName,
                                    className: cls,
                                    text: el.innerText ? el.innerText.trim().slice(0, 50) : ''
                                });
                            }
                        }
                    }
                }
                return results;
            }''')
            logger.info(f"🔍 Найдены элементы с ключевыми классами: {elements_info}")

            # ---------- ПОИСК СТАТУСА ----------
            status = None

            # 1. Ищем элемент с текстом "online" или "offline" (без учёта регистра)
            try:
                online_elem = await page.query_selector('text=online')
                offline_elem = await page.query_selector('text=offline')
                if online_elem:
                    status = 'online'
                elif offline_elem:
                    status = 'offline'
            except:
                pass

            # 2. Ищем по классам
            if status is None:
                for cls in ['status', 'server-status', 'state', 'server-state']:
                    elem = await page.query_selector(f'.{cls}')
                    if elem:
                        text = await elem.inner_text()
                        text = text.strip().lower()
                        if 'online' in text:
                            status = 'online'
                            break
                        elif 'offline' in text:
                            status = 'offline'
                            break
                        else:
                            status = text
                            break

            # 3. Ищем кнопку запуска/остановки (самый надёжный способ)
            if status is None:
                start_btn = await page.query_selector('button[data-action="start"]')
                stop_btn = await page.query_selector('button[data-action="stop"]')
                if stop_btn:
                    status = 'online'
                elif start_btn:
                    status = 'offline'
                else:
                    # Пробуем другие варианты кнопок
                    start_btn_any = await page.query_selector('button:has-text("Start")')
                    stop_btn_any = await page.query_selector('button:has-text("Stop")')
                    if stop_btn_any:
                        status = 'online'
                    elif start_btn_any:
                        status = 'offline'

            # 4. Ищем атрибут data-status
            if status is None:
                status_elem = await page.query_selector('[data-status]')
                if status_elem:
                    data_status = await status_elem.get_attribute('data-status')
                    if data_status:
                        status = data_status.lower()

            # 5. Если всё ещё неизвестно, берём текст всей страницы и ищем подстроки
            if status is None:
                body_text = await page.inner_text('body')
                body_text_lower = body_text.lower()
                if 'online' in body_text_lower:
                    status = 'online'
                elif 'offline' in body_text_lower:
                    status = 'offline'
                else:
                    status = 'unknown'

            logger.info(f"📊 Определён статус: {status}")
            return status

        except Exception as e:
            logger.error(f"Ошибка при получении статуса: {e}")
            # Сохраняем скриншот
            try:
                screenshot = await page.screenshot()
                with open("error_screenshot.png", "wb") as f:
                    f.write(screenshot)
                logger.info("📸 Скриншот сохранён как error_screenshot.png")
            except:
                pass
            raise
        finally:
            await browser.close()
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