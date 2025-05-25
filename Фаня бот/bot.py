import os
import random
import psycopg2
from psycopg2 import pool
from datetime import datetime
from collections import Counter
from telegram import Update, ParseMode
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler

CARD_FOLDER = "cards"
WAIT_HOURS = 0.5
CUBE_WAIT_SECONDS = 15 * 60 

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
    if conn_pool and conn:
        conn_pool.putconn(conn)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            create table if not exists users (
                user_id text primary key,
                username text,
                score integer not null default 0,
                last_time double precision not null default 0,
                last_cube_time double precision not null default 0
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
        cur.execute("select score, last_time, last_cube_time from users where user_id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            score, last_time, last_cube_time = row
        else:
            score, last_time, last_cube_time = 0, 0, 0
            cur.execute(
                "insert into users(user_id, username, score, last_time, last_cube_time) values (%s, %s, %s, %s, %s)",
                (user_id, "", score, last_time, last_cube_time)
            )
            conn.commit()

        cur.execute("select name, rarity, count from cards where user_id = %s", (user_id,))
        cards = [{"name": r[0], "rarity": r[1], "count": r[2]} for r in cur.fetchall()]
    finally:
        cur.close()
        release_connection(conn)

    return {"score": score, "last_time": last_time, "last_cube_time": last_cube_time, "cards": cards}

def save_user_data(user_id: str, data: dict, card_to_update: dict = None, username: str = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            update users set score=%s, last_time=%s, last_cube_time=%s, username=%s where user_id=%s
        """, (data["score"], data["last_time"], data.get("last_cube_time", 0), username, user_id))

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
        context.job_queue.run_once(
            callback=handle_dice_result,
            when=3,
            context={"user_id": user_id, "chat_id": message.chat_id, "amount": amount, "username": username, "dice_msg_id": dice_msg.message_id}
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

    found_msg = "🔁 Повторная карточка!" if already_has else "🎉 Новая карточка!"
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
        context.bot.send_photo(chat_id=message.chat_id, photo=img, caption=caption, parse_mode='Markdown')

def handle_dice_result(context: CallbackContext):
    job = context.job
    data = job.context
    user_id = data["user_id"]
    chat_id = data["chat_id"]
    amount = data["amount"]
    username = data["username"]

    updates = context.bot.get_chat(chat_id).get_message(data["dice_msg_id"])
    dice_value = updates.dice.value if updates and updates.dice else 1

    user_data = load_user_data(user_id)
    now = datetime.now().timestamp()
    result = ""

    if dice_value > 3:
        win = int(amount * 1.5)
        user_data["score"] += win
        result = f"🎉 Победа! Выпало {dice_value}.\nВы выиграли {win} очков!"
    else:
        user_data["score"] -= amount
        result = f"💀 Проигрыш! Выпало {dice_value}.\nВы потеряли {amount} очков."

    user_data["last_cube_time"] = now
    save_user_data(user_id, user_data, username=username)
    context.bot.send_message(chat_id=chat_id, text=f"{result}\n🧮 Новый счёт: {user_data['score']}")

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

    reply_text = f"🎴 Ваши карточки (всего очков: {score}):\n\n{rarity_stats}\n\n"
    for i, card in enumerate(cards, 1):
        reply_text += f"{i}. {card['name']} — {card['rarity']} (x{card['count']})\n"

    update.message.reply_text(reply_text)

def top_command(update: Update, context: CallbackContext):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("select user_id, username, score from users order by score desc limit 5")
        rows = cur.fetchall()
    finally:
        cur.close()
        release_connection(conn)

    text = "🏆 Топ 5 игроков:\n\n"
    for i, (uid, uname, score) in enumerate(rows, 1):
        name = f"@{uname}" if uname else f"[user](tg://user?id={uid})"
        text += f"{i}. {name} — {score} очков\n"

    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

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


