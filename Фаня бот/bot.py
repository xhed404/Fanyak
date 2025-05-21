import os
import json
import random
from datetime import datetime
from collections import Counter
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler

CARD_FOLDER = "cards"
USER_DATA_FOLDER = "data"
WAIT_HOURS = 0.4

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

GAMES = {
    "казино": "🎰",
    "футбол": "⚽",
    "баскетбол": "🏀"
}

GAME_COST = 5
GAME_WIN_REWARD = 20

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
    user_id = str(message.from_user.id)
    user_data = load_user_data(user_id)

    # Обработка игр с эмодзи
    for keyword, emoji in GAMES.items():
        if keyword in text:
            if user_data["score"] < GAME_COST:
                message.reply_text("😢 Недостаточно очков для игры.")
                return

            user_data["score"] -= GAME_COST
            save_user_data(user_id, user_data)

            message.reply_text(emoji)

            if random.random() < 0.5:
                user_data["score"] += GAME_WIN_REWARD
                save_user_data(user_id, user_data)
                message.reply_text(f"🎉 Победа! +{GAME_WIN_REWARD} очков! Теперь у вас {user_data['score']} очков.")
            else:
                message.reply_text(f"😞 Проигрыш! Осталось {user_data['score']} очков.")
            return  # прерываем, чтобы не обрабатывать дальше

    if text not in ["фаня", "фаняк"]:
        return

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
    rarity_cap = rarity.capitalize()
    emoji = RARITY_EMOJIS.get(rarity, "🎴")
    base_points = RARITY_POINTS.get(rarity, 0)

    already_has = any(card["name"] == name for card in user_data["cards"])
    if already_has:
        points = int(base_points * 1)
        found_msg = "🔁 Повторная карточка!"
    else:
        points = base_points
        user_data["cards"].append({"name": name, "rarity": rarity_cap})
        found_msg = "🎉 Новая карточка!"

    user_data["score"] += points
    user_data["last_time"] = now_ts
    save_user_data(user_id, user_data)

    caption = (
        f"📸 *{name}*\n"
        f"{emoji} Редкость: *{rarity_cap}*\n"
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
