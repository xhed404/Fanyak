import os
import random
import psycopg2
from psycopg2 import pool
from datetime import datetime
from collections import Counter
from telegram import Update, ParseMode
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler

CARD_FOLDER = "cards"
WAIT_HOURS = 2
CUBE_WAIT_SECONDS = 15 * 60

RARITY_EMOJIS = {
    "обычная": "⭐️",
    "редкая": "💎",
    "мифическая": "🔥",
    "легендарная": "👑",
    "лимитированная": "💀",
}

RARITY_POINTS = {
    "обычная": 5,
    "редкая": 10,
    "мифическая": 25,
    "легендарная": 50,
    "лимитированная": 100,
}

RARITY_COINS = {
    "обычная": 2,
    "редкая": 5,
    "мифическая": 15,
    "легендарная": 30,
    "лимитированная": 50,
}

RARITY_PROBABILITIES = {
    "обычная": 55,
    "редкая": 25,
    "мифическая": 17,
    "легендарная": 2.95,
    "лимитированная": 4,
}

CHEST_COSTS = {
    "обычный": 20,
    "редкий": 50,
    "легендарный": 100,
}

CHEST_RARITY_PROBS = {
    "обычный": {
        "обычная": 75,
        "редкая": 20,
        "мифическая": 7,
        "легендарная": 10,
        "лимитированная": 8,
    },
    "редкий": {
        "обычная": 5,
        "редкая": 10,
        "мифическая": 15,
        "легендарная": 35,
        "лимитированная": 15,
    },
    "легендарный": {
        "обычная": 1,
        "редкая": 2,
        "мифическая": 15,
        "легендарная": 65,
        "лимитированная": 25,
    },
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
                coins INTEGER NOT NULL DEFAULT 0,
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
        cur.execute("SELECT score, coins, last_time, last_cube_time, username FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            score, coins, last_time, last_cube_time, username = row
        else:
            score, coins, last_time, last_cube_time, username = 0, 0, 0, 0, ""
            cur.execute(
                "INSERT INTO users(user_id, username, score, coins, last_time, last_cube_time) VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, username, score, coins, last_time, last_cube_time)
            )
            conn.commit()

        cur.execute("SELECT name, rarity, count FROM cards WHERE user_id = %s", (user_id,))
        cards = [{"name": r[0], "rarity": r[1], "count": r[2]} for r in cur.fetchall()]
    finally:
        cur.close()
        release_connection(conn)

    return {"score": score, "coins": coins, "last_time": last_time, "last_cube_time": last_cube_time, "cards": cards, "username": username}

def save_user_data(user_id: str, data: dict, card_to_update: dict = None, username: str = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE users SET score=%s, coins=%s, last_time=%s, last_cube_time=%s, username=%s WHERE user_id=%s
        """, (
            data.get("score", 0),
            data.get("coins", 0),
            data.get("last_time", 0),
            data.get("last_cube_time", 0),
            username,
            user_id
        ))

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
    return name, rarity

def handle_message(update: Update, context: CallbackContext):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip().lower()
    user = message.from_user
    user_id = str(user.id)
    username = user.username or ""

    if text.startswith("сундук"):
        parts = text.split()
        if len(parts) != 2 or parts[1] not in CHEST_COSTS:
            message.reply_text(f"Используйте: сундук [обычный(20 монет) | редкий(50 монет) | легендарный(100 монет) ]")
            return

        chest_type = parts[1]
        open_chest(update, context, user_id, username, chest_type)
        return

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

    already_has = any(card["name"] == name for card in user_data["cards"])

    points = RARITY_POINTS.get(rarity, 5)
    coins_earned = 0
    
    if not already_has:
        coins_earned = RARITY_COINS.get(rarity, 0)
        card_status = "🆕 <b>Новая карточка!</b>"
    else:
        card_status = "♻️ <b>Повторная карточка</b> (монеты не начислены)"
    
    user_data["score"] += points
    user_data["coins"] += coins_earned

    user_data["last_time"] = now_ts

    save_user_data(user_id, user_data, card_to_update={"name": name, "rarity": rarity, "count": 1}, username=username)

    coins_text = f"💰 +{coins_earned} монет" if coins_earned > 0 else ""
    message.reply_photo(
        photo=open(os.path.join(CARD_FOLDER, chosen_file), "rb"),
        caption=(
            f"{emoji} Вы нашли: {name}\n"
            f"⭐️ Очки: +{points}\n"
            f"{coins_text}\n"
            f"{card_status}\n\n"
            f"💎 Ваш баланс: {user_data['score']} очков, {user_data['coins']} монет"
        ),
        parse_mode=ParseMode.HTML
    )


def open_chest(update: Update, context: CallbackContext, user_id: str, username: str, chest_type: str):
    user_data = load_user_data(user_id)

    cost = CHEST_COSTS[chest_type]
    if user_data["coins"] < cost:
        update.message.reply_text(f"❌ Недостаточно монет для открытия {chest_type} сундука. Требуется {cost} монет.")
        return

    user_data["coins"] -= cost

    probs = CHEST_RARITY_PROBS[chest_type]
    rarities = list(probs.keys())
    weights = list(probs.values())
    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]

    all_cards = [f for f in os.listdir(CARD_FOLDER) if f.lower().endswith((".jpg", ".png"))]
    cards_by_rarity = {r: [] for r in RARITY_PROBABILITIES}
    for filename in all_cards:
        _, rarity = parse_card_filename(filename)
        if rarity in cards_by_rarity:
            cards_by_rarity[rarity].append(filename)

    if not cards_by_rarity.get(chosen_rarity):
        update.message.reply_text("❌ Ошибка при выборе карты из сундука.")
        return

    chosen_file = random.choice(cards_by_rarity[chosen_rarity])
    name, rarity = parse_card_filename(chosen_file)
    emoji = RARITY_EMOJIS.get(rarity, "🎴")

    already_has = any(card["name"] == name for card in user_data["cards"])

    points = 0
    coins_earned = 0
    if not already_has:
        points = RARITY_POINTS.get(rarity, 5)
        coins_earned = RARITY_COINS.get(rarity, 0)
        card_status = "🆕 <b>Новая карточка!</b>"
    else:
        points = RARITY_POINTS.get(rarity, 5)
        coins_earned = 0
        card_status = "♻️ <b>Повторная карточка</b> (начислены только очки)"

    user_data["score"] += points
    user_data["coins"] += coins_earned


    save_user_data(user_id, user_data, card_to_update={"name": name, "rarity": rarity, "count": 1}, username=username)

    coins_text = f"💰 +{coins_earned} монет" if coins_earned > 0 else ""
    update.message.reply_photo(
        photo=open(os.path.join(CARD_FOLDER, chosen_file), "rb"),
        caption=(
            f"{emoji} Вы открыли {chest_type} сундук и получили:\n"
            f"{name}\n"
            f"⭐️ Очки: +{points}\n"
            f"{coins_text}\n"
            f"{card_status}\n\n"
            f"💎 Ваш баланс: {user_data['score']} очков, {user_data['coins']} монет"
        ),
        parse_mode=ParseMode.HTML
    )

def open_chest(update: Update, context: CallbackContext, user_id: str, username: str, chest_type: str):
    user_data = load_user_data(user_id)

    cost = CHEST_COSTS[chest_type]
    if user_data["coins"] < cost:
        update.message.reply_text(f"❌ Недостаточно монет для открытия {chest_type} сундука. Требуется {cost} монет.")
        return

    user_data["coins"] -= cost

    probs = CHEST_RARITY_PROBS[chest_type]
    rarities = list(probs.keys())
    weights = list(probs.values())
    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]

    all_cards = [f for f in os.listdir(CARD_FOLDER) if f.lower().endswith((".jpg", ".png"))]
    cards_by_rarity = {r: [] for r in RARITY_PROBABILITIES}
    for filename in all_cards:
        _, rarity = parse_card_filename(filename)
        if rarity in cards_by_rarity:
            cards_by_rarity[rarity].append(filename)

    if not cards_by_rarity.get(chosen_rarity):
        update.message.reply_text("❌ Ошибка при выборе карты из сундука.")
        return

    chosen_file = random.choice(cards_by_rarity[chosen_rarity])
    name, rarity = parse_card_filename(chosen_file)
    emoji = RARITY_EMOJIS.get(rarity, "🎴")

    points = RARITY_POINTS.get(rarity, 5)
    coins_earned = RARITY_COINS.get(rarity, 0)

    already_has = any(card["name"] == name for card in user_data["cards"])

    points = 0
    coins_earned = 0
    if not already_has:
        points = RARITY_POINTS.get(rarity, 5)
        coins_earned = RARITY_COINS.get(rarity, 0)
        user_data["score"] += points
        user_data["coins"] += coins_earned
        card_status = "🆕 <b>Новая карточка!</b>"
    else:
        card_status = "♻️ <b>Повторная карточка</b> (очки и монеты не начислены)"

    save_user_data(user_id, user_data, card_to_update={"name": name, "rarity": rarity, "count": 1}, username=username)

    update.message.reply_photo(
        photo=open(os.path.join(CARD_FOLDER, chosen_file), "rb"),
        caption=(
            f"🎉 <b>Поздравляем!</b> Вы открыли <b>{chest_type} сундук</b> и получили:\n\n"
            f"🔹 <b>Карта:</b> {emoji} <b>{name}</b>\n"
            f"🎖 <b>Редкость:</b> <b>{rarity}</b>\n"
            f"⭐️ <b>Очки:</b> +<b>{points}</b>\n"
            f"💰 <b>Монеты:</b> +<b>{coins_earned}</b>\n"
            f"{card_status}\n\n"
            f"📦 <b>Ваш баланс:</b> 💎 <b>{user_data['score']}</b> очков | 🪙 <b>{user_data['coins']}</b> монет\n"
            f"✨✨✨"
        ),
        parse_mode=ParseMode.HTML
    )

def handle_dice_result(context: CallbackContext):
    job = context.job
    data = job.context
    user_id = data["user_id"]
    chat_id = data["chat_id"]
    amount = data["amount"]
    username = data["username"]
    dice_value = data["dice_value"]

    user_data = load_user_data(user_id)
    win = False
    if dice_value > 3:
        user_data["score"] += amount
        win = True
    else:
        user_data["score"] -= amount
        if user_data["score"] < 0:
            user_data["score"] = 0

    user_data["last_cube_time"] = datetime.now().timestamp()
    save_user_data(user_id, user_data, username=username)

    result_text = (
        f"🎲 Выпало: {dice_value}\n"
        f"{'Вы выиграли' if win else 'Вы проиграли'} {amount} очков!\n"
        f"💎 Текущий баланс: {user_data['score']} очков, {user_data['coins']} монет"
    )

    context.bot.send_message(chat_id=chat_id, text=result_text)

def mycards(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    user_data = load_user_data(user_id)

    if not user_data["cards"]:
        update.message.reply_text("У вас пока нет карточек.")
        return

    lines = []
    for card in user_data["cards"]:
        emoji = RARITY_EMOJIS.get(card["rarity"], "")
        lines.append(f"{emoji} {card['name']} — {card['rarity'].capitalize()} (x{card['count']})")

    text = (
        "🎴 <b>Ваши карточки:</b>\n" +
        "\n".join(lines) +
        "\n\n" +
        f"💎 <b>Очки:</b> {user_data['score']} | 👑 <b>Монеты:</b> {user_data['coins']}"
    )

    update.message.reply_text(text, parse_mode=ParseMode.HTML)


def top(update: Update, context: CallbackContext):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT username, score FROM users ORDER BY score DESC LIMIT 10")
        rows = cur.fetchall()
    finally:
        cur.close()
        release_connection(conn)

    if not rows:
        update.message.reply_text("Топ игроков пока пуст.")
        return

    lines = []
    for i, (username, score) in enumerate(rows, 1):
        name_display = username if username else "Аноним"
        lines.append(f"{i}. {name_display} — {score} очков")

    text = "🏆 Топ игроков по очкам:\n" + "\n".join(lines)
    update.message.reply_text(text)

def main():
    init_connection_pool()
    init_db()

    updater = Updater("7726532835:AAFF55l7B4Pbcc3JmDSF6Ksqzhdh9G466uc", use_context=True)
    dp = updater.dispatcher

    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(CommandHandler("mycards", mycards))
    dp.add_handler(CommandHandler("top", top))
    
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
