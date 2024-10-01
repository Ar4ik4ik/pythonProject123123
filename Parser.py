import asyncio
import os
import re
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events

# Загрузка конфигурации из .env файла
load_dotenv(dotenv_path='0')

# Проверка, что файл загружается
print("Loaded .env file")

# Получение переменных из .env
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')

# Проверка значений
print(f"API_ID: {api_id}")
print(f"API_HASH: {api_hash}")

if not api_id or not api_hash:
    raise ValueError("API ID или API HASH не заданы")

client = TelegramClient('session_name', api_id, api_hash)

# Глобальные переменные
processed_users = set()
delay_between_messages = int(os.getenv('DELAY_BETWEEN_MESSAGES', 2))  # Задержка между сообщениями
PROCESSED_USERS_FILE = "processed_users.txt"
parsing_active = False
sending_active = False
message_counter = 0
CHAT_ID = int(os.getenv('CHAT_ID', 0))  # ID группы из .env файла
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))  # ID админа для отчетов и уведомлений

# Логирование в консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# --- Функции для работы с пользователями ---
def save_processed_users():
    """Сохраняем ID всех обработанных пользователей в файл"""
    logger.info("Saving processed users to file.")
    with open(PROCESSED_USERS_FILE, "w") as file:
        file.write("\n".join(map(str, processed_users)))
    logger.info("Processed users saved.")

def load_processed_users():
    """Загружаем ID обработанных пользователей из файла"""
    if os.path.exists(PROCESSED_USERS_FILE):
        logger.info("Loading processed users from file.")
        with open(PROCESSED_USERS_FILE, "r") as file:
            users = set(map(int, file.read().strip().split()))
        logger.info(f"Loaded {len(users)} processed users.")
        return users
    return set()

# --- Функции для Telegram ----
async def check_chat_existence(chat_id):
    try:
        chat = await client.get_entity(chat_id)
        logger.info(f"Chat found: {chat.title} (ID: {chat.id})")
        return chat
    except Exception as e:
        logger.error(f"Error getting chat: {e}")
        return None

async def send_message_with_retry(user_id, message, retries=3):
    delay = 1
    for attempt in range(retries):
        try:
            logger.info(f"Sending message to user {user_id}")
            await client.send_message(user_id, message)
            return True
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения, попытка {attempt + 1}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
    logger.error(f"Failed to send message to {user_id} after {retries} attempts.")
    return False

# --- Обработчики команд ---
@client.on(events.NewMessage(pattern='/check'))
async def check_command(event):
    logger.info("Received /check command.")
    await event.respond('Бот запущен и готов к работе!')

@client.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    global sending_active
    logger.info("Received /start command.")
    if not parsing_active:
        await event.respond('Сначала начните парсинг командой /parse.')
        return

    if not sending_active:
        sending_active = True
        await start_sending_messages()
        await event.respond('Отправка сообщений начата!')
    else:
        await event.respond('Отправка сообщений уже активна.')

@client.on(events.NewMessage(pattern='/stop'))
async def stop_command(event):
    global parsing_active, sending_active
    logger.info("Received /stop command.")
    parsing_active = False
    sending_active = False
    await event.respond('Парсинг и отправка сообщений остановлены.')

@client.on(events.NewMessage(pattern='/reset'))
async def reset_processed_users_command(event):
    global processed_users
    logger.info("Received /reset command.")
    processed_users.clear()
    save_processed_users()
    await event.respond('Список обработанных пользователей успешно сброшен.')

@client.on(events.NewMessage(chats=CHAT_ID))
async def handler(event):
    global message_counter
    if not parsing_active:
        return

    message_counter += 1
    message_text = event.message.message

    # Используем регулярное выражение для поиска всех вариантов ключевого слова
    keyword_found = re.search(r'ООБИ-24091\w*', message_text) is not None
    result = "Ключевое слово найдено" if keyword_found else "Ключевое слово не найдено"

    logger.info(f"[#{message_counter}] [Message: \"{message_text}\"] [Result: {result}]")

    for attempt in range(3):
        try:
            if keyword_found:  # Проверяем ключевое слово
                user = await event.get_sender()  # Получаем информацию о пользователе

                # Проверяем, не был ли пользователь уже обработан
                if user.id not in processed_users:
                    logger.info(f"Найден новый пользователь: {user.username or user.id}")
                    processed_users.add(user.id)
                    save_processed_users()  # Сохраняем обновленный список обработанных пользователей
                else:
                    logger.info(f"Пользователь {user.username or user.id} уже обработан, пропускаем его.")
            break  # Выходим из цикла при успешной обработке
        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения, попытка {attempt + 1}: {e}")
            if attempt == 2:
                logger.error(f"Не удалось обработать сообщение после 3 попыток.")
            await asyncio.sleep(1)  # Задержка перед повторной попыткой

# --- Основные функции ---
async def fetch_and_process_old_messages():
    global message_counter
    logger.info("Fetching old messages.")
    async for message in client.iter_messages(CHAT_ID):
        message_counter += 1
        message_text = message.message

        # Проверка, что message_text не является None
        if message_text is None:
            logger.info(f"#{message_counter} [Нет текста в сообщении]")
            continue  # Переходим к следующему сообщению

        keyword_found = 'ООБИ-24091' in message_text
        result = "Ключевое слово найдено" if keyword_found else "Ключевое слово не найдено"
        logger.info(f"[#{message_counter}] [Message: \"{message_text}\"] [Result: {result}]")

        for attempt in range(3):
            try:
                if keyword_found:  # Проверяем ключевое слово
                    user = await message.get_sender()  # Получаем информацию о пользователе

                    # Проверяем, не был ли пользователь уже обработан
                    if user.id not in processed_users:
                        logger.info(f"Найден новый пользователь: {user.username or user.id}")
                        processed_users.add(user.id)
                        save_processed_users()  # Сохраняем обновленный список обработанных пользователей
                    else:
                        logger.info(f"Пользователь {user.username or user.id} уже обработан, пропускаем его.")
                break  # Выходим из цикла при успешной обработке
            except Exception as e:
                logger.error(f"Ошибка при обработке сообщения, попытка {attempt + 1}: {e}")
                if attempt == 2:
                    logger.error(f"Не удалось обработать сообщение после 3 попыток.")
                await asyncio.sleep(1)  # Задержка перед повторной попыткой

async def start_sending_messages():
    global sending_active
    if not sending_active:
        return

    logger.info("Starting to send messages.")

    # Загружаем список пользователей, которым уже отправлены сообщения, чтобы не дублировать
    global processed_users
    processed_users = load_processed_users()
    logger.info(f"Loaded {len(processed_users)} users for messaging.")

    # Открываем список пользователей, собранных на текущий момент
    for user_id in processed_users:
        if not sending_active:
            logger.info("Stopping sending messages due to /stop command.")
            break
        success = await send_message_with_retry(user_id, '') # Сообщение для отправки
        if not success:
            logger.error(f"Failed to send message to user {user_id}")
        await asyncio.sleep(delay_between_messages)

async def run_cli():
    global parsing_active, sending_active
    while True:
        command = input("Введите команду (/parse, /start, /stop, /check, /reset, /exit): ").strip()
        logger.info(f"Received command: {command}")

        if command == '/parse':
            if not parsing_active:
                parsing_active = True
                logger.info("Парсинг запущен.")
                await fetch_and_process_old_messages()  # Обработка старых сообщений
            else:
                logger.info("Парсинг уже активен.")
        elif command == '/start':
            if parsing_active:
                if not sending_active:
                    await start_sending_messages()
                else:
                    logger.info("Отправка сообщений уже активна.")
            else:
                logger.info("Сначала начните парсинг командой /parse.")
        elif command == '/stop':
            if parsing_active or sending_active:
                parsing_active = False
                sending_active = False
                logger.info("Парсинг и отправка сообщений остановлены.")
            else:
                logger.info("Ни парсинг, ни отправка сообщений не активны.")
        elif command == '/check':
            status = "активен" if parsing_active else "не активен"
            sending_status = "активна" if sending_active else "не активна"
            logger.info(f"Парсинг {status}. Отправка сообщений {sending_status}.")
        elif command == '/reset':
            global processed_users
            processed_users.clear()
            save_processed_users()
            logger.info("Список обработанных пользователей успешно сброшен.")
        elif command == '/exit':
            logger.info("Завершение работы...")
            break
        else:
            logger.info("Неизвестная команда. Попробуйте еще раз.")

    # Завершение работы
    await client.disconnect()
    logger.info("Клиент отключен.")

async def main():
    await client.start()
    logger.info("Клиент запущен.")

    chat = await check_chat_existence(CHAT_ID)
    if chat is None:
        logger.error("Invalid chat ID or bot does not have access to the chat.")
        return

    # Загружаем обработанных пользователей из файла перед запуском
    global processed_users
    processed_users = load_processed_users()
    logger.info(f"Processed users loaded: {len(processed_users)}")

    # Запуск CLI интерфейса в отдельном потоке
    loop = asyncio.get_event_loop()
    loop.create_task(run_cli())

    await client.run_until_disconnected()

with client:
    client.loop.run_until_complete(main())
