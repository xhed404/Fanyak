import os
import json
import random
from datetime import datetime
from collections import Counter
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler

CARD_FOLDER = "cards"
USER_DATA_FOLDER = "data"
WAIT_HOURS = 1

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

def load_user_data(user_id: str) -> dict:
    user_file = os.path.join(USER_DATA_FOLDER, f"{user_id}.json")
    if os.path.exists(user_file):
        with open(user_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "cards": [],
        "score": 0,
        "last_time": 0
    }

def save_user_data(user_id: str, data: dict):
    user_file = os.path.join(USER_DATA_FOLDER, f"{user_id}.json")
    os.makedirs(USER_DATA_FOLDER, exist_ok=True)
    with open(user_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
    if text not in ["фаня", "фаняк"]:
        return

    user = message.from_user
    user_id = str(user.id)

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

    limited_cards = [f for f in all_cards if "_лимитированная" in f.lower()]
    normal_cards = [f for f in all_cards if "_лимитированная" not in f.lower()]

    roll = random.random()
    chosen_file = random.choice(limited_cards if limited_cards and roll < 0.005 else normal_cards)

    name, rarity = parse_card_filename(chosen_file)
    rarity_cap = rarity.capitalize()
    emoji = RARITY_EMOJIS.get(rarity, "🎴")
    points = RARITY_POINTS.get(rarity, 0)

    already_has = any(card["name"] == name for card in user_data["cards"])
    if not already_has:
        user_data["cards"].append({"name": name, "rarity": rarity_cap})

    user_data["score"] += points
    user_data["last_time"] = now_ts
    save_user_data(user_id, user_data)

    caption = (
        f"📸 *{name}*\n"
        f"{emoji} Редкость: *{rarity_cap}*\n"
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

    rarity_counter = Counter(card["rarity"].lower() for card in cards)
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
        reply_text += f"{i}. {name} — {rarity}\n"

    update.message.reply_text(reply_text)

def main():
    TOKEN = "7726532835:AAFF55l7B4Pbcc3JmDSF6Ksqzhdh9G466uc"
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("mycards", mycards_command))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
