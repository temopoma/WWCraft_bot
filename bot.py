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

# ---------- ЛОГИРОВАНИЕ (для файла) ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot_errors.log", encoding="utf-8"),
        # Убираем StreamHandler, чтобы не дублировать, будем использовать print
    ]
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)

COOKIE_FILE = "aternos_cookies.json"

# ---------- ОСНОВНАЯ ФУНКЦИЯ ----------
async def get_aternos_status():
    print("🚀 Запуск get_aternos_status")
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
            # Загружаем cookies
            if os.path.exists(COOKIE_FILE):
                with open(COOKIE_FILE, 'r') as f:
                    cookies = json.load(f)
                await context.add_cookies(cookies)
                print("🍪 Cookies загружены")

            server_url = f"https://aternos.org/server/{SERVER_ADDRESS}"
            print(f"🌐 Переход на {server_url}")
            await page.goto(server_url, timeout=60000, wait_until='domcontentloaded')
            print(f"✅ Страница загружена, URL: {page.url}")

            # Ждём 5 секунд для полной отрисовки
            await page.wait_for_timeout(5000)

            # Проверяем логин
            if "login" in page.url or "signin" in page.url:
                print("🔑 Требуется логин")
                await page.fill('input[name="username"]', ATERNOS_USERNAME)
                await page.fill('input[name="password"]', ATERNOS_PASSWORD)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(5000)
                cookies = await context.cookies()
                with open(COOKIE_FILE, 'w') as f:
                    json.dump(cookies, f, indent=2)
                print("🍪 Cookies сохранены после логина")
                print(f"✅ После логина URL: {page.url}")
                await page.wait_for_timeout(3000)

            # ---------- СОХРАНЯЕМ HTML СТРАНИЦЫ ДЛЯ АНАЛИЗА ----------
            html_content = await page.content()
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            print("📄 HTML-код страницы сохранён в debug_page.html")

            # ---------- СОХРАНЯЕМ СКРИНШОТ ----------
            screenshot = await page.screenshot()
            with open("debug_screenshot.png", "wb") as f:
                f.write(screenshot)
            print("📸 Скриншот сохранён в debug_screenshot.png")

            # ---------- ИЩЕМ ВСЕ ЭЛЕМЕНТЫ С КЛАССАМИ, СОДЕРЖАЩИМИ "status" или "label" ----------
            elements_info = await page.evaluate('''() => {
                const results = [];
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    if (el.className && typeof el.className === 'string') {
                        const classes = el.className.split(' ');
                        for (const cls of classes) {
                            if (cls.toLowerCase().includes('status') || cls.toLowerCase().includes('label')) {
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
            print("🔍 Найдены элементы с классами, содержащими 'status' или 'label':")
            for item in elements_info:
                print(f"   {item}")

            # ---------- ПОИСК СТАТУСА ----------
            status = None
            # 1. Ищем span.statuslabel-label
            try:
                element = await page.query_selector('span.statuslabel-label')
                if element:
                    text = await element.inner_text()
                    text = text.strip().lower()
                    print(f"🔍 span.statuslabel-label найден, текст: '{text}'")
                    if 'онлайн' in text or 'online' in text:
                        status = 'online'
                    elif 'офлайн' in text or 'offline' in text:
                        status = 'offline'
                    else:
                        status = text
                else:
                    print("⚠️ span.statuslabel-label не найден")
            except Exception as e:
                print(f"Ошибка при поиске span.statuslabel-label: {e}")

            # 2. Если не нашли, ищем другие селекторы
            if status is None:
                selectors = ['.status-label', '.server-status', '.status', '.online', '.offline', '[data-status]', '.statuslabel']
                for sel in selectors:
                    try:
                        elem = await page.query_selector(sel)
                        if elem:
                            text = await elem.inner_text()
                            text = text.strip().lower()
                            print(f"🔍 Найден селектор {sel}, текст: '{text}'")
                            if 'онлайн' in text or 'online' in text:
                                status = 'online'
                                break
                            elif 'офлайн' in text or 'offline' in text:
                                status = 'offline'
                                break
                            else:
                                status = text
                                break
                    except:
                        continue

            # 3. По кнопкам Start/Stop
            if status is None:
                start_btn = await page.query_selector('button[data-action="start"]')
                stop_btn = await page.query_selector('button[data-action="stop"]')
                if stop_btn:
                    status = 'online'
                    print("✅ Статус определён по кнопке Stop")
                elif start_btn:
                    status = 'offline'
                    print("✅ Статус определён по кнопке Start")

            # 4. По тексту всей страницы
            if status is None:
                body_text = await page.inner_text('body')
                body_lower = body_text.lower()
                if 'онлайн' in body_lower or 'online' in body_lower:
                    status = 'online'
                    print("✅ Статус определён по тексту страницы (онлайн)")
                elif 'офлайн' in body_lower or 'offline' in body_lower:
                    status = 'offline'
                    print("✅ Статус определён по тексту страницы (офлайн)")

            if status is None:
                status = 'unknown'
                print("⚠️ Статус не удалось определить")

            print(f"📊 Итоговый статус: {status}")
            return status

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            try:
                screenshot = await page.screenshot()
                with open("error_screenshot.png", "wb") as f:
                    f.write(screenshot)
                print("📸 Скриншот ошибки сохранён как error_screenshot.png")
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