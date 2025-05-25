import os
import random
import psycopg2
from psycopg2 import pool
from datetime import datetime
from collections import Counter
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler

CARD_FOLDER = "cards"
WAIT_HOURS = 0.5

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
    global conn_pool
    if conn_pool is not None and conn is not None:
        conn_pool.putconn(conn)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
        create table if not exists users (
            user_id text primary key,
            score integer not null default 0,
            last_time double precision not null default 0
        );
        """)
        cur.execute("""
        create table if not exists cards (
            user_id text,
            name text,
            rarity text,
            count integer default 1,
            primary key (user_id, name),
            foreign key (user_id) references users (user_id)
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
        cur.execute("select score, last_time from users where user_id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            score, last_time = row
        else:
            score, last_time = 0, 0
            cur.execute("insert into users(user_id, score, last_time) values (%s, %s, %s)", (user_id, score, last_time))
            conn.commit()

        cur.execute("select name, rarity, count from cards where user_id = %s", (user_id,))
        cards = [{"name": r[0], "rarity": r[1], "count": r[2]} for r in cur.fetchall()]
    finally:
        cur.close()
        release_connection(conn)
    return {"score": score, "last_time": last_time, "cards": cards}

def save_user_data(user_id: str, data: dict, card_to_update: dict = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("update users set score=%s, last_time=%s where user_id=%s",
                    (data["score"], data["last_time"], user_id))

        if card_to_update:
            cur.execute("""
            insert into cards (user_id, name, rarity, count)
            values (%s, %s, %s, %s)
            on conflict (user_id, name) do update set count = cards.count + EXCLUDED.count
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
    return name, rarity.lower()

def handle_message(update: Update, context: CallbackContext):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip().lower()
    user = message.from_user
    user_id = str(user.id)

    # Кубы фаня <сумма очков>
    if text.startswith("кубы фаня"):
        parts = text.split()
        if len(parts) != 3 or not parts[2].isdigit():
            message.reply_text("⚠️ Используйте: кубы фаня <сумма очков>, например: `кубы фаня 10`", parse_mode='Markdown')
            return

        bet = int(parts[2])
        if bet <= 0:
            message.reply_text("⚠️ Ставка должна быть больше нуля.")
            return

        user_data = load_user_data(user_id)
        if bet > user_data["score"]:
            message.reply_text(f"😕 У вас недостаточно очков. Ваш счёт: {user_data['score']}")
            return

        roll = random.randint(1, 6)
        win = roll > 3

        if win:
            gained = int(bet * 1.5)
            user_data["score"] += gained
            result = f"🎲 Выпало: *{roll}* — вы *выиграли*! +{gained} очков."
        else:
            user_data["score"] -= bet
            result = f"🎲 Выпало: *{roll}* — вы *проиграли*. -{bet} очков."

        save_user_data(user_id, user_data)
        message.reply_text(
            f"{result}\n💰 Ваш новый счёт: {user_data['score']}",
            parse_mode='Markdown'
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
            "😔 Вы осмотрелись, но не увидели рядом Фаню.\n\n"
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
            message.reply_text("❌ Нет доступных карточек.")
            return
        chosen_file = random.choice(available)

    name, rarity = parse_card_filename(chosen_file)
    emoji = RARITY_EMOJIS.get(rarity, "🎴")

    points = RARITY_POINTS.get(rarity, 5)
    already_has = any(card["name"] == name for card in user_data["cards"])

    found_msg = "🔁 Повторная карточка!" if already_has else "🎉 Новая карточка!"
    user_data["score"] += points
    user_data["last_time"] = now_ts

    save_user_data(user_id, user_data, {"name": name, "rarity": rarity.capitalize(), "count": 1})

    caption = (
        f"📸 *{name}*\n"
        f"{emoji} Редкость: *{rarity.capitalize()}*\n"
        f"{found_msg}\n"
        f"🎁 +{points} очков  |  🧮 Всего: {user_data['score']}"
    )

    with open(os.path.join(CARD_FOLDER, chosen_file), "rb") as img:
        context.bot.send_photo(
            chat_id=message.chat_id,
            photo=img,
            caption=caption,
            parse_mode='Markdown'
        )

def mycards_command(update: Update, context: CallbackContext):
    user = update.message.from_user
    user_id = str(user.id)

    user_data = load_user_data(user_id)
    cards = user_data.get("cards", [])
    score = user_data.get("score", 0)

    if not cards:
        update.message.reply_text("У вас пока нет карточек 😔")
        return

    rarity_counter = Counter()
    for card in cards:
        rarity_counter[card["rarity"].lower()] += card["count"]

    rarity_stats = "\n".join(
        f"{RARITY_EMOJIS.get(r, '🎴')} {r.capitalize()} — {count}"
        for r, count in rarity_counter.items()
    )

    reply_text = (
        f"🎴 Ваши карточки (всего очков: {score}):\n\n"
        f"{rarity_stats}\n\n"
    )

    for i, card in enumerate(cards, 1):
        name = card.get("name", "Неизвестная Фаня")
        rarity = card.get("rarity", "Обычная")
        count = card.get("count", 1)
        reply_text += f"{i}. {name} — {rarity} (x{count})\n"

    update.message.reply_text(reply_text)

def top_command(update: Update, context: CallbackContext):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, score FROM users ORDER BY score DESC LIMIT 5")
        top_users = cur.fetchall()
    finally:
        cur.close()
        release_connection(conn)

    if not top_users:
        update.message.reply_text("Пока что никто не набрал очков 😔")
        return

    msg = "🏆 *Топ 5 пользователей по очкам:*\n\n"
    for i, (user_id, score) in enumerate(top_users, 1):
        msg += f"{i}. ID: `{user_id}` — {score} очков\n"

    update.message.reply_text(msg, parse_mode='Markdown')

def main():
    TOKEN = "7726532835:AAFF55l7B4Pbcc3JmDSF6Ksqzhdh9G466uc"  
    init_connection_pool()
    init_db()

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("mycards", mycards_command))
    dp.add_handler(CommandHandler("top", top_command))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
