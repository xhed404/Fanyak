import os
import random
import sqlite3
from datetime import datetime
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler

CARD_FOLDER = "cards"
WAIT_HOURS = 0.15

RARITY_EMOJIS = {
    "обычная": "⭐️",
    "редкая": "💎",
    "мифическая": "🔥",
    "легендарная": "👑",
    "лимитированная": "🌀"
}

RARITY_POINTS = {
    "обычная": 5,
    "редкая": 10,
    "мифическая": 25,
    "легендарная": 50,
    "лимитированная": 100
}

RARITY_PROBABILITIES = {
    "обычная": 55,
    "редкая": 25,
    "мифическая": 17,
    "легендарная": 2.95,
    "лимитированная": 0.05
}

DB_FILE = "cards_bot.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            score INTEGER DEFAULT 0,
            last_time REAL DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS cards (
            card_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            rarity TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_cards (
            user_id TEXT,
            card_id INTEGER,
            count INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, card_id),
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(card_id) REFERENCES cards(card_id)
        )
    ''')
    conn.commit()
    conn.close()

def parse_card_filename(filename: str):
    base = os.path.splitext(filename)[0]
    if "_" not in base:
        return ("Неизвестная Фаня", "обычная")
    name_part, rarity = base.rsplit("_", 1)
    name = name_part.replace("-", " ").capitalize()
    return name, rarity.lower()

def get_user_data(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    if user is None:
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        user = {"user_id": user_id, "score": 0, "last_time": 0}
    else:
        user = dict(user)
    conn.close()
    return user

def update_user_score_and_time(user_id, score_delta, now_ts):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET score = score + ?, last_time = ? WHERE user_id = ?", (score_delta, now_ts, user_id))
    conn.commit()
    conn.close()

def get_card_id(name, rarity):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT card_id FROM cards WHERE name = ?", (name,))
    card = c.fetchone()
    if card:
        card_id = card["card_id"]
    else:
        c.execute("INSERT INTO cards (name, rarity) VALUES (?, ?)", (name, rarity))
        card_id = c.lastrowid
        conn.commit()
    conn.close()
    return card_id

def get_user_card(user_id, card_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT count FROM user_cards WHERE user_id = ? AND card_id = ?", (user_id, card_id))
    res = c.fetchone()
    conn.close()
    return res["count"] if res else None

def add_or_update_user_card(user_id, card_id):
    conn = get_db_connection()
    c = conn.cursor()
    count = get_user_card(user_id, card_id)
    if count is None:
        c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (?, ?, 1)", (user_id, card_id))
        is_new = True
    else:
        c.execute("UPDATE user_cards SET count = count + 1 WHERE user_id = ? AND card_id = ?", (user_id, card_id))
        is_new = False
    conn.commit()
    conn.close()
    return is_new

def handle_message(update: Update, context: CallbackContext):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip().lower()
    if text not in ["фаня", "фаняк"]:
        return

    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)
    now_ts = datetime.now().timestamp()

    if now_ts - user_data["last_time"] < WAIT_HOURS * 3600:
        remaining = WAIT_HOURS * 3600 - (now_ts - user_data["last_time"])
        hours, remainder = divmod(int(remaining), 3600)
        minutes, seconds = divmod(remainder, 60)
        msg = (
            "😔 Вы осмотрелись, но не увидели рядом Фаню.\n\n"
            f"🕐 Возвращайтесь через {hours} час {minutes} мин {seconds} сек."
        )
        message.reply_text(msg, reply_to_message_id=message.message_id)
        return

    all_cards = [f for f in os.listdir(CARD_FOLDER) if f.lower().endswith((".jpg", ".png"))]
    if not all_cards:
        message.reply_text("❌ Нет доступных карточек.", reply_to_message_id=message.message_id)
        return

    cards_by_rarity = {r: [] for r in RARITY_PROBABILITIES}
    for filename in all_cards:
        _, rarity = parse_card_filename(filename)
        rarity = rarity.lower()
        if rarity in cards_by_rarity:
            cards_by_rarity[rarity].append(filename)

    rarities = list(RARITY_PROBABILITIES.keys())
    weights = list(RARITY_PROBABILITIES.values())
    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]

    if cards_by_rarity[chosen_rarity]:
        chosen_file = random.choice(cards_by_rarity[chosen_rarity])
    else:
        available = [f for lst in cards_by_rarity.values() for f in lst]
        if not available:
            message.reply_text("❌ Нет доступных карточек.", reply_to_message_id=message.message_id)
            return
        chosen_file = random.choice(available)

    name, rarity = parse_card_filename(chosen_file)
    emoji = RARITY_EMOJIS.get(rarity, "🎴")
    points = RARITY_POINTS.get(rarity, 5)

    card_id = get_card_id(name, rarity)
    is_new = add_or_update_user_card(user_id, card_id)

    found_msg = "🎉 Новая карточка!" if is_new else "🔁 Повторная карточка!"

    update_user_score_and_time(user_id, points, now_ts)

    user_data = get_user_data(user_id)
    total_score = user_data["score"]

    caption = (
        f"📸 *{name}*\n"
        f"{emoji} Редкость: *{rarity.capitalize()}*\n"
        f"{found_msg}\n"
        f"🎁 +{points} очков  |  🧮 Всего: {total_score}"
    )

    with open(os.path.join(CARD_FOLDER, chosen_file), "rb") as img:
        context.bot.send_photo(
            chat_id=message.chat_id,
            photo=img,
            caption=caption,
            parse_mode='Markdown',
            reply_to_message_id=message.message_id
        )

def mycards_command(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT score FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    score = user["score"] if user else 0

    c.execute('''
        SELECT cards.name, cards.rarity, user_cards.count
        FROM user_cards
        JOIN cards ON user_cards.card_id = cards.card_id
        WHERE user_cards.user_id = ?
    ''', (user_id,))
    cards = c.fetchall()

    if not cards:
        update.message.reply_text("У вас пока нет карточек 😔", reply_to_message_id=update.message.message_id)
        conn.close()
        return

    rarity_counter = {}
    for card in cards:
        r = card["rarity"].lower()
        rarity_counter[r] = rarity_counter.get(r, 0) + card["count"]

    rarity_stats = "\n".join(
        f"{RARITY_EMOJIS.get(r, '🎴')} {r.capitalize()} — {count}"
        for r, count in rarity_counter.items()
    )

    reply_text = f"🎴 Ваши карточки (всего очков: {score}):\n\n{rarity_stats}\n\n"

    for i, card in enumerate(cards, 1):
        name = card["name"]
        rarity = card["rarity"].capitalize()
        count = card["count"]
        reply_text += f"{i}. {name} — {rarity} (x{count})\n"

    update.message.reply_text(reply_text, reply_to_message_id=update.message.message_id)
    conn.close()

def main():
    init_db()
    TOKEN = "7726532835:AAFF55l7B4Pbcc3JmDSF6Ksqzhdh9G466uc"
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("mycards", mycards_command))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()




