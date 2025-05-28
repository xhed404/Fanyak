import os
import random
import psycopg2
from psycopg2 import pool
from datetime import datetime
from collections import Counter
from telegram import Update, ParseMode
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler
from telegram import ParseMode

CARD_FOLDER = "cards"
WAIT_HOURS = 2
CUBE_WAIT_SECONDS = 15 * 60  

RARITY_EMOJIS = {
    "обычная": "⭐️",
    "редкая": "💎",
    "мифическая": "🔥",
    "легендарная": "👑",
    "лимитираванная" : "",
}

RARITY_POINTS = {
    "обычная": 5,
    "редкая": 10,
    "мифическая": 25,
    "легендарная": 50,
    "лимитированная" : 100,
}

RARITY_PROBABILITIES = {
    "обычная": 55,
    "редкая": 25,
    "мифическая": 17,
    "легендарная": 2.95,
    "лимитированная" : 4,
}

DB_PARAMS = {
    'dbname': 'postgres',
    'user': 'postgres.ohjvqejdhqdvmpinreng',
    'password': 'Mateoloko17+',
    'host': 'aws-0-eu-north-1.pooler.supabase.com',
    'port': 6543
}


conn_pool = None

def init_connection_pool():
    global conn_pool
    if conn_pool is None:
        conn_pool = pool.SimpleConnectionPool(1, 10, **DB_PARAMS)

def get_connection():
    global conn_pool
    if conn_pool is None:
        init_connection_pool()
    return conn_pool.getconn()

def release_connection(conn):
    if conn_pool and conn:
        conn_pool.putconn(conn)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                score INTEGER NOT NULL DEFAULT 0,
                last_time DOUBLE PRECISION NOT NULL DEFAULT 0,
                last_cube_time DOUBLE PRECISION NOT NULL DEFAULT 0
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                user_id TEXT,
                name TEXT,
                rarity TEXT,
                count INTEGER DEFAULT 1,
                PRIMARY KEY (user_id, name),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            );
        """)
        conn.commit()
    finally:
        cur.close()
        release_connection(conn)

def load_user_data(user_id: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT score, last_time, last_cube_time, username FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            score, last_time, last_cube_time, username = row
        else:
            score, last_time, last_cube_time, username = 0, 0, 0, ""
            cur.execute(
                "INSERT INTO users(user_id, username, score, last_time, last_cube_time) VALUES (%s, %s, %s, %s, %s)",
                (user_id, username, score, last_time, last_cube_time)
            )
            conn.commit()

        cur.execute("SELECT name, rarity, count FROM cards WHERE user_id = %s", (user_id,))
        cards = [{"name": r[0], "rarity": r[1], "count": r[2]} for r in cur.fetchall()]
    finally:
        cur.close()
        release_connection(conn)

    return {"score": score, "last_time": last_time, "last_cube_time": last_cube_time, "cards": cards, "username": username}

def save_user_data(user_id: str, data: dict, card_to_update: dict = None, username: str = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE users SET score=%s, last_time=%s, last_cube_time=%s, username=%s WHERE user_id=%s
        """, (data["score"], data["last_time"], data.get("last_cube_time", 0), username, user_id))

        if card_to_update:
            cur.execute("""
                INSERT INTO cards (user_id, name, rarity, count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, name) DO UPDATE SET count = cards.count + EXCLUDED.count
            """, (user_id, card_to_update["name"], card_to_update["rarity"].lower(), card_to_update["count"]))
        conn.commit()
    finally:
        cur.close()
        release_connection(conn)

def parse_card_filename(filename: str) -> tuple[str, str]:
    base = os.path.splitext(filename)[0]
    if "_" not in base:
        return ("Неизвестная Фаня", "обычная")
    name_part, rarity = base.rsplit("_", 1)
    name = name_part.replace("-", " ").capitalize()
    rarity = rarity.lower()

    if rarity == "ультра-легендарная" or rarity == "ультра_легендарная":
        rarity = "ультра-легендарная"
    return name, rarity

def handle_message(update: Update, context: CallbackContext):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip().lower()
    user = message.from_user
    user_id = str(user.id)
    username = user.username or ""

    if text.startswith("кубы фаня"):
        try:
            amount = int(text.split()[-1])
        except:
            message.reply_text("⚠️ Формат: 'кубы фаня сумма'")
            return

        user_data = load_user_data(user_id)
        now = datetime.now().timestamp()

        if now - user_data.get("last_cube_time", 0) < CUBE_WAIT_SECONDS:
            remaining = CUBE_WAIT_SECONDS - (now - user_data.get("last_cube_time", 0))
            mins, secs = divmod(int(remaining), 60)
            message.reply_text(f"⏳ Подождите {mins} мин {secs} сек перед следующим броском.")
            return

        if amount <= 0 or amount > user_data["score"]:
            message.reply_text("❌ Недопустимая сумма для ставки.")
            return

        dice_msg = message.reply_dice()
        dice_value = dice_msg.dice.value if dice_msg.dice else random.randint(1, 6)

        context.job_queue.run_once(
            callback=handle_dice_result,
            when=3,
            context={"user_id": user_id, "chat_id": message.chat_id, "amount": amount, "username": username, "dice_value": dice_value}
        )
        return

    if text not in ["фаня", "фаняк"]:
        return

    user_data = load_user_data(user_id)
    last_time = user_data.get("last_time", 0)
    now_ts = datetime.now().timestamp()

    if now_ts - last_time < WAIT_HOURS * 3600:
        remaining = WAIT_HOURS * 3600 - (now_ts - last_time)
        hours, remainder = divmod(int(remaining), 3600)
        minutes, seconds = divmod(remainder, 60)
        msg = (
            "😔 Вы уже искали рядом Фаню.\n\n"
            f"🕐 Возвращайтесь через {hours} час {minutes} мин {seconds} сек."
        )
        message.reply_text(msg)
        return

    all_cards = [f for f in os.listdir(CARD_FOLDER) if f.lower().endswith((".jpg", ".png"))]
    if not all_cards:
        message.reply_text("❌ Нет доступных карточек.")
        return

    cards_by_rarity = {r: [] for r in RARITY_PROBABILITIES}
    for filename in all_cards:
        _, rarity = parse_card_filename(filename)
        if rarity in cards_by_rarity:
            cards_by_rarity[rarity].append(filename)

    rarities = list(RARITY_PROBABILITIES.keys())
    weights = list(RARITY_PROBABILITIES.values())
    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]

    chosen_file = random.choice(cards_by_rarity.get(chosen_rarity, all_cards))
    name, rarity = parse_card_filename(chosen_file)
    emoji = RARITY_EMOJIS.get(rarity, "🎴")

    points = RARITY_POINTS.get(rarity, 5)
    already_has = any(card["name"] == name for card in user_data["cards"])

    found_msg = "🔁 Повторная карточка! Будут начислены только очки!" if already_has else "🎉 Новая карточка!"
    user_data["score"] += points
    user_data["last_time"] = now_ts

    save_user_data(user_id, user_data, {"name": name, "rarity": rarity.capitalize(), "count": 1}, username)

    caption = (
        f"📸 *{name}*\n"
        f"{emoji} Редкость: *{rarity.capitalize()}*\n"
        f"{found_msg}\n"
        f"🎁 +{points} очков  |  🧮 Всего: {user_data['score']}"
    )

    with open(os.path.join(CARD_FOLDER, chosen_file), "rb") as img:
        context.bot.send_photo(chat_id=message.chat_id, photo=img, caption=caption, parse_mode=ParseMode.MARKDOWN)

def handle_dice_result(context: CallbackContext):
    job = context.job
    data = job.context
    user_id = data["user_id"]
    chat_id = data["chat_id"]
    amount = data["amount"]
    username = data["username"]
    dice_value = data["dice_value"]

    user_data = load_user_data(user_id)
    score = user_data["score"]
    if amount > score:
        context.bot.send_message(chat_id=chat_id, text="❌ Недостаточно очков для ставки.")
        return

    if dice_value in [4, 5, 6]:
        score += amount
        result_msg = f"🎉 Выпало {dice_value}! Вы выиграли {amount} очков."
    else:
        score -= amount
        result_msg = f"😞 Выпало {dice_value}. Вы проиграли {amount} очков."

    user_data["score"] = max(score, 0)
    user_data["last_cube_time"] = datetime.now().timestamp()
    save_user_data(user_id, user_data, username=username)

    context.bot.send_message(chat_id=chat_id, text=result_msg)

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Привет!")

def top(update: Update, context: CallbackContext):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, username, score FROM users ORDER BY score DESC LIMIT 10;")
        rows = cur.fetchall()
        
        if not rows:
            update.message.reply_text("Пока нет игроков с очками.")
            return

        msg_lines = ["🏆 Топ игроков по очкам:"]
        for i, (user_id, username, score) in enumerate(rows, 1):
            if username:
                # Создание гиперссылки на профиль пользователя
                display_name = f'<a href="tg://user?id={user_id}">{username}</a>'
            else:
                display_name = "Пользователь без имени"

            msg_lines.append(f"{i}. {display_name} — {score} очков")

        update.message.reply_text("\n".join(msg_lines), parse_mode=ParseMode.HTML)
    finally:
        cur.close()
        release_connection(conn)


def mycards(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    user_data = load_user_data(user_id)

    score = user_data.get("score", 0)
    cards = user_data.get("cards", [])

    msg_lines = [f"💰 Ваши очки: {score}\n"]

    if not cards:
        msg_lines.append("У вас пока нет карточек.")
    else:
        msg_lines.append("🎴 Ваши карточки:")
        for card in cards:
            count = card.get("count", 1)
            msg_lines.append(f"- {card['name']} (редкость: {card['rarity'].capitalize()}), количество: {count}")

    update.message.reply_text("\n".join(msg_lines), parse_mode=ParseMode.MARKDOWN)


def main():
    init_connection_pool()
    init_db()

    TOKEN = "7726532835:AAFF55l7B4Pbcc3JmDSF6Ksqzhdh9G466uc"
    updater = Updater(TOKEN)

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("mycards", mycards))
    dp.add_handler(CommandHandler("top", top))
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()



