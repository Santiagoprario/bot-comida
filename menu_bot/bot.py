from __future__ import annotations

import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from .db import Database
from .parser import parse_key_values, parse_offer
from .planner import (
    format_day,
    format_household_rotation,
    format_product_preferences,
    format_shopping_list,
    format_week,
    generate_week,
    week_start_for,
)
from .weather import fetch_weather_context


load_dotenv()

DB = Database(os.getenv("DB_PATH", "data/menu_bot.sqlite3"))
TZ = ZoneInfo(os.getenv("TIMEZONE", "America/Argentina/Buenos_Aires"))

KEYBOARD = ReplyKeyboardMarkup(
    [
        ["Menú de hoy", "Regenerar semana"],
        ["Menú semanal", "Compra"],
        ["Ver ofertas", "Mis marcas"],
        ["Hogar"],
        ["Ver perfil", "Ver reglas"],
        ["Ayuda"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

BUTTON_ACTIONS = {
    "menú de hoy": "menu_hoy",
    "menu de hoy": "menu_hoy",
    "regenerar semana": "generar_semana",
    "menú semanal": "menu_semana",
    "menu semanal": "menu_semana",
    "compra": "compra",
    "ver ofertas": "ofertas",
    "mis marcas": "mis_marcas",
    "hogar": "hogar",
    "ver perfil": "perfil",
    "ver reglas": "condiciones",
    "ayuda": "ayuda",
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    DB.ensure_user(chat_id)
    await update.message.reply_text(
        "Listo. Configurá tu perfil con /perfil y tus condiciones con /condiciones.\n\n"
        "Ejemplo:\n"
        "/perfil objetivo=bajar grasa, personas=1, presupuesto=45000\n"
        "/condiciones restricciones=sin lactosa, evitar=atún, preferencias=pollo huevo\n"
        "/oferta pollo 30% off\n"
        "/generar_semana",
        reply_markup=KEYBOARD,
    )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Comandos:\n"
        "/perfil objetivo=bajar grasa, personas=1, calorias=2200, presupuesto=50000\n"
        "/condiciones restricciones=sin gluten, evitar=pescado, preferencias=pollo huevos\n"
        "/oferta pollo $4500 kg\n"
        "/ofertas\n"
        "/limpiar_ofertas\n"
        "/mis_marcas\n"
        "/hogar\n"
        "/generar_semana\n"
        "/menu_hoy\n"
        "/menu_semana\n"
        "/compra",
        reply_markup=KEYBOARD,
    )


async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    payload = _command_payload(update.message.text)
    if not payload:
        user = DB.get_user(chat_id)
        await update.message.reply_text(f"Perfil actual:\n{_format_dict(user['profile'])}", reply_markup=KEYBOARD)
        return
    values = parse_key_values(payload)
    if not values:
        await update.message.reply_text(
            "Usá formato clave=valor. Ejemplo: /perfil objetivo=bajar grasa, personas=1",
            reply_markup=KEYBOARD,
        )
        return
    profile = DB.update_profile(chat_id, values)
    await update.message.reply_text(f"Perfil actualizado:\n{_format_dict(profile)}", reply_markup=KEYBOARD)


async def condiciones(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    payload = _command_payload(update.message.text)
    if not payload:
        user = DB.get_user(chat_id)
        await update.message.reply_text(f"Condiciones actuales:\n{_format_dict(user['conditions'])}", reply_markup=KEYBOARD)
        return
    values = parse_key_values(payload)
    if not values:
        await update.message.reply_text(
            "Usá formato clave=valor. Ejemplo: /condiciones evitar=atun, preferencias=pollo",
            reply_markup=KEYBOARD,
        )
        return
    conditions = DB.update_conditions(chat_id, values)
    await update.message.reply_text(f"Condiciones actualizadas:\n{_format_dict(conditions)}", reply_markup=KEYBOARD)


async def oferta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    payload = _command_payload(update.message.text)
    if not payload:
        await update.message.reply_text("Ejemplo: /oferta pollo $4500 kg o /oferta huevos 2x1", reply_markup=KEYBOARD)
        return
    item, price, note = parse_offer(payload)
    DB.add_offer(chat_id, item, price, note)
    await update.message.reply_text(f"Oferta guardada: {item}" + (f" ({price})" if price else ""), reply_markup=KEYBOARD)


async def ofertas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = DB.list_offers(update.effective_chat.id)
    if not rows:
        await update.message.reply_text("Todavía no cargaste ofertas.", reply_markup=KEYBOARD)
        return
    lines = ["Ofertas cargadas:"]
    for row in rows:
        extra = " ".join(part for part in [row.get("price"), row.get("note")] if part)
        lines.append(f"- {row['item']}" + (f": {extra}" if extra else ""))
    await update.message.reply_text("\n".join(lines), reply_markup=KEYBOARD)


async def limpiar_ofertas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    DB.clear_offers(update.effective_chat.id)
    await update.message.reply_text("Ofertas borradas.", reply_markup=KEYBOARD)


async def generar_semana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    plan, shopping, start = _build_and_save(chat_id, _today())
    await update.message.reply_text(
        f"Menú generado para la semana del {start.isoformat()}.\n\n"
        f"{format_day(plan[0])}\n\n"
        "Pedí /menu_semana o /compra para ver el resto.",
        reply_markup=KEYBOARD,
    )


async def menu_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    today = _today()
    weekly = _get_or_create(chat_id, today)
    index = today.weekday()
    await update.message.reply_text(format_day(weekly["plan"][index]), reply_markup=KEYBOARD)


async def menu_semana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    weekly = _get_or_create(update.effective_chat.id, _today())
    await update.message.reply_text(_split_if_needed(format_week(weekly["plan"])), reply_markup=KEYBOARD)


async def compra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    weekly = _get_or_create(chat_id, _today())
    preferences = DB.get_product_preferences(chat_id)
    await update.message.reply_text(format_shopping_list(weekly["shopping_list"], preferences), reply_markup=KEYBOARD)


async def mis_marcas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    preferences = DB.get_product_preferences(update.effective_chat.id)
    await update.message.reply_text(format_product_preferences(preferences), reply_markup=KEYBOARD)


async def hogar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"{format_household_rotation()}\n\n"
        "Para cambiar esta rotación, decime acá qué producto querés agregar, sacar o cada cuánto comprarlo y lo dejo configurado.",
        reply_markup=KEYBOARD,
    )


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip().lower()
    action = BUTTON_ACTIONS.get(text)
    if action == "menu_hoy":
        await menu_hoy(update, context)
    elif action == "generar_semana":
        await generar_semana(update, context)
    elif action == "menu_semana":
        await menu_semana(update, context)
    elif action == "compra":
        await compra(update, context)
    elif action == "ofertas":
        await ofertas(update, context)
    elif action == "mis_marcas":
        await mis_marcas(update, context)
    elif action == "hogar":
        await hogar(update, context)
    elif action == "perfil":
        await perfil(update, context)
    elif action == "condiciones":
        await condiciones(update, context)
    elif action == "ayuda":
        await ayuda(update, context)
    else:
        await update.message.reply_text(
            "Usá los botones de abajo o /ayuda. Para cargar ofertas: /oferta pollo $4500 kg",
            reply_markup=KEYBOARD,
        )


async def daily_push(context: ContextTypes.DEFAULT_TYPE) -> None:
    today = _today()
    for chat_id in DB.list_chat_ids():
        weekly = _get_or_create(chat_id, today)
        await context.bot.send_message(chat_id=chat_id, text=format_day(weekly["plan"][today.weekday()]))


def build_application(token: str) -> Application:
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("perfil", perfil))
    app.add_handler(CommandHandler("condiciones", condiciones))
    app.add_handler(CommandHandler("oferta", oferta))
    app.add_handler(CommandHandler("ofertas", ofertas))
    app.add_handler(CommandHandler("mis_marcas", mis_marcas))
    app.add_handler(CommandHandler("hogar", hogar))
    app.add_handler(CommandHandler("limpiar_ofertas", limpiar_ofertas))
    app.add_handler(CommandHandler("generar_semana", generar_semana))
    app.add_handler(CommandHandler("menu_hoy", menu_hoy))
    app.add_handler(CommandHandler("menu_semana", menu_semana))
    app.add_handler(CommandHandler("compra", compra))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_router))

    hour = int(os.getenv("DAILY_SEND_HOUR", "8"))
    minute = int(os.getenv("DAILY_SEND_MINUTE", "0"))
    app.job_queue.run_daily(daily_push, time=time(hour=hour, minute=minute, tzinfo=TZ), name="daily_menu")
    return app


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN. Copiá .env.example a .env y pegá el token.")

    app = build_application(token)
    app.run_polling()


def _build_and_save(chat_id: int, day: date) -> tuple[list[dict], dict[str, float], date]:
    user = DB.get_user(chat_id)
    offers = DB.list_offers(chat_id)
    start = week_start_for(day)
    plan, shopping = generate_week(start, user["profile"], user["conditions"], offers, fetch_weather_context())
    DB.save_weekly_plan(chat_id, start.isoformat(), plan, shopping)
    return plan, shopping, start


def _get_or_create(chat_id: int, day: date) -> dict:
    start = week_start_for(day)
    weekly = DB.get_weekly_plan(chat_id, start.isoformat())
    if weekly and not _plan_needs_refresh(weekly["plan"]):
        return weekly
    plan, shopping, _ = _build_and_save(chat_id, day)
    return {"plan": plan, "shopping_list": shopping}


def _plan_needs_refresh(plan: list[dict]) -> bool:
    if not plan:
        return True
    comidas = plan[0].get("comidas", {})
    return "colación 2" in comidas or "clima" not in plan[0]


def _today() -> date:
    return datetime.now(TZ).date()


def _command_payload(text: str) -> str:
    return text.split(maxsplit=1)[1].strip() if text and len(text.split(maxsplit=1)) > 1 else ""


def _format_dict(values: dict) -> str:
    if not values:
        return "- sin datos"
    return "\n".join(f"- {key}: {value}" for key, value in values.items())


def _split_if_needed(text: str) -> str:
    return text[:3900] + "\n\n..." if len(text) > 3900 else text


if __name__ == "__main__":
    main()
