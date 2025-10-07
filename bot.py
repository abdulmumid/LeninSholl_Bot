import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup

from dotenv import load_dotenv

load_dotenv()  # загружаем переменные из .env




# ================= Настройки =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SPAM_INTERVAL = 2           
WARNING_LIMIT = 4
TEMP_BLOCK = 3600               

# ================= ID групп =================
hooligans_chat_id = -4854123470
ideas_chat_id     = -4882835148
problems_chat_id  = -4927386342

# ================= Файл данных =================
DATA_FILE = "data.json"
AUTO_SAVE_INTERVAL = 30  

# ================= Логирование =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")]
)

# ================= Клавиатуры =================
user_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📢 Сообщить о хулигане")],
        [KeyboardButton(text="💡 Предложить идею")],
        [KeyboardButton(text="⚠️ Сообщить о проблеме")]
    ],
    resize_keyboard=True
)

admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📣 Сделать рассылку")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="⚙️ Настройки бота")],
        [KeyboardButton(text="⛔ Заблокировать пользователя")],
        [KeyboardButton(text="✅ Разблокировать пользователя")]
    ],
    resize_keyboard=True
)

# ================= Хранилище (in-memory) =================
users = {}               
registered_users = set() 

# ================= Инициализация =================
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ================= Фильтр мата =================
BAD_ROOTS = [
    "хуй", "хуя", "хуе", "пизд", "пиздюк", "пизда", "ебл", "ебан", "ебат",
    "сука", "суки", "ебло", "мудак", "мудил", "гондон", "бляд", "блять", "уебок",
    "шлюх", "шлюп", "пидор", "пидр", "пидорок", "манда"
]

REPLACE_MAP = {
    "0": "о", "1": "и", "3": "е", "4": "а", "5": "с", "7": "т", "@": "а",
    "q": "к", "w": "в", "e": "е", "r": "р", "t": "т", "y": "у", "u": "у",
    "i": "и", "o": "о", "p": "р", "a": "а", "s": "с", "d": "д", "f": "ф",
    "g": "г", "h": "х", "j": "й", "k": "к", "l": "л", "z": "з", "x": "х",
    "c": "с", "v": "в", "b": "в", "n": "н", "m": "м"
}

def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.lower()
    text = "".join([REPLACE_MAP.get(ch, ch) for ch in text])
    text = re.sub(r"[^а-яa-zё\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(.)\1{2,}", r"\1", text)
    return text

BAD_PATTERNS = [re.compile(rf"\b{re.escape(root)}\b", re.IGNORECASE) for root in BAD_ROOTS]
BAD_SUB_PATTERNS = [re.compile(re.escape(root), re.IGNORECASE) for root in BAD_ROOTS]

def contains_profanity(text: Optional[str]) -> bool:
    norm = normalize_text(text)
    for p in BAD_PATTERNS + BAD_SUB_PATTERNS:
        if p.search(norm):
            return True
    return False

# ================= Сохранение / загрузка =================
def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if isinstance(dt, datetime) else None

def _iso_to_dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None

def save_data():
    """Сохраняем users и registered_users в DATA_FILE"""
    try:
        to_save = {
            "registered_users": list(registered_users),
            "users": {}
        }
        for uid, info in users.items():
            to_save["users"][str(uid)] = {
                "name": info.get("name"),
                "last_message": _dt_to_iso(info.get("last_message")),
                "warnings": info.get("warnings", 0),
                "temp_block": _dt_to_iso(info.get("temp_block")),
                "permanent_block": info.get("permanent_block", False),
                "awaiting_broadcast_message": info.get("awaiting_broadcast_message", False),
                "awaiting_block_user": info.get("awaiting_block_user", False),
                "awaiting_unblock": info.get("awaiting_unblock", False),
                "category": info.get("category"),
                "messages_count": info.get("messages_count", 0)
            }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)
        logging.info("Data saved to %s", DATA_FILE)
    except Exception as e:
        logging.exception("Failed to save data: %s", e)

def load_data():
    """Загружаем users и registered_users из DATA_FILE (если есть)"""
    if not os.path.exists(DATA_FILE):
        logging.info("No data file found, starting fresh")
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        regs = data.get("registered_users", [])
        for uid in regs:
            registered_users.add(int(uid))
        raw_users = data.get("users", {})
        for uid_str, info in raw_users.items():
            uid = int(uid_str)
            users[uid] = {
                "name": info.get("name", f"User{uid}"),
                "last_message": _iso_to_dt(info.get("last_message")),
                "warnings": int(info.get("warnings", 0)),
                "temp_block": _iso_to_dt(info.get("temp_block")),
                "permanent_block": bool(info.get("permanent_block", False)),
                "awaiting_broadcast_message": bool(info.get("awaiting_broadcast_message", False)),
                "awaiting_block_user": bool(info.get("awaiting_block_user", False)),
                "awaiting_unblock": bool(info.get("awaiting_unblock", False)),
                "category": info.get("category"),
                "messages_count": int(info.get("messages_count", 0))
            }
        logging.info("Loaded data from %s", DATA_FILE)
    except Exception as e:
        logging.exception("Failed to load data: %s", e)

async def autosave_loop():
    try:
        while True:
            await asyncio.sleep(AUTO_SAVE_INTERVAL)
            save_data()
    except asyncio.CancelledError:
        logging.info("Autosave task cancelled, saving one last time")
        save_data()
        raise

# ================= Вспомогательные =================
def init_user(user_id: int, full_name: str = ""):
    if user_id not in users:
        users[user_id] = {
            "name": full_name or f"User{user_id}",
            "last_message": None,
            "warnings": 0,
            "temp_block": None,
            "permanent_block": False,
            "awaiting_broadcast_message": False,
            "awaiting_block_user": False,
            "awaiting_unblock": False,
            "category": None,
            "messages_count": 0
        }
        logging.info("Initialized user %s (%s)", user_id, users[user_id]["name"])
    registered_users.add(user_id)

async def send_to_category_by_payload(sender_id: int, sender_name: str, text: str,
                                     photo, video, document, category: str, caption: str = "") -> bool:
    target_chat = {
        "hooligan": hooligans_chat_id,
        "idea": ideas_chat_id,
        "problem": problems_chat_id
    }.get(category)
    if not target_chat:
        logging.error("Invalid category: %s", category)
        return False
    info = f"От: {sender_name} (id: {sender_id})\nВремя: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
    try:
        if photo:
            await bot.send_photo(target_chat, photo[-1].file_id, caption=f"{info}\n\n{caption or text or '📎 Без текста'}")
        elif video:
            await bot.send_video(target_chat, video.file_id, caption=f"{info}\n\n{caption or text or '🎥 Без подписи'}")
        elif document:
            await bot.send_document(target_chat, document.file_id, caption=f"{info}\n\n{caption or text or '📄 Без подписи'}")
        else:
            await bot.send_message(target_chat, f"{info}\n\n{text or '📎 Без текста'}")
        return True
    except Exception as e:
        logging.exception("Failed to send to category %s: %s", category, e)
        return False

async def send_to_category(user_id: int, msg: Message, category: str):
    init_user(user_id, msg.from_user.full_name if msg.from_user else f"User{user_id}")
    text = msg.text or ""
    caption = msg.caption or ""
    success = await send_to_category_by_payload(
        sender_id=user_id,
        sender_name=(msg.from_user.full_name if msg.from_user else f"User{user_id}"),
        text=text,
        photo=msg.photo if msg.photo else None,
        video=msg.video if hasattr(msg, "video") else None,
        document=msg.document if hasattr(msg, "document") else None,
        category=category,
        caption=caption
    )
    if success:
        await msg.answer("Ваше сообщение отправлено Президенту и Администрации. Спасибо!")
    else:
        await msg.answer("Не удалось отправить сообщение. Сообщите администратору.")

# ================= Обработчики =================
@dp.message(Command("start"))
async def cmd_start(msg: Message):
    user_id = msg.from_user.id
    full_name = msg.from_user.full_name or msg.from_user.first_name or ""
    init_user(user_id, full_name)
    logging.info("/start from %s (%s). Is admin: %s", user_id, full_name, user_id == ADMIN_ID)
    if user_id == ADMIN_ID:
        await msg.answer("Привет, админ! Выберите действие:", reply_markup=admin_kb)
    else:
        welcome_text = (
            f"Привет, {msg.from_user.first_name or ''}! 👋\n\n"
            "Я — школьный бот, и я помогу тебе быстро сообщить о любых событиях в школе или поделиться идеями.\n\n"
            "📢 Сообщить о хулигане\n💡 Предложить идею\n⚠️ Сообщить о проблеме\n\n"
            "Просто нажми на соответствующую кнопку."
        )
        await msg.answer(welcome_text, reply_markup=user_kb)

@dp.message()
async def handle_all(msg: Message):
    if msg.from_user and msg.from_user.is_bot:
        return

    user_id = msg.from_user.id
    full_name = msg.from_user.full_name or msg.from_user.first_name or ""
    init_user(user_id, full_name)
    user = users[user_id]
    now = datetime.utcnow()
    text = (msg.text or msg.caption or "").strip()
    registered_users.add(user_id)

    logging.info("Message from %s: '%s' | state: warnings=%s perm_block=%s temp_block=%s",
                 user_id, text, user.get("warnings"), user.get("permanent_block"), user.get("temp_block"))

    # ---------- Блокировки ----------
    if user.get("permanent_block"):
        await msg.answer("Вы заблокированы навсегда за нарушения.")
        return
    if user.get("temp_block") and now < user["temp_block"]:
        remaining = int((user["temp_block"] - now).total_seconds())
        await msg.answer(f"Вы временно заблокированы. Осталось {remaining} секунд.")
        return

    # ---------- Антиспам ----------
    if user.get("last_message") and (now - user["last_message"]).total_seconds() < SPAM_INTERVAL:
        await msg.answer(f"Слишком много сообщений! Подождите {SPAM_INTERVAL} секунд.")
        return
    user["last_message"] = now
    user["messages_count"] = user.get("messages_count", 0) + 1

    # ---------- Фильтр мата ----------
    if contains_profanity(text):
        user["warnings"] += 1
        if user["warnings"] >= WARNING_LIMIT:
            user["temp_block"] = now + timedelta(seconds=TEMP_BLOCK)
            await msg.answer("Вы получили временную блокировку за мат (1 час).")
        else:
            await msg.answer(f"Предупреждение {user['warnings']}/{WARNING_LIMIT} за мат.")
        return

    # ---------- Админ: ожидаемые состояния ----------
    if user_id == ADMIN_ID:
        if user.get("awaiting_broadcast_message"):
            for uid in list(registered_users):
                if uid == ADMIN_ID:
                    continue
                try:
                    if msg.photo:
                        await bot.send_photo(uid, msg.photo[-1].file_id, caption=msg.caption or msg.text or "")
                    elif hasattr(msg, "video") and msg.video:
                        await bot.send_video(uid, msg.video.file_id, caption=msg.caption or msg.text or "")
                    elif hasattr(msg, "document") and msg.document:
                        await bot.send_document(uid, msg.document.file_id, caption=msg.caption or msg.text or "")
                    else:
                        await bot.send_message(uid, msg.text or "📎 Без текста")
                except Exception as e:
                    logging.warning("Broadcast failed to %s: %s", uid, e)
            await msg.answer("Рассылка выполнена.")
            user["awaiting_broadcast_message"] = False
            return

        # ожидание ID для блокировки
        if user.get("awaiting_block_user"):
            try:
                uid = int(text)
                if uid not in users:
                    init_user(uid, full_name=f"User{uid}")
                users[uid]["permanent_block"] = True
                await msg.answer(f"Пользователь {uid} заблокирован навсегда.")
                logging.info("Admin %s blocked %s", user_id, uid)
            except Exception as e:
                await msg.answer("Введите корректный ID пользователя.")
                logging.error("Invalid uid for block: %s (%s)", text, e)
            user["awaiting_block_user"] = False
            return

        # ожидание ID для разблокировки
        if user.get("awaiting_unblock"):
            try:
                uid = int(text)
                if uid not in users:
                    init_user(uid, full_name=f"User{uid}")
                users[uid]["permanent_block"] = False
                users[uid]["temp_block"] = None
                users[uid]["warnings"] = 0
                await msg.answer(f"Пользователь {uid} разблокирован.")
                logging.info("Admin %s unblocked %s", user_id, uid)
            except Exception as e:
                await msg.answer("Введите корректный ID пользователя.")
                logging.error("Invalid uid for unblock: %s (%s)", text, e)
            user["awaiting_unblock"] = False
            return

    # ---------- Кнопки (админ) ----------
    if user_id == ADMIN_ID:
        if text == "📣 Сделать рассылку":
            user["awaiting_broadcast_message"] = True
            await msg.answer("Отправьте текст или медиа для рассылки.")
            return
        if text == "📊 Статистика":
            total = len(registered_users)
            blocked = sum(1 for u in users.values() if u.get("permanent_block") or (u.get("temp_block") and now < u.get("temp_block")))
            top_users = sorted(users.items(), key=lambda kv: kv[1].get("messages_count", 0), reverse=True)[:5]
            top_text = "\n".join([f"{info['name']} ({uid}): {info.get('messages_count',0)}" for uid, info in top_users]) or "Пока нет активности."
            await msg.answer(f"📊 Статистика\nВсего пользователей: {total}\nЗаблокировано: {blocked}\n\nТоп активных:\n{top_text}")
            return
        if text == "⚙️ Настройки бота":
            await msg.answer("Настройки: антиспам, фильтр мата, категории. (in-memory + автосохранение в data.json)")
            return
        if text == "⛔ Заблокировать пользователя":
            user["awaiting_block_user"] = True
            await msg.answer("Отправьте ID пользователя для блокировки.")
            return
        if text == "✅ Разблокировать пользователя":
            user["awaiting_unblock"] = True
            await msg.answer("Отправьте ID пользователя для разблокировки.")
            return

    # ---------- Кнопки (пользователи) ----------
    if text == "📢 Сообщить о хулигане":
        user["category"] = "hooligan"
        await msg.answer("Опишите ситуацию.")
        return
    if text == "💡 Предложить идею":
        user["category"] = "idea"
        await msg.answer("Напишите вашу идею.")
        return
    if text == "⚠️ Сообщить о проблеме":
        user["category"] = "problem"
        await msg.answer("Опишите проблему.")
        return

    # ---------- Сообщения в категории ----------
    if user.get("category"):
        await send_to_category(user_id, msg, user["category"])
        user["category"] = None
        return

    # ---------- Нераспознанное ----------
    if user_id != ADMIN_ID:
        await msg.answer("Выберите категорию с помощью кнопок ниже.", reply_markup=user_kb)
    else:
        await msg.answer("Выберите действие с помощью кнопок.", reply_markup=admin_kb)

# ================= Старт / Завершение =================
async def main():
    load_data()
    autosave_task = asyncio.create_task(autosave_loop())
    me = await bot.get_me()
    logging.info("Bot @{0} (id: {1}) starting...".format(me.username, me.id))
    try:
        await dp.start_polling(bot)
    finally:
        autosave_task.cancel()
        try:
            await autosave_task
        except asyncio.CancelledError:
            pass
        save_data()
        logging.info("Bot stopped and data saved")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped by user (KeyboardInterrupt/SystemExit)")
        save_data()
