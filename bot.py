"""
МОЙ ДЕНЬ — Telegram Bot
Личный дневник прямо в Telegram
"""

import os
import sqlite3
import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ─────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN", "")
DB_PATH = "diary.db"
DEFAULT_TZ = "Europe/Moscow"
SUMMARY_HOUR = 21   # во сколько слать вечернюю сводку
# ─────────────────────────────────────────

MOODS = {"😄": "Отлично", "🙂": "Хорошо", "😐": "Нормально", "😔": "Грустно", "😤": "Тяжело"}
MONTHS_RU = ["","Января","Февраля","Марта","Апреля","Мая","Июня",
              "Июля","Августа","Сентября","Октября","Ноября","Декабря"]

# ═══════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════
def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            timezone   TEXT DEFAULT 'Europe/Moscow',
            notify_h   INTEGER DEFAULT 21,
            notify_m   INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            date       TEXT,
            text       TEXT,
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
        row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row

def upsert_user(user_id, username):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO users(user_id, username) VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
        """, (user_id, username))

def add_note(user_id, date_str, text):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("INSERT INTO notes(user_id,date,text) VALUES(?,?,?)", (user_id, date_str, text))

def get_notes(user_id, date_str):
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT text, ts FROM notes WHERE user_id=? AND date=? ORDER BY ts",
            (user_id, date_str)
        ).fetchall()
    return rows

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
        rows = con.execute("""
            SELECT r.date, r.stars, r.mood,
                   COUNT(n.id) as note_count
            FROM ratings r
            LEFT JOIN notes n ON n.user_id=r.user_id AND n.date=r.date
            WHERE r.user_id=?
            GROUP BY r.date
            ORDER BY r.date DESC LIMIT ?
        """, (user_id, limit)).fetchall()
    return rows

def day_of_year(dt):
    return dt.timetuple().tm_yday

def user_today(user_id):
    u = get_user(user_id)
    tz_name = u[2] if u else DEFAULT_TZ
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)
    return datetime.now(tz).date()

def fmt_date(date_obj):
    return f"{date_obj.day} {MONTHS_RU[date_obj.month]} {date_obj.year}"

def date_str_to_obj(s):
    return datetime.strptime(s, "%Y-%m-%d").date()

# ═══════════════════════════════════════════════════
#  KEYBOARDS
# ═══════════════════════════════════════════════════
def kb_rating(date_str, current_stars=0, current_mood=''):
    stars_row = []
    for i in range(1, 6):
        label = "⭐" if i <= current_stars else "☆"
        stars_row.append(InlineKeyboardButton(label, callback_data=f"star:{date_str}:{i}"))

    mood_row = []
    for emoji in MOODS:
        label = f"[{emoji}]" if emoji == current_mood else emoji
        mood_row.append(InlineKeyboardButton(label, callback_data=f"mood:{date_str}:{emoji}"))

    return InlineKeyboardMarkup([stars_row, mood_row])

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📓 Сегодня", callback_data="cmd:today"),
         InlineKeyboardButton("📅 Вчера",   callback_data="cmd:yesterday")],
        [InlineKeyboardButton("📜 История 7 дней", callback_data="cmd:history")],
        [InlineKeyboardButton("🗑 Очистить сегодня", callback_data="cmd:clear")],
    ])

# ═══════════════════════════════════════════════════
#  FORMATTERS
# ═══════════════════════════════════════════════════
def format_day(user_id, date_obj, title=""):
    date_str = date_obj.strftime("%Y-%m-%d")
    notes = get_notes(user_id, date_str)
    stars, mood = get_rating(user_id, date_str)
    doy = day_of_year(date_obj)

    header = (
        f"📓 *{title or fmt_date(date_obj)}*\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"📄 Страница `{doy}` из 365\n"
    )

    if not notes:
        body = "\n_Записей пока нет._\n"
    else:
        body = "\n"
        for i, (text, ts) in enumerate(notes, 1):
            try:
                t = datetime.fromisoformat(ts).strftime("%H:%M")
            except Exception:
                t = "--:--"
            body += f"🕐 `{t}` — {text}\n"

    rating_line = ""
    if stars:
        rating_line += "\n⭐ *Оценка:* " + "★" * stars + "☆" * (5 - stars)
    if mood:
        rating_line += f"\n{mood} *Настроение:* {MOODS.get(mood,'')}"

    return header + body + rating_line

def format_history(user_id):
    rows = get_history(user_id, 7)
    if not rows:
        return "📜 История пуста. Начни записывать свой день!"

    lines = ["📜 *Последние 7 дней:*\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"]
    for date_str, stars, mood, note_count in rows:
        try:
            d = date_str_to_obj(date_str)
            label = fmt_date(d)
        except Exception:
            label = date_str
        star_s = "★" * stars + "☆" * (5 - stars) if stars else "☆☆☆☆☆"
        mood_s = mood if mood else "–"
        lines.append(f"\n📅 *{label}*\n{star_s} {mood_s}  |  📝 {note_count} записей")
    return "\n".join(lines)

# ═══════════════════════════════════════════════════
#  HANDLERS
# ═══════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username or user.first_name)
    today = user_today(user.id)

    text = (
        f"👋 Привет, *{user.first_name}*\\!\n\n"
        f"Я твой личный дневник дня\\.\n"
        f"Просто пиши мне что происходит прямо сейчас — "
        f"и я всё запишу с временной меткой\\.\n\n"
        f"*Примеры:*\n"
        f"`Проснулся в 7:30`\n"
        f"`Выехал на работу`\n"
        f"`Купил кофе и хлеб`\n"
        f"`Провёл отличную встречу`\n"
        f"`Пришёл домой, устал но доволен`\n\n"
        f"Каждый вечер в *21:00* я пришлю сводку дня 📓\n\n"
        f"Команды:\n"
        f"/today — записи за сегодня\n"
        f"/yesterday — записи за вчера\n"
        f"/history — история 7 дней\n"
        f"/clear — очистить сегодня\n"
        f"/menu — главное меню"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📓 *МОЙ ДЕНЬ* — главное меню",
        parse_mode="Markdown",
        reply_markup=kb_main()
    )

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    upsert_user(uid, update.effective_user.username or "")
    today = user_today(uid)
    date_str = today.strftime("%Y-%m-%d")
    text = format_day(uid, today, f"Сегодня · {fmt_date(today)}")
    stars, mood = get_rating(uid, date_str)
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=kb_rating(date_str, stars, mood)
    )

async def cmd_yesterday(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    upsert_user(uid, update.effective_user.username or "")
    yesterday = user_today(uid) - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")
    text = format_day(uid, yesterday, f"Вчера · {fmt_date(yesterday)}")
    stars, mood = get_rating(uid, date_str)
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=kb_rating(date_str, stars, mood)
    )

async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    upsert_user(uid, update.effective_user.username or "")
    await update.message.reply_text(format_history(uid), parse_mode="Markdown")

async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    today = user_today(uid)
    date_str = today.strftime("%Y-%m-%d")
    delete_notes(uid, date_str)
    await update.message.reply_text("🗑 Записи за сегодня удалены.")

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username or user.first_name)
    uid = user.id
    text = update.message.text.strip()
    if not text:
        return

    today = user_today(uid)
    date_str = today.strftime("%Y-%m-%d")
    add_note(uid, date_str, text)

    # Count notes today
    notes = get_notes(uid, date_str)
    count = len(notes)
    suffix = ["","запись","записи","записи","записи","записей",
              "записей","записей","записей","записей","записей"]
    s = suffix[count] if count < 11 else "записей"

    responses = [
        f"✍️ Записал! Сегодня уже {count} {s}.",
        f"📝 Готово. {count} {s} за сегодня.",
        f"✅ Сохранено! Всего сегодня: {count} {s}.",
        f"📓 Записал в дневник. {count} {s} за день.",
    ]
    import random
    await update.message.reply_text(random.choice(responses))

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
        await q.answer(f"Оценка {'★'*stars} сохранена!", show_alert=False)

    elif data.startswith("mood:"):
        _, date_str, emoji = data.split(":")
        stars, _ = get_rating(uid, date_str)
        set_rating(uid, date_str, stars=stars or None, mood=emoji)
        stars_n, mood_n = get_rating(uid, date_str)
        await q.edit_message_reply_markup(reply_markup=kb_rating(date_str, stars_n, mood_n))
        await q.answer(f"Настроение {emoji} сохранено!", show_alert=False)

    elif data == "cmd:today":
        today = user_today(uid)
        date_str = today.strftime("%Y-%m-%d")
        text = format_day(uid, today, f"Сегодня · {fmt_date(today)}")
        stars, mood = get_rating(uid, date_str)
        await q.message.reply_text(text, parse_mode="Markdown",
                                   reply_markup=kb_rating(date_str, stars, mood))

    elif data == "cmd:yesterday":
        yesterday = user_today(uid) - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")
        text = format_day(uid, yesterday, f"Вчера · {fmt_date(yesterday)}")
        stars, mood = get_rating(uid, date_str)
        await q.message.reply_text(text, parse_mode="Markdown",
                                   reply_markup=kb_rating(date_str, stars, mood))

    elif data == "cmd:history":
        await q.message.reply_text(format_history(uid), parse_mode="Markdown")

    elif data == "cmd:clear":
        today = user_today(uid)
        date_str = today.strftime("%Y-%m-%d")
        delete_notes(uid, date_str)
        await q.message.reply_text("🗑 Записи за сегодня удалены.")

# ═══════════════════════════════════════════════════
#  EVENING SUMMARY JOB
# ═══════════════════════════════════════════════════
async def send_evening_summaries(ctx: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB_PATH) as con:
        users = con.execute("SELECT user_id, timezone, notify_h, notify_m FROM users").fetchall()

    now_utc = datetime.utcnow()
    for uid, tz_name, h, m in users:
        try:
            tz = ZoneInfo(tz_name or DEFAULT_TZ)
            now_local = datetime.now(tz)
            if now_local.hour == h and now_local.minute < 5:
                today = now_local.date()
                date_str = today.strftime("%Y-%m-%d")
                notes = get_notes(uid, date_str)
                if not notes:
                    continue
                text = format_day(uid, today, f"🌙 Итог дня · {fmt_date(today)}")
                stars, mood = get_rating(uid, date_str)
                await ctx.bot.send_message(
                    chat_id=uid,
                    text=text + "\n\n_Оцени свой день:_",
                    parse_mode="Markdown",
                    reply_markup=kb_rating(date_str, stars, mood)
                )
        except Exception as e:
            print(f"Error sending summary to {uid}: {e}")

# ═══════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("menu",      cmd_menu))
    app.add_handler(CommandHandler("today",     cmd_today))
    app.add_handler(CommandHandler("yesterday", cmd_yesterday))
    app.add_handler(CommandHandler("history",   cmd_history))
    app.add_handler(CommandHandler("clear",     cmd_clear))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Evening summary every 5 minutes check
    app.job_queue.run_repeating(send_evening_summaries, interval=300, first=10)

    print("🤖 Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
