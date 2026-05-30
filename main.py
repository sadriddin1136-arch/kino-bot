import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

ADMIN_ID       = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID     = os.getenv("CHANNEL_ID", "@smovi_uz")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@somuray")
USERS_FILE     = "users.json"
MOVIES_FILE    = "movies.json"


# ── Bazalar ───────────────────────────────────────────────────────────────

def load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def register_user(user) -> bool:
    users = load_json(USERS_FILE)
    uid = str(user.id)
    if uid not in users:
        users[uid] = {
            "id": user.id,
            "name": user.full_name,
            "username": user.username or "",
            "joined": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        save_json(USERS_FILE, users)
        return True
    return False

def next_code(movies: dict) -> str:
    if not movies:
        return "1"
    return str(max(int(k) for k in movies if k.isdigit()) + 1)

def increment_views(code: str):
    movies = load_json(MOVIES_FILE)
    if code in movies:
        movies[code]["views"] = movies[code].get("views", 0) + 1
        save_json(MOVIES_FILE, movies)


# ── Obuna tekshirish ──────────────────────────────────────────────────────

async def is_subscribed(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning(f"Obuna tekshirishda xato: {e}")
        return False

async def ask_to_subscribe(update: Update, code: str = ""):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")],
        [InlineKeyboardButton("✅ Obuna bo'ldim", callback_data=f"check_sub:{code}")],
    ])
    await update.message.reply_html(
        "⛔ <b>Kanalga obuna bo'lmagan foydalanuvchilar kinolarni ololmaydi!</b>\n\n"
        "👇 Avval kanalga obuna bo'ling:",
        reply_markup=kb
    )


# ── Kino yuborish ─────────────────────────────────────────────────────────

async def send_movie(update: Update, code: str):
    movies = load_json(MOVIES_FILE)
    if code not in movies:
        await update.message.reply_html(
            f"❌ <code>{code}</code> kodi topilmadi.\n\nTo'g'ri kodni kiriting.",
            reply_markup=user_keyboard()
        )
        return
    m       = movies[code]
    tavsif  = f"\n\n📝 {m['tavsif']}" if m.get("tavsif") else ""
    caption = f"🎬 <b>{m['title']}</b>  |  Kod: <code>{code}</code>{tavsif}"
    increment_views(code)

    if m.get("link"):
        await update.message.reply_html(
            f"{caption}\n\n🔗 <a href='{m['link']}'>Kinoni ko'rish / yuklab olish</a>"
        )
    elif m.get("file_id"):
        ftype = m.get("file_type", "document")
        try:
            if ftype == "video":
                await update.message.reply_video(m["file_id"], caption=caption, parse_mode="HTML")
            elif ftype == "photo":
                await update.message.reply_photo(m["file_id"], caption=caption, parse_mode="HTML")
            else:
                await update.message.reply_document(m["file_id"], caption=caption, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Fayl yuborishda xato: {e}")
            await update.message.reply_html(f"{caption}\n\n⚠️ Fayl yuborishda xato.")


# ── Yangi kino bildirishnomasi ────────────────────────────────────────────

async def notify_all_users(bot, movies: dict, code: str):
    m      = movies[code]
    tavsif = f"\n\n📝 {m['tavsif']}" if m.get("tavsif") else ""
    text   = (
        f"🔔 <b>Yangi kino qo'shildi!</b>\n\n"
        f"🎬 <b>{m['title']}</b>{tavsif}\n\n"
        f"📥 Olish uchun kodni yuboring: <code>{code}</code>"
    )
    users = load_json(USERS_FILE)
    sent, failed = 0, 0
    for uid in users:
        try:
            await bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    logger.info(f"Bildirishnoma: {sent} yuborildi, {failed} yetkazilmadi")
    return sent, failed


# ── Klaviaturalar ─────────────────────────────────────────────────────────

def user_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎬 Kinolar ro'yxati")],
            [KeyboardButton("👨‍💼 Admin bilan bog'lanish")],
        ],
        resize_keyboard=True,
        persistent=True
    )

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kinolar ro'yxati",      callback_data="admin_movies")],
        [InlineKeyboardButton("📊 Statistika",             callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Foydalanuvchilar",       callback_data="admin_users")],
        [InlineKeyboardButton("📢 Hammaga xabar yuborish", callback_data="admin_broadcast")],
    ])


# ── /start ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    is_new = register_user(user)
    name   = user.first_name
    if is_new:
        text = (
            f"🎬 Assalomu alaykum, <b>{name}</b>!\n\n"
            "Kino olish uchun uning <b>kodini</b> yuboring.\n"
            "Masalan: <code>1</code>, <code>25</code>\n\n"
            "👇 Barcha mavjud kinolarni ko'rish uchun tugmani bosing:"
        )
    else:
        text = (
            f"👋 Qaytib keldingiz, <b>{name}</b>!\n\n"
            "Kino kodini yuboring yoki ro'yxatni ko'ring 👇"
        )
    await update.message.reply_html(text, reply_markup=user_keyboard())


# ── /help ─────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "📖 <b>Yordam</b>\n\n"
        "Kino olish uchun uning <b>kodini</b> yuboring.\n"
        "Masalan: <code>1</code>, <code>10</code>, <code>25</code>\n\n"
        "/start — bosh sahifa\n"
        "/help — ushbu yordam",
        reply_markup=user_keyboard()
    )


# ── /admin ────────────────────────────────────────────────────────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo'q.")
        return
    users  = load_json(USERS_FILE)
    movies = load_json(MOVIES_FILE)
    today  = datetime.now().strftime("%Y-%m-%d")
    bugun  = sum(1 for u in users.values() if u.get("joined", "").startswith(today))
    await update.message.reply_html(
        "👑 <b>Admin Panel</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{len(users)}</b>  (bugun +{bugun})\n"
        f"🎬 Kinolar: <b>{len(movies)}</b> ta",
        reply_markup=admin_keyboard()
    )


# ── /add ──────────────────────────────────────────────────────────────────

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo'q.")
        return
    context.user_data["state"] = "waiting_title"
    await update.message.reply_html(
        "🎬 <b>Yangi kino qo'shish</b>\n\n1️⃣ Kino nomini yuboring:"
    )


# ── /list ─────────────────────────────────────────────────────────────────

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo'q.")
        return
    movies = load_json(MOVIES_FILE)
    if not movies:
        await update.message.reply_text("Hali kino qo'shilmagan.\n/add orqali qo'shing.")
        return
    lines = ["🎬 <b>Kinolar ro'yxati:</b>\n"]
    for code, m in sorted(movies.items(), key=lambda x: int(x[0])):
        icon   = "📎" if m.get("link") else "🎥"
        views  = m.get("views", 0)
        lines.append(f"{icon} <code>{code}</code> — {m['title']}  👁 {views}")
    lines.append(f"\n<i>Jami: {len(movies)} ta</i>")
    await update.message.reply_html("\n".join(lines))


# ── /delete ───────────────────────────────────────────────────────────────

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ruxsat yo'q.")
        return
    context.user_data["state"] = "waiting_delete"
    await update.message.reply_html("🗑 O'chirmoqchi bo'lgan kino kodini yuboring:")


# ── Kino saqlash yordamchisi ──────────────────────────────────────────────

async def save_and_notify(update_or_msg, context, title: str, tavsif: str,
                          link=None, file_id=None, file_type="link"):
    movies = load_json(MOVIES_FILE)
    code   = next_code(movies)
    movies[code] = {
        "title":     title,
        "tavsif":    tavsif,
        "link":      link,
        "file_id":   file_id,
        "file_type": file_type,
        "views":     0,
        "added":     datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    save_json(MOVIES_FILE, movies)

    tavsif_line = f"\n📝 {tavsif}" if tavsif else ""
    if hasattr(update_or_msg, "reply_html"):
        await update_or_msg.reply_html(
            f"✅ <b>Kino qo'shildi!</b>\n\n"
            f"🎬 {title}{tavsif_line}\n"
            f"🔢 Kod: <code>{code}</code>\n\n"
            f"📢 Barcha foydalanuvchilarga bildirishnoma yuborilmoqda…"
        )
    else:
        await update_or_msg.reply_html(
            f"✅ <b>Kino qo'shildi!</b>\n\n"
            f"🎬 {title}{tavsif_line}\n"
            f"🔢 Kod: <code>{code}</code>\n\n"
            f"📢 Barcha foydalanuvchilarga bildirishnoma yuborilmoqda…"
        )

    sent, failed = await notify_all_users(context.bot, movies, code)
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📊 Bildirishnoma natijasi:\n✅ {sent} yuborildi  ❌ {failed} yetkazilmadi",
        parse_mode="HTML"
    )


# ── Matn handleri ─────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    register_user(user)
    text  = update.message.text.strip()
    state = context.user_data.get("state")

    # ── Admin holatlari ───────────────────────────────────────────────────

    if user.id == ADMIN_ID and state:

        if state == "waiting_title":
            context.user_data["tmp_title"] = text
            context.user_data["state"]     = "waiting_content"
            await update.message.reply_html(
                f"✅ Nom: <b>{text}</b>\n\n"
                "2️⃣ Kino <b>faylini</b> yuboring\n"
                "   yoki <b>havolasini</b> (URL) yozing:"
            )
            return

        if state == "waiting_content":
            context.user_data["tmp_link"]  = text
            context.user_data["state"]     = "waiting_desc"
            await update.message.reply_html(
                "3️⃣ Kino <b>tavsifini</b> yuboring:\n"
                "<i>(qisqacha — janr, yil, aktyor va h.k.)</i>",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data="skip_desc")
                ]])
            )
            return

        if state == "waiting_desc":
            title  = context.user_data.pop("tmp_title", "Nomsiz")
            link   = context.user_data.pop("tmp_link", None)
            context.user_data.pop("state", None)
            await save_and_notify(update.message, context, title, text, link=link)
            return

        if state == "waiting_delete":
            context.user_data.pop("state", None)
            movies = load_json(MOVIES_FILE)
            if text in movies:
                title = movies.pop(text)["title"]
                save_json(MOVIES_FILE, movies)
                await update.message.reply_html(
                    f"🗑 <b>{title}</b> (kod <code>{text}</code>) o'chirildi."
                )
            else:
                await update.message.reply_html(
                    f"❌ <code>{text}</code> kodi topilmadi."
                )
            return

        if state == "waiting_broadcast":
            context.user_data.pop("state", None)
            users = load_json(USERS_FILE)
            sent, failed = 0, 0
            msg = await update.message.reply_html(
                f"📢 {len(users)} ta foydalanuvchiga yuborilmoqda…"
            )
            for uid in users:
                try:
                    await context.bot.send_message(
                        chat_id=int(uid),
                        text=f"📢 <b>Yangilik:</b>\n\n{text}",
                        parse_mode="HTML"
                    )
                    sent += 1
                except Exception:
                    failed += 1
            await msg.edit_text(
                f"✅ Yuborildi: <b>{sent}</b>  ❌ Yetkazilmadi: <b>{failed}</b>",
                parse_mode="HTML"
            )
            return

    # ── Tugmalar ──────────────────────────────────────────────────────────

    if text == "🎬 Kinolar ro'yxati":
        movies = load_json(MOVIES_FILE)
        if not movies:
            await update.message.reply_text("Hali kinolar qo'shilmagan.")
            return
        lines = ["🎬 <b>Barcha kinolar:</b>\n"]
        for code, m in sorted(movies.items(), key=lambda x: int(x[0])):
            tavsif = f" — {m['tavsif']}" if m.get("tavsif") else ""
            lines.append(f"🔢 <code>{code}</code> {m['title']}{tavsif}")
        lines.append("\n💬 <i>Kodini yuboring — kinoni oling!</i>")
        await update.message.reply_html("\n".join(lines))
        return

    if text == "👨‍💼 Admin bilan bog'lanish":
        await update.message.reply_html(
            f"👨‍💼 Admin bilan bog'lanish:\n\n{ADMIN_USERNAME}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 Adminga yozish", url=f"https://t.me/{ADMIN_USERNAME.lstrip('@')}")
            ]])
        )
        return

    # ── Kino kodi ─────────────────────────────────────────────────────────

    code = text.lstrip("#")
    if code.isdigit():
        if not await is_subscribed(context.bot, user.id):
            await ask_to_subscribe(update, code)
            return
        await send_movie(update, code)
        return

    await update.message.reply_html(
        "❓ Kino olish uchun uning <b>kodini</b> yuboring.\n"
        "Masalan: <code>1</code>, <code>10</code>",
        reply_markup=user_keyboard()
    )


# ── Fayl handler (admin) ──────────────────────────────────────────────────

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    state = context.user_data.get("state")
    if user.id != ADMIN_ID:
        return

    if state == "waiting_content":
        msg = update.message
        if msg.video:        file_id, ftype = msg.video.file_id, "video"
        elif msg.document:   file_id, ftype = msg.document.file_id, "document"
        elif msg.photo:      file_id, ftype = msg.photo[-1].file_id, "photo"
        else:
            await msg.reply_text("⚠️ Qo'llab-quvvatlanmagan fayl turi.")
            return
        context.user_data["tmp_file_id"]   = file_id
        context.user_data["tmp_file_type"] = ftype
        context.user_data["state"]         = "waiting_desc"
        await msg.reply_html(
            "3️⃣ Kino <b>tavsifini</b> yuboring:\n"
            "<i>(qisqacha — janr, yil, aktyor va h.k.)</i>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data="skip_desc")
            ]])
        )

    elif state == "waiting_desc":
        msg = update.message
        if msg.video:        file_id, ftype = msg.video.file_id, "video"
        elif msg.document:   file_id, ftype = msg.document.file_id, "document"
        elif msg.photo:      file_id, ftype = msg.photo[-1].file_id, "photo"
        else:
            return
        context.user_data["tmp_file_id"]   = file_id
        context.user_data["tmp_file_type"] = ftype
        await msg.reply_html(
            "3️⃣ Kino <b>tavsifini</b> yuboring:\n"
            "<i>(qisqacha — janr, yil, aktyor va h.k.)</i>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data="skip_desc")
            ]])
        )


# ── Callback handler ──────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    data = q.data

    # ── Tavsifni o'tkazib yuborish ────────────────────────────────────────
    if data == "skip_desc":
        if q.from_user.id != ADMIN_ID:
            return
        title     = context.user_data.pop("tmp_title", "Nomsiz")
        link      = context.user_data.pop("tmp_link", None)
        file_id   = context.user_data.pop("tmp_file_id", None)
        file_type = context.user_data.pop("tmp_file_type", "document")
        context.user_data.pop("state", None)
        await q.message.delete()
        await save_and_notify(
            q.message.chat, context, title, "",
            link=link, file_id=file_id, file_type=file_type
        )
        return

    # ── Obuna tekshirish ──────────────────────────────────────────────────
    if data.startswith("check_sub:"):
        code = data.split(":", 1)[1]
        if not await is_subscribed(context.bot, q.from_user.id):
            await q.answer("❌ Siz hali obuna bo'lmagansiz! Avval obuna bo'ling.", show_alert=True)
            return
        await q.message.delete()
        if code:
            movies = load_json(MOVIES_FILE)
            if code in movies:
                m       = movies[code]
                tavsif  = f"\n\n📝 {m['tavsif']}" if m.get("tavsif") else ""
                caption = f"🎬 <b>{m['title']}</b>  |  Kod: <code>{code}</code>{tavsif}"
                increment_views(code)
                if m.get("link"):
                    await q.message.chat.send_message(
                        f"{caption}\n\n🔗 <a href='{m['link']}'>Kinoni ko'rish / yuklab olish</a>",
                        parse_mode="HTML"
                    )
                elif m.get("file_id"):
                    ftype = m.get("file_type", "document")
                    try:
                        if ftype == "video":
                            await q.message.chat.send_video(m["file_id"], caption=caption, parse_mode="HTML")
                        elif ftype == "photo":
                            await q.message.chat.send_photo(m["file_id"], caption=caption, parse_mode="HTML")
                        else:
                            await q.message.chat.send_document(m["file_id"], caption=caption, parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Fayl yuborishda xato: {e}")
            else:
                await q.message.chat.send_message(f"❌ <code>{code}</code> kodi topilmadi.", parse_mode="HTML")
        else:
            await q.message.chat.send_message("✅ Obuna tasdiqlandi! Endi kino kodini yuboring.")
        return

    if q.from_user.id != ADMIN_ID:
        return

    # ── Admin callbacklar ─────────────────────────────────────────────────

    if data == "admin_movies":
        movies = load_json(MOVIES_FILE)
        if not movies:
            await q.edit_message_text(
                "Hali kino qo'shilmagan. /add orqali qo'shing.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back_admin")]])
            )
            return
        lines = ["🎬 <b>Kinolar ro'yxati:</b>\n"]
        for code, m in sorted(movies.items(), key=lambda x: int(x[0])):
            icon  = "📎" if m.get("link") else "🎥"
            views = m.get("views", 0)
            lines.append(f"{icon} <code>{code}</code> — {m['title']}  👁 {views}")
        lines.append(f"\n<i>Jami: {len(movies)} ta</i>")
        await q.edit_message_text(
            "\n".join(lines), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back_admin")]])
        )

    elif data == "admin_stats":
        movies = load_json(MOVIES_FILE)
        if not movies:
            await q.edit_message_text(
                "Hali kino yo'q.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back_admin")]])
            )
            return
        sorted_movies = sorted(movies.items(), key=lambda x: x[1].get("views", 0), reverse=True)
        total_views   = sum(m.get("views", 0) for m in movies.values())
        lines = [f"📊 <b>Kino statistikasi</b>  (jami: {total_views} marta ko'rilgan)\n"]
        for i, (code, m) in enumerate(sorted_movies[:20], 1):
            views = m.get("views", 0)
            lines.append(f"{i}. <code>{code}</code> {m['title']} — <b>{views}</b> marta")
        await q.edit_message_text(
            "\n".join(lines), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back_admin")]])
        )

    elif data == "admin_users":
        users = load_json(USERS_FILE)
        lines = ["👥 <b>Foydalanuvchilar:</b>\n"]
        for i, u in enumerate(list(users.values())[:50], 1):
            uname = f"@{u['username']}" if u.get("username") else "—"
            lines.append(f"{i}. <b>{u['name']}</b> {uname}  {u.get('joined','')}")
        if len(users) > 50:
            lines.append(f"\n…va yana {len(users)-50} ta")
        await q.edit_message_text(
            "\n".join(lines), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back_admin")]])
        )

    elif data == "admin_broadcast":
        context.user_data["state"] = "waiting_broadcast"
        await q.edit_message_text("📢 Yuboriladigan xabar matnini yozing:")

    elif data == "back_admin":
        users  = load_json(USERS_FILE)
        movies = load_json(MOVIES_FILE)
        today  = datetime.now().strftime("%Y-%m-%d")
        bugun  = sum(1 for u in users.values() if u.get("joined","").startswith(today))
        await q.edit_message_text(
            "👑 <b>Admin Panel</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{len(users)}</b>  (bugun +{bugun})\n"
            f"🎬 Kinolar: <b>{len(movies)}</b> ta",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN topilmadi!")
        return

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("help",   help_command))
    app.add_handler(CommandHandler("admin",  admin_command))
    app.add_handler(CommandHandler("add",    add_command))
    app.add_handler(CommandHandler("list",   list_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(
        filters.VIDEO | filters.Document.ALL | filters.PHOTO,
        handle_media
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info(f"Kino Bot ishga tushdi! Admin: {ADMIN_ID}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
