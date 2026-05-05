from __future__ import annotations

import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from .db import Database
from .disco import (
    DEFAULT_SALES_CHANNEL,
    format_disco_product_list,
    format_disco_search,
    format_disco_simulation,
    search_disco_products,
    simulate_disco_purchase,
)
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
from .presets import get_preset, list_presets
from .weather import fetch_weather_context


load_dotenv()

DB = Database(os.getenv("DB_PATH", "data/menu_bot.sqlite3"))
TZ = ZoneInfo(os.getenv("TIMEZONE", "America/Argentina/Buenos_Aires"))

KEYBOARD = ReplyKeyboardMarkup(
    [
        ["Menú de hoy", "Regenerar semana"],
        ["Menú semanal", "Compra"],
        ["Ver ofertas", "Mis marcas"],
        ["Hogar", "Disco"],
        ["Stock", "Cambiar hoy"],
        ["Invitar", "Mi ID"],
        ["Presets"],
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
    "disco": "simular_disco",
    "stock": "stock",
    "cambiar hoy": "cambiar_hoy",
    "invitar": "invitar",
    "mi id": "mi_id",
    "presets": "presets",
    "ver perfil": "perfil",
    "ver reglas": "condiciones",
    "ayuda": "ayuda",
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _handle_invite_start(update):
        return
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
    if not await _guard(update):
        return
    await update.message.reply_text(
        "Comandos:\n"
        "/perfil objetivo=bajar grasa, personas=1, calorias=2200, presupuesto=50000\n"
        "/condiciones restricciones=sin gluten, evitar=pescado, preferencias=pollo huevos\n"
        "/presets\n"
        "/preset sanda\n"
        "/disco_config sc=33, zona=Santa Clara del Mar\n"
        "/buscar_disco leche zero lactosa\n"
        "/simular_disco\n"
        "/compra_disco\n"
        "/oferta pollo $4500 kg\n"
        "/ofertas\n"
        "/limpiar_ofertas\n"
        "/mis_marcas\n"
        "/hogar\n"
        "/stock arroz=500, huevos=6\n"
        "/mi_stock\n"
        "/limpiar_stock\n"
        "/favorito milanesas de nalga\n"
        "/no_repetir pescado\n"
        "/cambiar_hoy\n"
        "/invitar\n"
        "/mi_id\n"
        "/generar_semana\n"
        "/menu_hoy\n"
        "/menu_semana\n"
        "/compra",
        reply_markup=KEYBOARD,
    )


async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
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
    if not await _guard(update):
        return
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


async def presets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    rows = list_presets()
    lines = ["Presets disponibles:"]
    for key, preset_data in rows.items():
        lines.append(f"- /preset {key}: {preset_data['description']}")
    await update.message.reply_text("\n".join(lines), reply_markup=KEYBOARD)


async def preset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    name = _command_payload(update.message.text)
    if not name:
        await presets(update, context)
        return
    preset_data = get_preset(name)
    if not preset_data:
        await update.message.reply_text("No encontré ese preset. Usá /presets para ver opciones.", reply_markup=KEYBOARD)
        return
    profile = DB.update_profile(chat_id, preset_data["profile"])
    conditions = DB.update_conditions(chat_id, preset_data["conditions"])
    _clear_current_week(chat_id)
    await update.message.reply_text(
        f"Preset aplicado: {preset_data['label']}.\n\n"
        f"Perfil:\n{_format_dict(profile)}\n\n"
        f"Reglas:\n{_format_dict(conditions)}\n\n"
        "Regeneré la configuración base. Usá /generar_semana para crear el menú familiar.",
        reply_markup=KEYBOARD,
    )


async def oferta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    payload = _command_payload(update.message.text)
    if not payload:
        await update.message.reply_text("Ejemplo: /oferta pollo $4500 kg o /oferta huevos 2x1", reply_markup=KEYBOARD)
        return
    item, price, note = parse_offer(payload)
    DB.add_offer(chat_id, item, price, note)
    await update.message.reply_text(f"Oferta guardada: {item}" + (f" ({price})" if price else ""), reply_markup=KEYBOARD)


async def ofertas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
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
    if not await _guard(update):
        return
    DB.clear_offers(update.effective_chat.id)
    await update.message.reply_text("Ofertas borradas.", reply_markup=KEYBOARD)


async def disco_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    payload = _command_payload(update.message.text)
    if not payload:
        user = DB.get_user(chat_id)
        sc = _disco_sales_channel(user["profile"])
        zona = user["profile"].get("disco_zona", "sin zona cargada")
        await update.message.reply_text(f"Disco configurado:\n- sc: {sc}\n- zona: {zona}", reply_markup=KEYBOARD)
        return
    values = parse_key_values(payload)
    if not values:
        await update.message.reply_text("Ejemplo: /disco_config sc=33, zona=Santa Clara del Mar", reply_markup=KEYBOARD)
        return
    profile_values = {}
    if "sc" in values:
        profile_values["disco_sc"] = str(values["sc"])
    if "zona" in values:
        profile_values["disco_zona"] = values["zona"]
    profile = DB.update_profile(chat_id, profile_values)
    await update.message.reply_text(
        f"Disco actualizado:\n- sc: {_disco_sales_channel(profile)}\n- zona: {profile.get('disco_zona', 'sin zona')}",
        reply_markup=KEYBOARD,
    )


async def buscar_disco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    query = _command_payload(update.message.text)
    if not query:
        await update.message.reply_text("Ejemplo: /buscar_disco leche zero lactosa", reply_markup=KEYBOARD)
        return
    user = DB.get_user(update.effective_chat.id)
    products = search_disco_products(query, sales_channel=_disco_sales_channel(user["profile"]))
    await update.message.reply_text(format_disco_search(products, query), reply_markup=KEYBOARD)


async def simular_disco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    weekly = _get_or_create(chat_id, _today())
    user = DB.get_user(chat_id)
    sales_channel = _disco_sales_channel(user["profile"])
    max_items = int(os.getenv("DISCO_SIMULATION_LIMIT", "14"))
    lines, missing = simulate_disco_purchase(
        weekly["shopping_list"],
        sales_channel=sales_channel,
        max_items=max_items,
    )
    await update.message.reply_text(
        _split_if_needed(format_disco_simulation(lines, missing, sales_channel)),
        reply_markup=KEYBOARD,
    )


async def compra_disco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    weekly = _get_or_create(chat_id, _today())
    user = DB.get_user(chat_id)
    sales_channel = _disco_sales_channel(user["profile"])
    max_items = int(os.getenv("DISCO_SIMULATION_LIMIT", "14"))
    lines, missing = simulate_disco_purchase(
        weekly["shopping_list"],
        sales_channel=sales_channel,
        max_items=max_items,
    )
    await update.message.reply_text(
        _split_if_needed(format_disco_product_list(lines, missing, sales_channel)),
        reply_markup=KEYBOARD,
    )


async def generar_semana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    plan, shopping, start = _build_and_save(chat_id, _today())
    await update.message.reply_text(
        f"Menú generado para la semana del {start.isoformat()}.\n\n"
        f"{format_day(plan[0])}\n\n"
        "Pedí /menu_semana o /compra para ver el resto.",
        reply_markup=KEYBOARD,
    )


async def menu_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    today = _today()
    weekly = _get_or_create(chat_id, today)
    index = today.weekday()
    await update.message.reply_text(format_day(weekly["plan"][index]), reply_markup=KEYBOARD)


async def menu_semana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    weekly = _get_or_create(update.effective_chat.id, _today())
    await update.message.reply_text(_split_if_needed(format_week(weekly["plan"])), reply_markup=KEYBOARD)


async def compra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    weekly = _get_or_create(chat_id, _today())
    preferences = DB.get_product_preferences(chat_id)
    pantry = DB.list_pantry_items(chat_id)
    user = DB.get_user(chat_id)
    sales_channel = _disco_sales_channel(user["profile"])
    max_items = int(os.getenv("DISCO_SIMULATION_LIMIT", "14"))
    disco_lines, missing = simulate_disco_purchase(
        weekly["shopping_list"],
        sales_channel=sales_channel,
        max_items=max_items,
    )
    await update.message.reply_text(
        _split_if_needed(
            format_shopping_list(weekly["shopping_list"], preferences, pantry)
            + "\n\n"
            + format_disco_product_list(disco_lines, missing, sales_channel)
        ),
        reply_markup=KEYBOARD,
    )


async def mis_marcas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    preferences = DB.get_product_preferences(update.effective_chat.id)
    await update.message.reply_text(format_product_preferences(preferences), reply_markup=KEYBOARD)


async def hogar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    await update.message.reply_text(
        f"{format_household_rotation()}\n\n"
        "Para cambiar esta rotación, decime acá qué producto querés agregar, sacar o cada cuánto comprarlo y lo dejo configurado.",
        reply_markup=KEYBOARD,
    )


async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    payload = _command_payload(update.message.text)
    if not payload:
        await mi_stock(update, context)
        return
    values = parse_key_values(payload)
    if not values:
        await update.message.reply_text("Ejemplo: /stock arroz=500, huevo=6, leche zero lactosa=1", reply_markup=KEYBOARD)
        return
    for item, quantity in values.items():
        try:
            qty = float(quantity)
        except (TypeError, ValueError):
            qty = 1
        DB.upsert_pantry_item(chat_id, item, qty)
    await update.message.reply_text("Stock actualizado. La próxima /compra lo descuenta.", reply_markup=KEYBOARD)


async def mi_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    pantry = DB.list_pantry_items(update.effective_chat.id)
    if not pantry:
        await update.message.reply_text("No hay stock cargado.", reply_markup=KEYBOARD)
        return
    await update.message.reply_text(
        "Stock en casa:\n" + "\n".join(f"- {item}: {qty:g}" for item, qty in pantry.items()),
        reply_markup=KEYBOARD,
    )


async def limpiar_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    DB.clear_pantry(update.effective_chat.id)
    await update.message.reply_text("Stock borrado.", reply_markup=KEYBOARD)


async def favorito(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    item = _command_payload(update.message.text)
    if not item:
        await update.message.reply_text("Ejemplo: /favorito milanesas de nalga", reply_markup=KEYBOARD)
        return
    DB.add_feedback(update.effective_chat.id, item, "like")
    user = DB.get_user(update.effective_chat.id)
    condiciones = user["conditions"]
    condiciones["preferencias"] = f"{condiciones.get('preferencias', '')} {item}".strip()
    DB.update_conditions(update.effective_chat.id, condiciones)
    await update.message.reply_text("Guardado como favorito y sumado a preferencias.", reply_markup=KEYBOARD)


async def no_repetir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    item = _command_payload(update.message.text)
    if not item:
        await update.message.reply_text("Ejemplo: /no_repetir pescado", reply_markup=KEYBOARD)
        return
    DB.add_feedback(update.effective_chat.id, item, "dislike")
    user = DB.get_user(update.effective_chat.id)
    condiciones = user["conditions"]
    condiciones["evitar"] = f"{condiciones.get('evitar', '')} {item}".strip()
    DB.update_conditions(update.effective_chat.id, condiciones)
    _clear_current_week(update.effective_chat.id)
    await update.message.reply_text("Anotado para evitarlo y regenerar próximas comidas.", reply_markup=KEYBOARD)


async def cambiar_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    _clear_current_week(chat_id)
    weekly = _get_or_create(chat_id, _today())
    await update.message.reply_text("Regeneré la semana. Menú de hoy:\n\n" + format_day(weekly["plan"][_today().weekday()]), reply_markup=KEYBOARD)


async def invitar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    code = DB.create_invite(update.effective_chat.id)
    await update.message.reply_text(
        "Código de invitación creado.\n\n"
        f"Tu cuñada tiene que abrir el bot y mandar:\n/start {code}\n\n"
        "Después puede aplicar /preset sanda o configurar su perfil con /perfil y sus reglas con /condiciones.",
        reply_markup=KEYBOARD,
    )


async def mi_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    await update.message.reply_text(f"Tu chat ID es: {update.effective_chat.id}", reply_markup=KEYBOARD)


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
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
    elif action == "simular_disco":
        await simular_disco(update, context)
    elif action == "stock":
        await mi_stock(update, context)
    elif action == "cambiar_hoy":
        await cambiar_hoy(update, context)
    elif action == "invitar":
        await invitar(update, context)
    elif action == "mi_id":
        await mi_id(update, context)
    elif action == "presets":
        await presets(update, context)
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
    app.add_handler(CommandHandler("presets", presets))
    app.add_handler(CommandHandler("preset", preset))
    app.add_handler(CommandHandler("oferta", oferta))
    app.add_handler(CommandHandler("ofertas", ofertas))
    app.add_handler(CommandHandler("disco_config", disco_config))
    app.add_handler(CommandHandler("buscar_disco", buscar_disco))
    app.add_handler(CommandHandler("simular_disco", simular_disco))
    app.add_handler(CommandHandler("compra_disco", compra_disco))
    app.add_handler(CommandHandler("mis_marcas", mis_marcas))
    app.add_handler(CommandHandler("hogar", hogar))
    app.add_handler(CommandHandler("stock", stock))
    app.add_handler(CommandHandler("mi_stock", mi_stock))
    app.add_handler(CommandHandler("limpiar_stock", limpiar_stock))
    app.add_handler(CommandHandler("favorito", favorito))
    app.add_handler(CommandHandler("no_repetir", no_repetir))
    app.add_handler(CommandHandler("cambiar_hoy", cambiar_hoy))
    app.add_handler(CommandHandler("invitar", invitar))
    app.add_handler(CommandHandler("mi_id", mi_id))
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
    plan, shopping = generate_week(
        start,
        user["profile"],
        user["conditions"],
        offers,
        fetch_weather_context(user["profile"]),
    )
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


async def _guard(update: Update) -> bool:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id and DB.is_authorized_user(chat_id):
        return True
    allowed_ids = _allowed_chat_ids()
    if not allowed_ids:
        return True
    if str(chat_id) in allowed_ids:
        if chat_id:
            DB.authorize_user(chat_id)
        return True
    if update.message:
        await update.message.reply_text(
            "No autorizado. Pedile al dueño del bot un código y usá /start CODIGO."
        )
    return False


async def _handle_invite_start(update: Update) -> bool:
    chat_id = update.effective_chat.id
    payload = _command_payload(update.message.text)
    if DB.is_authorized_user(chat_id) or str(chat_id) in _allowed_chat_ids() or not _allowed_chat_ids():
        DB.authorize_user(chat_id)
        return True
    if payload and DB.consume_invite(payload, chat_id):
        await update.message.reply_text(
            "Listo, cuenta familiar activada. Podés aplicar /preset sanda o configurar tu perfil "
            "con /perfil y tus reglas con /condiciones.",
            reply_markup=KEYBOARD,
        )
        return True
    await update.message.reply_text("Código inválido o vencido. Pedí una nueva invitación.")
    return False


def _allowed_chat_ids() -> set[str]:
    raw = ",".join(
        value
        for value in [
            os.getenv("ALLOWED_CHAT_IDS", ""),
            os.getenv("ALLOWED_CHAT_ID", ""),
            os.getenv("DEFAULT_CHAT_ID", ""),
        ]
        if value
    )
    return {part.strip() for part in raw.split(",") if part.strip()}


def _disco_sales_channel(profile: dict) -> str:
    return str(profile.get("disco_sc") or DEFAULT_SALES_CHANNEL)


def _clear_current_week(chat_id: int) -> None:
    start = week_start_for(_today()).isoformat()
    with DB.connect() as conn:
        conn.execute("DELETE FROM weekly_plans WHERE chat_id = ? AND week_start = ?", (chat_id, start))


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
