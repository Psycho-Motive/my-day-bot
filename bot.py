"""
МОЙ ДЕНЬ — Telegram Bot v2.0
Личный дневник с красивым оформлением
"""

import os
import sqlite3
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

TOKEN = os.environ.get("BOT_TOKEN", "")
DB_PATH = "diary.db"
DEFAULT_TZ = "Europe/Amsterdam"

# ═══════════════════════════════════════════
#  КОНСТАНТЫ
# ═══════════════════════════════════════════
MOODS = {
    "😄": "Отличное",
    "🙂": "Хорошее",
    "😐": "Нормальное",
    "😔": "Грустное",
    "😤": "Тяжёлое"
}

MONTHS_RU = ["","Января","Февраля","Марта","Апреля","Мая","Июня",
             "Июля","Августа","Сентября","Октября","Ноября","Декабря"]

DAYS_RU = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]

QUOTES = [
    "💫 Каждый день — это новая возможность стать лучше.",
    "🌱 Маленькие шаги каждый день ведут к большим результатам.",
    "⚡ Делай сегодня то, что другие откладывают на завтра.",
    "🎯 Фокус на процессе — результат придёт сам.",
    "🌊 Жизнь — это то, что происходит прямо сейчас.",
    "🔥 Энергия туда, где внимание.",
    "🦋 Изменения начинаются с одного шага.",
    "🌟 Ты способен на больше, чем думаешь.",
    "🧭 Каждое утро — новый старт.",
    "💎 Дисциплина важнее мотивации.",
]

MORNING_GREETINGS = [
    "☀️ Доброе утро! Новый день — новые возможности.",
    "🌅 С добрым утром! Пусть день будет продуктивным.",
    "☕ Доброе утро! Начни день с маленькой победы.",
    "🌤 Привет! Сегодня отличный день чтобы сделать что-то важное.",
]

# Авто-категории по ключевым словам
CATEGORIES = {
    "🌅": ["проснулся", "встал", "подъём", "проснулась"],
    "🚗": ["выехал", "поехал", "в дороге", "пробки", "доехал", "выехала"],
    "💼": ["работа", "работал", "встреча", "задача", "проект", "офис", "клиент", "звонок"],
    "🛒": ["магазин", "купил", "купила", "супермаркет", "аптека", "заехал"],
    "🏠": ["дома", "пришёл", "вернулся", "пришла", "вернулась"],
    "🍽️": ["поел", "поужинал", "пообедал", "позавтракал", "кафе", "ресторан", "еда"],
    "💪": ["спортзал", "тренировка", "бегал", "качалка", "фитнес", "зарядка"],
    "😴": ["лёг", "сплю", "ложусь", "отдыхаю", "устал", "устала"],
    "📚": ["читал", "книга", "учился", "курс", "урок"],
    "👨‍👩‍👧": ["семья", "дети", "жена", "муж", "родители", "друзья"],
}

def get_emoji_for_note(text):
    text_lower = text.lower()
    for emoji, keywords in CATEGORIES.items():
        if any(kw in text_lower for kw in keywords):
            return emoji
    return "📝"

# ═══════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════
def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            first_name TEXT,
            timezone   TEXT DEFAULT 'Europe/Amsterdam',
            notify_h   INTEGER DEFAULT 21,
            notify_m   INTEGER DEFAULT 0,
            streak     INTEGER DEFAULT 0,
            last_active TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            date       TEXT,
            text       TEXT,
            emoji      TEXT DEFAULT '📝',
            ts         TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ratings (
            user_id    INTEGER,
            date       TEXT,
            stars      INTEGER DEFAULT 0,
            mood       TEXT DEFAULT '',
            PRIMARY KEY (user_id, date)
        );
        """)

def get_user(user_id):
    with sqlite3.connect(DB_PATH) as con:
        return con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def upsert_user(user_id, username, first_name=""):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO users(user_id, username, first_name) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name
        """, (user_id, username, first_name))

def add_note(user_id, date_str, text, emoji):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO notes(user_id,date,text,emoji) VALUES(?,?,?,?)",
            (user_id, date_str, text, emoji)
        )

def get_notes(user_id, date_str):
    with sqlite3.connect(DB_PATH) as con:
        return con.execute(
            "SELECT text, ts, emoji FROM notes WHERE user_id=? AND date=? ORDER BY ts",
            (user_id, date_str)
        ).fetchall()

def delete_notes(user_id, date_str):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM notes WHERE user_id=? AND date=?", (user_id, date_str))

def set_rating(user_id, date_str, stars=None, mood=None):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO ratings(user_id,date,stars,mood) VALUES(?,?,?,?)
            ON CONFLICT(user_id,date) DO UPDATE SET
              stars = CASE WHEN ? IS NOT NULL THEN ? ELSE stars END,
              mood  = CASE WHEN ? IS NOT NULL THEN ? ELSE mood  END
        """, (user_id, date_str, stars or 0, mood or '',
              stars, stars, mood, mood))

def get_rating(user_id, date_str):
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT stars, mood FROM ratings WHERE user_id=? AND date=?",
            (user_id, date_str)
        ).fetchone()
    return row or (0, '')

def get_history(user_id, limit=7):
    with sqlite3.connect(DB_PATH) as con:
        return con.execute("""
            SELECT r.date, r.stars, r.mood, COUNT(n.id) as note_count
            FROM ratings r
            LEFT JOIN notes n ON n.user_id=r.user_id AND n.date=r.date
            WHERE r.user_id=?
            GROUP BY r.date ORDER BY r.date DESC LIMIT ?
        """, (user_id, limit)).fetchall()

def get_streak(user_id):
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute("""
            SELECT DISTINCT date FROM notes
            WHERE user_id=? ORDER BY date DESC LIMIT 30
        """, (user_id,)).fetchall()
    if not rows:
        return 0
    streak = 0
    today = datetime.now(ZoneInfo(DEFAULT_TZ)).date()
    for i, (date_str,) in enumerate(rows):
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        if (today - d).days == i:
            streak += 1
        else:
            break
    return streak

def user_today(user_id):
    u = get_user(user_id)
    tz_name = u[2] if u and u[2] else DEFAULT_TZ
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)
    return datetime.now(tz).date()

def fmt_date(date_obj):
    day_name = DAYS_RU[date_obj.weekday()]
    return f"{date_obj.day} {MONTHS_RU[date_obj.month]} {date_obj.year} · {day_name}"

def day_of_year(dt):
    return dt.timetuple().tm_yday

# ═══════════════════════════════════════════
#  KEYBOARDS
# ═══════════════════════════════════════════
def kb_rating(date_str, current_stars=0, current_mood=''):
    stars_row = []
    for i in range(1, 6):
        label = "⭐" if i <= current_stars else "✩"
        stars_row.append(InlineKeyboardButton(label, callback_data=f"star:{date_str}:{i}"))

    mood_row = []
    for emoji in MOODS:
        label = f"›{emoji}‹" if emoji == current_mood else emoji
        mood_row.append(InlineKeyboardButton(label, callback_data=f"mood:{date_str}:{emoji}"))

    return InlineKeyboardMarkup([stars_row, mood_row])

def kb_main():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📓 Сегодня", callback_data="cmd:today"),
            InlineKeyboardButton("📅 Вчера", callback_data="cmd:yesterday"),
        ],
        [
            InlineKeyboardButton("📊 История 7 дней", callback_data="cmd:history"),
            InlineKeyboardButton("🏆 Моя статистика", callback_data="cmd:stats"),
        ],
        [
            InlineKeyboardButton("🗑 Очистить сегодня", callback_data="cmd:clear"),
        ],
    ])

# ═══════════════════════════════════════════
#  ФОРМАТИРОВАНИЕ
# ═══════════════════════════════════════════
def format_day(user_id, date_obj, title=""):
    date_str = date_obj.strftime("%Y-%m-%d")
    notes = get_notes(user_id, date_str)
    stars, mood = get_rating(user_id, date_str)
    doy = day_of_year(date_obj)
    total = 366 if date_obj.year % 4 == 0 else 365
    pct = round(doy / total * 100)

    # Заголовок
    header = (
        f"╔══════════════════╗\n"
        f"║  📓  МОЙ ДЕНЬ  ║\n"
        f"╚══════════════════╝\n\n"
        f"📅 *{fmt_date(date_obj)}*\n"
        f"📄 Страница `{doy}` из `{total}` · {pct}% года\n"
    )

    # Разделитель
    sep = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"

    # Записи
    if not notes:
        body = f"\n{sep}📭 *Записей пока нет*\nПросто напиши мне что происходит!\n"
    else:
        body = f"\n{sep}📝 *Записи дня:*\n\n"
        for text, ts, emoji in notes:
            try:
                t = datetime.fromisoformat(ts).strftime("%H:%M")
            except Exception:
                t = "--:--"
            body += f"{emoji} `{t}` {text}\n"

    # Оценка и настроение
    rating_block = f"\n{sep}"
    if stars:
        filled = "⭐" * stars
        empty = "✩" * (5 - stars)
        rating_block += f"🌟 *Оценка дня:* {filled}{empty}\n"
    else:
        rating_block += "🌟 *Оценка:* не поставлена\n"

    if mood:
        rating_block += f"{mood} *Настроение:* {MOODS.get(mood, '')}\n"
    else:
        rating_block += "💭 *Настроение:* не выбрано\n"

    # Цитата дня
    quote = QUOTES[doy % len(QUOTES)]
    quote_block = f"\n{sep}_{quote}_"

    return header + body + rating_block + quote_block

def format_history(user_id):
    rows = get_history(user_id, 7)
    if not rows:
        return (
            "╔══════════════════╗\n"
            "║  📊  ИСТОРИЯ  ║\n"
            "╚══════════════════╝\n\n"
            "📭 История пуста.\nНачни записывать свой день прямо сейчас!"
        )

    text = (
        "╔══════════════════╗\n"
        "║  📊  ИСТОРИЯ  ║\n"
        "╚══════════════════╝\n\n"
    )

    for date_str, stars, mood, note_count in rows:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            label = f"{d.day} {MONTHS_RU[d.month]}"
            day_name = DAYS_RU[d.weekday()]
        except Exception:
            label = date_str
            day_name = ""

        star_s = "⭐" * stars + "✩" * (5 - stars) if stars else "✩✩✩✩✩"
        mood_s = mood if mood else "–"
        notes_s = f"📝 {note_count}" if note_count else "📭 0"

        text += (
            f"┌─────────────────────\n"
            f"│ 📅 *{label}* · {day_name}\n"
            f"│ {star_s} {mood_s}\n"
            f"│ {notes_s} записей\n"
            f"└─────────────────────\n"
        )

    return text

def format_stats(user_id):
    streak = get_streak(user_id)
    history = get_history(user_id, 30)

    total_days = len(history)
    total_notes = sum(row[3] for row in history)
    avg_stars = 0
    rated_days = [(r[1]) for r in history if r[1] > 0]
    if rated_days:
        avg_stars = round(sum(rated_days) / len(rated_days), 1)

    mood_counts = {}
    for row in history:
        if row[2]:
            mood_counts[row[2]] = mood_counts.get(row[2], 0) + 1
    top_mood = max(mood_counts, key=mood_counts.get) if mood_counts else "–"

    streak_emoji = "🔥" if streak >= 3 else "📅"

    return (
        "╔══════════════════╗\n"
        "║  🏆  СТАТИСТИКА  ║\n"
        "╚══════════════════╝\n\n"
        f"{streak_emoji} *Серия дней подряд:* `{streak}` дней\n"
        f"📅 *Всего дней в дневнике:* `{total_days}`\n"
        f"📝 *Всего записей:* `{total_notes}`\n"
        f"⭐ *Средняя оценка:* `{avg_stars}` из 5\n"
        f"💭 *Частое настроение:* {top_mood}\n\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"_{random.choice(QUOTES)}_"
    )

# ═══════════════════════════════════════════
#  HANDLERS
# ═══════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username or "", user.first_name or "")

    text = (
        "╔══════════════════╗\n"
        "║  📓  МОЙ ДЕНЬ  ║\n"
        "╚══════════════════╝\n\n"
        f"👋 Привет, *{user.first_name}*\\!\n\n"
        "Я твой личный дневник дня\\.\n"
        "Просто пиши мне что происходит — "
        "я сохраню всё с точным временем\\.\n\n"
        "*Примеры записей:*\n"
        "🌅 `Проснулся в 7:30`\n"
        "🚗 `Выехал на работу`\n"
        "🛒 `Купил кофе и хлеб`\n"
        "💼 `Провёл отличную встречу`\n"
        "🏠 `Пришёл домой, устал но доволен`\n\n"
        "📊 Каждый вечер в *21:00* пришлю красивый итог дня\\!\n\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "*Команды:*\n"
        "/today — записи за сегодня\n"
        "/yesterday — записи за вчера\n"
        "/history — история 7 дней\n"
        "/stats — моя статистика\n"
        "/clear — очистить сегодня\n"
        "/menu — главное меню"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    streak = get_streak(update.effective_user.id)
    streak_line = f"🔥 Серия: {streak} дней подряд" if streak >= 2 else "📓 Личный дневник"
    await update.message.reply_text(
        f"╔══════════════════╗\n║  📓  МОЙ ДЕНЬ  ║\n╚══════════════════╝\n\n{streak_line}",
        parse_mode="Markdown",
        reply_markup=kb_main()
    )

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    upsert_user(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    today = user_today(uid)
    date_str = today.strftime("%Y-%m-%d")
    text = format_day(uid, today, "Сегодня")
    stars, mood = get_rating(uid, date_str)
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=kb_rating(date_str, stars, mood))

async def cmd_yesterday(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    upsert_user(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    yesterday = user_today(uid) - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")
    text = format_day(uid, yesterday, "Вчера")
    stars, mood = get_rating(uid, date_str)
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=kb_rating(date_str, stars, mood))

async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    upsert_user(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    await update.message.reply_text(format_history(uid), parse_mode="Markdown")

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    upsert_user(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    await update.message.reply_text(format_stats(uid), parse_mode="Markdown")

async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    today = user_today(uid)
    date_str = today.strftime("%Y-%m-%d")
    delete_notes(uid, date_str)
    await update.message.reply_text("🗑 Записи за сегодня удалены.")

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username or "", user.first_name or "")
    uid = user.id
    text = update.message.text.strip()
    if not text:
        return

    today = user_today(uid)
    date_str = today.strftime("%Y-%m-%d")
    emoji = get_emoji_for_note(text)
    add_note(uid, date_str, text, emoji)

    notes = get_notes(uid, date_str)
    count = len(notes)

    responses = [
        f"{emoji} Записал\\! Сегодня уже *{count}* записей\\.",
        f"{emoji} Готово\\. Всего сегодня: *{count}* записей\\.",
        f"{emoji} Сохранено\\! *{count}* записей за день\\.",
        f"{emoji} Записал в дневник\\. Всего: *{count}*\\.",
    ]
    await update.message.reply_text(random.choice(responses), parse_mode="MarkdownV2")

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data.startswith("star:"):
        _, date_str, val = data.split(":")
        stars = int(val)
        _, mood = get_rating(uid, date_str)
        set_rating(uid, date_str, stars=stars, mood=mood or None)
        stars_n, mood_n = get_rating(uid, date_str)
        await q.edit_message_reply_markup(reply_markup=kb_rating(date_str, stars_n, mood_n))

    elif data.startswith("mood:"):
        _, date_str, emoji = data.split(":")
        stars, _ = get_rating(uid, date_str)
        set_rating(uid, date_str, stars=stars or None, mood=emoji)
        stars_n, mood_n = get_rating(uid, date_str)
        await q.edit_message_reply_markup(reply_markup=kb_rating(date_str, stars_n, mood_n))

    elif data == "cmd:today":
        today = user_today(uid)
        date_str = today.strftime("%Y-%m-%d")
        text = format_day(uid, today, "Сегодня")
        stars, mood = get_rating(uid, date_str)
        await q.message.reply_text(text, parse_mode="Markdown",
                                   reply_markup=kb_rating(date_str, stars, mood))

    elif data == "cmd:yesterday":
        yesterday = user_today(uid) - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")
        text = format_day(uid, yesterday, "Вчера")
        stars, mood = get_rating(uid, date_str)
        await q.message.reply_text(text, parse_mode="Markdown",
                                   reply_markup=kb_rating(date_str, stars, mood))

    elif data == "cmd:history":
        await q.message.reply_text(format_history(uid), parse_mode="Markdown")

    elif data == "cmd:stats":
        await q.message.reply_text(format_stats(uid), parse_mode="Markdown")

    elif data == "cmd:clear":
        today = user_today(uid)
        date_str = today.strftime("%Y-%m-%d")
        delete_notes(uid, date_str)
        await q.message.reply_text("🗑 Записи за сегодня удалены.")

# ═══════════════════════════════════════════
#  УТРЕННЕЕ ПРИВЕТСТВИЕ И ВЕЧЕРНЯЯ СВОДКА
# ═══════════════════════════════════════════
async def scheduled_jobs(ctx: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB_PATH) as con:
        users = con.execute("SELECT user_id, first_name, timezone FROM users").fetchall()

    for uid, first_name, tz_name in users:
        try:
            tz = ZoneInfo(tz_name or DEFAULT_TZ)
            now = datetime.now(tz)
            hour = now.hour
            minute = now.minute

            # Утреннее приветствие в 8:00
            if hour == 8 and minute < 5:
                greeting = random.choice(MORNING_GREETINGS)
                quote = random.choice(QUOTES)
                name = first_name or "друг"
                msg = (
                    f"{greeting}\n\n"
                    f"👤 *{name}*, сегодня:\n"
                    f"📅 {now.day} {MONTHS_RU[now.month]} · {DAYS_RU[now.weekday()]}\n"
                    f"📄 День {day_of_year(now.date())} из 365\n\n"
                    f"_{quote}_"
                )
                await ctx.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")

            # Вечерняя сводка в 21:00
            if hour == 21 and minute < 5:
                today = now.date()
                date_str = today.strftime("%Y-%m-%d")
                notes = get_notes(uid, date_str)
                if not notes:
                    continue
                text = format_day(uid, today, "Итог дня")
                stars, mood = get_rating(uid, date_str)
                streak = get_streak(uid)
                streak_msg = f"\n\n🔥 *Серия:* {streak} дней подряд\\!" if streak >= 2 else ""
                await ctx.bot.send_message(
                    chat_id=uid,
                    text=f"🌙 *Вечерняя сводка*\n\n{text}{streak_msg}\n\n_Оцени свой день:_",
                    parse_mode="Markdown",
                    reply_markup=kb_rating(date_str, stars, mood)
                )
        except Exception as e:
            print(f"Job error for {uid}: {e}")

def day_of_year(dt):
    return dt.timetuple().tm_yday

# ═══════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("menu",      cmd_menu))
    app.add_handler(CommandHandler("today",     cmd_today))
    app.add_handler(CommandHandler("yesterday", cmd_yesterday))
    app.add_handler(CommandHandler("history",   cmd_history))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("clear",     cmd_clear))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(scheduled_jobs, interval=300, first=10)

    print("🤖 МОЙ ДЕНЬ v2.0 запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
