from __future__ import annotations

import os
import json
import hashlib
import hmac
import re
import secrets
import smtplib
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html import escape
from typing import Any
from urllib.parse import parse_qs, urlencode
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from telegram.ext import Application

from .bot import DB, TZ, build_application
from .disco import DEFAULT_SALES_CHANNEL, format_disco_product_list, simulate_disco_purchase
from .parser import parse_offer
from .planner import (
    DAYS,
    MEALS,
    SLOTS,
    format_quantity,
    format_shopping_list,
    generate_week,
    replace_meal,
    week_start_for,
)
from .seed import seed_default_user
from .weather import fetch_weather_context, format_weather_summary


load_dotenv()

telegram_app: Application | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    seed_default_user(DB)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        telegram_app = build_application(token)
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling()
    try:
        yield
    finally:
        if telegram_app:
            await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()


app = FastAPI(title="Mesa Lista", lifespan=lifespan)
PWA_CACHE_VERSION = "menu-bot-v6"
SESSION_COOKIE = "menu_session"
CHAT_COOKIE = "menu_chat_id"
PASSWORD_ITERATIONS = 210_000

CHEF_STYLES = {
    "paulina cocina": "Paulina Cocina: práctico, casero, rendidor y sin complicarla.",
    "narda lepes": "Narda Lepes: verduras con más intención, frescura, acidez y buenos condimentos.",
    "germán martitegui": "Germán Martitegui: plato prolijo, buen punto de cocción y sabores más definidos.",
    "german martitegui": "Germán Martitegui: plato prolijo, buen punto de cocción y sabores más definidos.",
    "donato de santis": "Donato De Santis: toque italiano, pastas cuidadas, salsa simple y buen queso.",
    "petersen": "Los Petersen: carnes bien tratadas, buen dorado, reposo y guarniciones clásicas.",
}


@app.get("/manifest.webmanifest")
def manifest() -> Response:
    payload = {
        "name": "Mesa Lista",
        "short_name": "Mesa",
        "description": "Menú semanal, recetas y compra para la casa.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#fff4e8",
        "theme_color": "#d84f35",
        "icons": [
            {
                "src": "/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }
        ],
    }
    return Response(json.dumps(payload, ensure_ascii=False), media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> Response:
    script = f"""
const CACHE_NAME = '{PWA_CACHE_VERSION}';
const APP_SHELL = ['/', '/semana', '/compra', '/random', '/config', '/platos', '/login', '/register', '/verify', '/offline', '/manifest.webmanifest', '/icon.svg'];

self.addEventListener('install', (event) => {{
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
}});

self.addEventListener('activate', (event) => {{
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
}});

self.addEventListener('fetch', (event) => {{
  if (event.request.method !== 'GET') return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {{
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return response;
      }})
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match('/offline')))
  );
}});
"""
    return Response(script.strip(), media_type="application/javascript")


@app.get("/icon.svg")
def app_icon() -> Response:
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="104" fill="#d84f35"/>
  <circle cx="256" cy="250" r="142" fill="#fff4e8"/>
  <circle cx="256" cy="250" r="92" fill="#ffd166"/>
  <path d="M184 286c36 34 108 34 144 0" fill="none" stroke="#53386f" stroke-width="26" stroke-linecap="round"/>
  <path d="M162 154v180M350 154v180" stroke="#53386f" stroke-width="24" stroke-linecap="round"/>
  <path d="M128 392h256" stroke="#fff4e8" stroke-width="28" stroke-linecap="round"/>
</svg>
"""
    return Response(svg.strip(), media_type="image/svg+xml")


@app.get("/brand-plate.svg")
def brand_plate() -> Response:
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 520" role="img" aria-label="Mesa con platos">
  <rect width="760" height="520" rx="34" fill="#fff4e8"/>
  <path d="M60 360c90 68 210 98 340 86 134-13 246-66 300-146 38-57 16-128-40-154-52-25-108 7-163-25-58-33-75-92-159-92-92 0-126 74-191 103-62 28-128 14-152 85-17 51 14 105 65 143Z" fill="#ffd166"/>
  <circle cx="306" cy="250" r="122" fill="#fffdf8"/>
  <circle cx="306" cy="250" r="74" fill="#f7dfc8"/>
  <circle cx="301" cy="242" r="38" fill="#d84f35"/>
  <path d="M220 298c52 42 124 43 176 0" fill="none" stroke="#53386f" stroke-width="18" stroke-linecap="round"/>
  <path d="M502 168c28 20 45 54 45 91 0 62-50 112-112 112-21 0-40-6-57-15" fill="none" stroke="#2d6cdf" stroke-width="18" stroke-linecap="round"/>
  <path d="M512 104v242M594 108v238" stroke="#53386f" stroke-width="16" stroke-linecap="round"/>
  <path d="M122 168c-18 34-18 72 1 116" stroke="#d84f35" stroke-width="18" stroke-linecap="round"/>
  <circle cx="148" cy="384" r="24" fill="#2d6cdf"/>
  <circle cx="610" cy="372" r="19" fill="#d84f35"/>
</svg>
"""
    return Response(svg.strip(), media_type="image/svg+xml")


@app.get("/offline", response_class=HTMLResponse)
def offline() -> str:
    return """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#d84f35">
  <title>Menú sin conexión</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #fff4e8; color: #241b18; font-family: system-ui, sans-serif; }
    main { width: min(520px, calc(100vw - 32px)); border: 1px solid #ead7c7; border-radius: 8px; background: #fffdf8; padding: 24px; }
    h1 { margin: 0 0 10px; font-size: 28px; }
    p { margin: 0; color: #68645d; line-height: 1.4; }
  </style>
</head>
<body>
  <main>
    <h1>Sin conexión</h1>
    <p>La app no pudo actualizar el menú. Cuando vuelva internet, abrila de nuevo para traer la última versión.</p>
  </main>
</body>
</html>"""


def _auth_style() -> str:
    return """
    :root { --bg:#fff4e8; --ink:#241b18; --muted:#78685f; --line:#ead7c7; --card:#fffdf8; --accent:#d84f35; --accent-strong:#8f2f22; --blue:#2d6cdf; --plum:#53386f; --butter:#ffd166; }
    * { box-sizing: border-box; }
    body { margin:0; min-height:100vh; display:grid; place-items:center; background:radial-gradient(circle at 15% 12%, rgba(255,209,102,.34), transparent 28%), linear-gradient(135deg, #fff4e8 0%, #fffdf8 52%, #eaf1ff 100%); color:var(--ink); font-family:Inter, ui-sans-serif, system-ui, sans-serif; padding:18px; }
    main { width:min(500px, 100%); background:rgba(255,253,248,.96); border:1px solid var(--line); border-radius:8px; padding:18px; box-shadow:0 18px 44px rgba(83,56,111,.14); }
    .brand-art { display:block; width:100%; aspect-ratio: 16 / 8.8; object-fit:contain; border:1px solid var(--line); border-radius:8px; margin-bottom:16px; background:#fff4e8; }
    .brand-mark { display:inline-flex; align-items:center; gap:8px; margin-bottom:8px; color:var(--accent-strong); font-size:13px; font-weight:900; text-transform:uppercase; }
    h1 { margin:0 0 8px; font-size:34px; line-height:1; letter-spacing:0; color:var(--plum); }
    p { margin:0 0 18px; color:var(--muted); line-height:1.35; }
    label { display:flex; flex-direction:column; gap:6px; margin-top:12px; color:var(--muted); font-size:13px; font-weight:850; }
    input, select { width:100%; border:1px solid var(--line); border-radius:8px; padding:12px; background:#fff; color:var(--ink); font:inherit; font-weight:650; }
    input:focus, select:focus { outline:3px solid rgba(216,79,53,.18); border-color:var(--accent); }
    button { width:100%; margin-top:16px; border:1px solid var(--accent); border-radius:8px; background:linear-gradient(135deg, var(--accent), var(--accent-strong)); color:#fff; padding:13px; font:inherit; font-weight:900; cursor:pointer; }
    a { color:var(--blue); font-weight:900; }
    .login-error { border:1px solid #c65b46; background:#fff0eb; color:#7c2c20; border-radius:8px; padding:10px; margin:12px 0; font-weight:850; }
    @media (max-width: 520px) { body { padding:12px; align-items:start; } main { margin-top:10px; padding:14px; } h1 { font-size:30px; } .brand-art { aspect-ratio: 16 / 9.6; } }
  """


@app.get("/", response_class=HTMLResponse)
def home(request: Request, pin: str | None = None, chat_id: int | None = None) -> Any:
    if gate := _login_redirect_if_needed(request, pin):
        return gate
    _guard_web(request, pin)
    chat_id = _active_chat_id(chat_id, request)
    user = DB.get_user(chat_id)
    if _needs_onboarding(user):
        return _redirect("/onboarding", chat_id, pin)
    today = _today()
    weekly = _get_or_create(chat_id, today)
    today_plan = weekly["plan"][today.weekday()]
    preferences = DB.get_product_preferences(chat_id)
    pantry = DB.list_pantry_items(chat_id)
    shopping = format_shopping_list(weekly["shopping_list"], preferences, pantry)
    return _page(today_plan, weekly["plan"], shopping, user["conditions"], chat_id, pin)


@app.get("/semana", response_class=HTMLResponse)
def week_page(request: Request, pin: str | None = None, chat_id: int | None = None) -> Any:
    if gate := _login_redirect_if_needed(request, pin):
        return gate
    data = _app_data(request, pin, chat_id)
    if data["needs_onboarding"]:
        return _redirect("/onboarding", data["chat_id"], pin)
    body = _week_screen(data["weekly"]["plan"])
    return _app_shell("Semana", "semana", body)


@app.get("/compra", response_class=HTMLResponse)
def shopping_page(request: Request, pin: str | None = None, chat_id: int | None = None) -> Any:
    if gate := _login_redirect_if_needed(request, pin):
        return gate
    data = _app_data(request, pin, chat_id)
    if data["needs_onboarding"]:
        return _redirect("/onboarding", data["chat_id"], pin)
    shopping = format_shopping_list(
        data["weekly"]["shopping_list"],
        data["preferences"],
        data["pantry"],
    )
    sales_channel = str(data["user"]["profile"].get("disco_sc") or DEFAULT_SALES_CHANNEL)
    max_items = int(os.getenv("DISCO_SIMULATION_LIMIT", "14"))
    disco_lines, missing = simulate_disco_purchase(
        data["weekly"]["shopping_list"],
        sales_channel=sales_channel,
        max_items=max_items,
    )
    disco_text = format_disco_product_list(disco_lines, missing, sales_channel)
    week_start = week_start_for(data["today"]).isoformat()
    states = DB.get_shopping_item_states(data["chat_id"], week_start)
    body = _shopping_screen(data["chat_id"], pin, shopping, disco_text, states)
    return _app_shell("Compra", "compra", body)


@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request, pin: str | None = None, chat_id: int | None = None) -> Any:
    if gate := _login_redirect_if_needed(request, pin):
        return gate
    data = _app_data(request, pin, chat_id)
    if data["needs_onboarding"]:
        return _redirect("/onboarding", data["chat_id"], pin)
    body = _config_screen(data["chat_id"], pin, data["user"], data["pantry"], DB.list_offers(data["chat_id"]))
    return _app_shell("Config", "config", body)


@app.get("/platos", response_class=HTMLResponse)
def dishes_page(request: Request, pin: str | None = None, chat_id: int | None = None) -> Any:
    if gate := _login_redirect_if_needed(request, pin):
        return gate
    data = _app_data(request, pin, chat_id)
    if data["needs_onboarding"]:
        return _redirect("/onboarding", data["chat_id"], pin)
    body = _dishes_screen(data["chat_id"], pin, DB.list_community_dishes(data["chat_id"]))
    return _app_shell("Platos", "platos", body)


@app.get("/random", response_class=HTMLResponse)
def random_page(request: Request, pin: str | None = None, chat_id: int | None = None, filtro: str = "") -> Any:
    if gate := _login_redirect_if_needed(request, pin):
        return gate
    data = _app_data(request, pin, chat_id)
    if data["needs_onboarding"]:
        return _redirect("/onboarding", data["chat_id"], pin)
    body = _random_screen(data["chat_id"], pin, _random_meal(data["chat_id"], data["today"], filtro), filtro)
    return _app_shell("Random", "random", body)


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding_page(request: Request, pin: str | None = None, chat_id: int | None = None) -> Any:
    if gate := _login_redirect_if_needed(request, pin):
        return gate
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    user = DB.get_user(active_chat_id)
    return _app_shell(
        "Config inicial",
        "config",
        _onboarding_screen(active_chat_id, pin, user),
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/") -> HTMLResponse:
    return HTMLResponse(_login_screen(next))


@app.post("/login")
async def login_submit(request: Request) -> Any:
    form = _parse_form(await request.body())
    email = _form_str(form, "email").lower()
    password = _form_str(form, "password")
    next_path = _safe_next(_form_str(form, "next", "/"))
    account = DB.get_web_account(email)
    if not account or not _verify_password(password, str(account["password_hash"])):
        return HTMLResponse(_login_screen(next_path, "Email o contraseña incorrectos."), status_code=401)
    response = _session_response(next_path, int(account["chat_id"]), str(account["email"]))
    return response


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, next: str = "/") -> HTMLResponse:
    return HTMLResponse(_register_screen(_available_web_users(), next))


@app.post("/register")
async def register_submit(request: Request) -> Any:
    form = _parse_form(await request.body())
    email = _form_str(form, "email").lower()
    password = _form_str(form, "password")
    display_name = _form_str(form, "display_name") or None
    next_path = _safe_next(_form_str(form, "next", "/"))
    if "@" not in email or "." not in email:
        return HTMLResponse(_register_screen(_available_web_users(), next_path, "Ingresá un email válido."), status_code=400)
    if len(password) < 8:
        return HTMLResponse(_register_screen(_available_web_users(), next_path, "La contraseña debe tener al menos 8 caracteres."), status_code=400)
    chat_id = _form_int(form, "chat_id")
    if not chat_id:
        chat_id = _new_web_chat_id()
    if DB.get_web_account(email):
        return HTMLResponse(_register_screen(_available_web_users(), next_path, "Ese email ya existe."), status_code=409)
    debug_code = os.getenv("EMAIL_DEBUG_CODE", "").strip()
    code = debug_code if debug_code.isdigit() and len(debug_code) == 6 else f"{secrets.randbelow(1_000_000):06d}"
    try:
        _send_verification_email(email, code)
    except RuntimeError as exc:
        return HTMLResponse(_register_screen(_available_web_users(), next_path, str(exc)), status_code=503)
    DB.save_pending_web_account(
        email,
        chat_id,
        _hash_password(password),
        display_name,
        _hash_verification_code(email, code),
        (datetime.now(TZ if isinstance(TZ, ZoneInfo) else ZoneInfo("America/Argentina/Buenos_Aires")) + timedelta(minutes=15)).isoformat(),
    )
    return RedirectResponse(f"/verify?{urlencode({'email': email, 'next': next_path})}", status_code=303)


@app.get("/verify", response_class=HTMLResponse)
def verify_page(request: Request, email: str = "", next: str = "/") -> HTMLResponse:
    return HTMLResponse(_verify_screen(email, next))


@app.post("/verify")
async def verify_submit(request: Request) -> Any:
    form = _parse_form(await request.body())
    email = _form_str(form, "email").lower()
    code = _form_str(form, "code")
    next_path = _safe_next(_form_str(form, "next", "/"))
    pending = DB.get_pending_web_account(email)
    if not pending:
        return HTMLResponse(_verify_screen(email, next_path, "No hay una cuenta pendiente para ese email."), status_code=404)
    expires_at = datetime.fromisoformat(str(pending["expires_at"]))
    now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
    if now > expires_at:
        DB.delete_pending_web_account(email)
        return HTMLResponse(_verify_screen(email, next_path, "El código venció. Creá la cuenta de nuevo."), status_code=410)
    if not hmac.compare_digest(_hash_verification_code(email, code), str(pending["code_hash"])):
        return HTMLResponse(_verify_screen(email, next_path, "Código incorrecto."), status_code=401)
    if DB.get_web_account(email):
        DB.delete_pending_web_account(email)
        return HTMLResponse(_login_screen(next_path, "La cuenta ya estaba activada. Iniciá sesión."), status_code=409)
    chat_id = int(pending["chat_id"])
    DB.create_web_account(email, chat_id, str(pending["password_hash"]), pending.get("display_name"))
    if pending.get("display_name"):
        DB.update_profile(chat_id, {"nombre": pending["display_name"]})
    DB.delete_pending_web_account(email)
    return _session_response(next_path, chat_id, email)


@app.post("/logout")
async def logout_submit() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CHAT_COOKIE)
    return response


@app.post("/onboarding")
async def save_onboarding(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    DB.authorize_user(active_chat_id)
    DB.update_profile(
        active_chat_id,
        _clean_values(
            {
                "personas": _form_int(form, "personas", 2),
                "integrantes": _form_str(form, "integrantes"),
                "ciudad": _form_str(form, "ciudad"),
                "provincia": _form_str(form, "provincia"),
                "objetivo": _form_str(form, "objetivo"),
                "timezone": "America/Argentina/Buenos_Aires",
            }
        ),
    )
    DB.update_conditions(
        active_chat_id,
        _clean_values(
            {
                "evitar": _form_str(form, "evitar"),
                "preferencias": _form_str(form, "preferencias"),
                "estilo": _form_str(form, "estilo"),
                "compra": _form_str(form, "compra"),
            }
        ),
    )
    _clear_current_week(active_chat_id)
    _get_or_create(active_chat_id, _today())
    return _redirect("/semana", active_chat_id, pin)


@app.post("/actions/generate")
async def action_generate(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    _clear_current_week(active_chat_id)
    _get_or_create(active_chat_id, _today())
    return _redirect("/semana", active_chat_id, pin)


@app.post("/actions/profile")
async def action_profile(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    DB.update_profile(
        active_chat_id,
        _clean_values(
            {
                "personas": _form_int(form, "personas", 2),
                "integrantes": _form_str(form, "integrantes"),
                "ciudad": _form_str(form, "ciudad"),
                "provincia": _form_str(form, "provincia"),
                "objetivo": _form_str(form, "objetivo"),
                "timezone": "America/Argentina/Buenos_Aires",
            }
        ),
    )
    _clear_current_week(active_chat_id)
    return _redirect("/config", active_chat_id, pin)


@app.post("/actions/conditions")
async def action_conditions(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    DB.update_conditions(
        active_chat_id,
        _clean_values(
            {
                "preferencias": _form_str(form, "preferencias"),
                "evitar": _form_str(form, "evitar"),
                "restricciones": _form_str(form, "restricciones"),
                "reglas": _form_str(form, "reglas"),
                "chefs": _form_str(form, "chefs"),
                "estilo": _form_str(form, "estilo"),
                "compra": _form_str(form, "compra"),
            }
        ),
    )
    _clear_current_week(active_chat_id)
    return _redirect("/config", active_chat_id, pin)


@app.post("/actions/dishes")
async def action_create_dish(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    name = _form_str(form, "name")
    prep = _form_str(form, "prep")
    ingredients = _parse_ingredients(_form_str(form, "ingredients"))
    if name and prep:
        DB.create_community_dish(
            active_chat_id,
            name,
            _form_str(form, "slot", "cena"),
            _form_str(form, "protein") or "usuario",
            _parse_tags(_form_str(form, "tags")),
            ingredients,
            prep,
            public=_form_str(form, "public") == "on",
            active=_form_str(form, "active") == "on",
        )
        _clear_current_week(active_chat_id)
    return _redirect("/platos", active_chat_id, pin)


@app.post("/actions/rate_dish")
async def action_rate_dish(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    dish_id = _form_int(form, "dish_id")
    if dish_id:
        DB.rate_community_dish(
            dish_id,
            active_chat_id,
            _form_int(form, "rating", 5),
            _form_str(form, "note") or None,
        )
        _clear_current_week(active_chat_id)
    return _redirect("/platos", active_chat_id, pin)


@app.post("/actions/dislike_meal")
async def action_dislike_meal(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    slot = _form_str(form, "slot")
    scope = _form_str(form, "scope", "plato")
    today = _today()
    weekly = _get_or_create(active_chat_id, today)
    day_index = today.weekday()
    if slot not in weekly["plan"][day_index]["comidas"]:
        return _redirect("/", active_chat_id, pin)

    meal = weekly["plan"][day_index]["comidas"][slot]
    feedback_item = _feedback_item_for_scope(meal, scope)
    DB.add_feedback(active_chat_id, feedback_item, "negative", scope)

    user = DB.get_user(active_chat_id)
    conditions, blocked_names, favorite_names = _conditions_with_feedback(active_chat_id, user["conditions"])
    if scope != "plato":
        conditions["evitar"] = f"{conditions.get('evitar', '')} {feedback_item}".strip()
    _clear_current_week(active_chat_id)
    weekly = _get_or_create(active_chat_id, today)
    replacement, shopping = replace_meal(
        weekly["plan"],
        day_index,
        slot,
        user["profile"],
        conditions,
        DB.list_offers(active_chat_id),
        weather=weekly["plan"][day_index].get("clima"),
        custom_meals=DB.list_community_dishes(active_chat_id, active_only=True),
        blocked_meal_names=blocked_names,
        favorite_meal_names=favorite_names,
    )
    DB.save_weekly_plan(active_chat_id, week_start_for(today).isoformat(), weekly["plan"], shopping)
    DB.add_feedback(active_chat_id, str(replacement["nombre"]), "replacement", f"{scope}: {feedback_item}")
    return _redirect("/", active_chat_id, pin)


@app.post("/actions/favorite_meal")
async def action_favorite_meal(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    meal_name = _form_str(form, "meal_name")
    if meal_name:
        DB.add_feedback(active_chat_id, meal_name, "positive", "favorito")
    return _redirect("/", active_chat_id, pin)


@app.post("/actions/delete_feedback")
async def action_delete_feedback(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    feedback_id = _form_int(form, "feedback_id")
    if feedback_id:
        DB.delete_feedback(active_chat_id, feedback_id)
        _clear_current_week(active_chat_id)
    return _redirect("/config", active_chat_id, pin)


@app.post("/actions/stock")
async def action_stock(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    item = _form_str(form, "item")
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    if item.strip():
        DB.upsert_pantry_item(active_chat_id, item, _form_float(form, "quantity", 1))
        _clear_current_week(active_chat_id)
    return _redirect("/config", active_chat_id, pin)


@app.post("/actions/shopping_item")
async def action_shopping_item(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    item = _form_str(form, "item")
    leftover = _optional_form_float(form, "leftover_quantity")
    DB.upsert_shopping_item_state(
        active_chat_id,
        week_start_for(_today()).isoformat(),
        item,
        checked=_form_str(form, "checked") == "on",
        bought_quantity=_optional_form_float(form, "bought_quantity"),
        leftover_quantity=leftover,
        note=_form_str(form, "note") or None,
    )
    if item and leftover and leftover > 0:
        DB.upsert_pantry_item(active_chat_id, item, leftover)
    return _redirect("/compra", active_chat_id, pin)


@app.post("/actions/clear_shopping_state")
async def action_clear_shopping_state(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    DB.clear_shopping_item_states(active_chat_id, week_start_for(_today()).isoformat())
    return _redirect("/compra", active_chat_id, pin)


@app.post("/actions/clear_stock")
async def action_clear_stock(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    DB.clear_pantry(active_chat_id)
    _clear_current_week(active_chat_id)
    return _redirect("/config", active_chat_id, pin)


@app.post("/actions/offers")
async def action_offers(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    offer = _form_str(form, "offer")
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    if offer.strip():
        item, price, note = parse_offer(offer)
        DB.add_offer(active_chat_id, item, price, note)
        _clear_current_week(active_chat_id)
    return _redirect("/config", active_chat_id, pin)


@app.post("/actions/clear_offers")
async def action_clear_offers(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    chat_id = _form_int(form, "chat_id")
    pin = _form_str(form, "pin") or None
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    DB.clear_offers(active_chat_id)
    _clear_current_week(active_chat_id)
    return _redirect("/config", active_chat_id, pin)


@app.get("/api/menu")
def api_menu(request: Request, pin: str | None = None, chat_id: int | None = None) -> JSONResponse:
    _guard_web(request, pin)
    chat_id = _active_chat_id(chat_id, request)
    today = _today()
    weekly = _get_or_create(chat_id, today)
    return JSONResponse(
        {
            "today": weekly["plan"][today.weekday()],
            "week": weekly["plan"],
            "shopping_list": weekly["shopping_list"],
        }
    )


def _guard_web(request: Request, pin: str | None) -> None:
    if _has_web_access(request, pin):
        return
    raise HTTPException(status_code=401, detail="PIN requerido")


def _has_web_access(request: Request, pin: str | None) -> bool:
    if _session_chat_id(request) is not None:
        return True
    expected = os.getenv("DASHBOARD_PIN", "").strip()
    if not expected:
        return DB.count_web_accounts() == 0
    header_pin = request.headers.get("x-dashboard-pin")
    if pin == expected or header_pin == expected:
        return True
    return False


def _login_redirect_if_needed(request: Request, pin: str | None) -> RedirectResponse | None:
    if _has_web_access(request, pin):
        return None
    return RedirectResponse(f"/login?{urlencode({'next': request.url.path})}", status_code=303)


def _active_chat_id(requested_chat_id: int | None = None, request: Request | None = None) -> int:
    if request:
        session_chat_id = _session_chat_id(request)
        if session_chat_id and DB.is_authorized_user(session_chat_id):
            return session_chat_id
    if requested_chat_id and DB.is_authorized_user(requested_chat_id):
        return requested_chat_id
    configured = os.getenv("DEFAULT_CHAT_ID", "").strip()
    if configured:
        return int(configured)
    chat_ids = DB.list_chat_ids()
    if not chat_ids:
        raise HTTPException(
            status_code=503,
            detail="No hay usuario configurado. Usá el bot con /start o definí DEFAULT_CHAT_ID.",
        )
    return chat_ids[0]


def _app_data(request: Request, pin: str | None, chat_id: int | None) -> dict[str, Any]:
    _guard_web(request, pin)
    active_chat_id = _active_chat_id(chat_id, request)
    today = _today()
    user = DB.get_user(active_chat_id)
    needs_onboarding = _needs_onboarding(user)
    weekly = None if needs_onboarding else _get_or_create(active_chat_id, today)
    return {
        "chat_id": active_chat_id,
        "today": today,
        "needs_onboarding": needs_onboarding,
        "weekly": weekly,
        "today_plan": weekly["plan"][today.weekday()] if weekly else None,
        "user": user,
        "preferences": DB.get_product_preferences(active_chat_id),
        "pantry": DB.list_pantry_items(active_chat_id),
    }


def _needs_onboarding(user: dict[str, Any]) -> bool:
    return not user["profile"] or not user["conditions"]


def _redirect(path: str, chat_id: int, pin: str | None = None) -> RedirectResponse:
    return RedirectResponse(f"{path}{_context_query(chat_id, pin)}", status_code=303)


def _context_query(chat_id: int, pin: str | None = None) -> str:
    params: dict[str, str] = {"chat_id": str(chat_id)}
    if pin:
        params["pin"] = pin
    return "?" + urlencode(params)


def _session_response(next_path: str, chat_id: int, email: str) -> RedirectResponse:
    response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(SESSION_COOKIE, _signed_session_token(chat_id, email), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180)
    response.set_cookie(CHAT_COOKIE, str(chat_id), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180)
    return response


def _session_secret() -> str:
    secret = os.getenv("WEB_SESSION_SECRET") or os.getenv("DASHBOARD_PIN") or "local-dev-session"
    return secret


def _signed_session_token(chat_id: int, email: str) -> str:
    payload = f"{chat_id}:{email.lower()}"
    signature = hmac.new(_session_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def _session_chat_id(request: Request) -> int | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    parts = token.split(":")
    if len(parts) != 3:
        return None
    chat_id_raw, email, signature = parts
    payload = f"{chat_id_raw}:{email}"
    expected = hmac.new(_session_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    account = DB.get_web_account(email)
    if not account:
        return None
    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        return None
    if int(account["chat_id"]) != chat_id:
        return None
    return chat_id


def _cookie_chat_id(request: Request) -> int | None:
    raw = request.cookies.get(CHAT_COOKIE, "")
    try:
        return int(raw)
    except ValueError:
        return None


def _hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PASSWORD_ITERATIONS).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt, digest = stored_hash.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations).hex()
    return hmac.compare_digest(candidate, digest)


def _hash_verification_code(email: str, code: str) -> str:
    payload = f"{email.strip().lower()}:{code.strip()}"
    return hmac.new(_session_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _send_verification_email(email: str, code: str) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_FROM", user).strip()
    if os.getenv("EMAIL_DEBUG", "").strip() == "1":
        print(f"Verification code for {email}: {code}")
        return
    if not host or not sender:
        raise RuntimeError("Falta configurar SMTP_HOST y SMTP_FROM para enviar el código por email.")

    message = EmailMessage()
    message["Subject"] = "Tu código de activación de Mesa Lista"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "Tu código de activación es:\n\n"
        f"{code}\n\n"
        "Vence en 15 minutos. Si no pediste esta cuenta, ignorá este email."
    )

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.starttls()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(message)
    except OSError as exc:
        raise RuntimeError("No pude enviar el email de activación. Revisá la configuración SMTP.") from exc


def _new_web_chat_id() -> int:
    while True:
        chat_id = 900_000_000_000 + secrets.randbelow(99_999_999)
        if chat_id not in DB.list_chat_ids():
            return chat_id


def _available_web_users() -> list[dict[str, Any]]:
    users = []
    for chat_id in DB.list_chat_ids():
        user = DB.get_user(chat_id)
        profile = user["profile"]
        label = profile.get("nombre") or profile.get("familia") or profile.get("ciudad") or str(chat_id)
        users.append({"chat_id": chat_id, "label": str(label), "profile": profile})
    return users


def _safe_next(next_path: str) -> str:
    if next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/"


def _hidden_context(chat_id: int, pin: str | None = None) -> str:
    fields = [f'<input type="hidden" name="chat_id" value="{chat_id}">']
    if pin:
        fields.append(f'<input type="hidden" name="pin" value="{escape(pin, quote=True)}">')
    return "".join(fields)


def _clean_values(values: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                clean[key] = stripped
        elif value not in (None, ""):
            clean[key] = value
    return clean


def _form_str(form: Any, key: str, default: str = "") -> str:
    value = form.get(key, default)
    return str(value).strip() if value is not None else default


def _parse_form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _form_int(form: Any, key: str, default: int = 0) -> int:
    value = _form_str(form, key, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def _form_float(form: Any, key: str, default: float = 0) -> float:
    value = _form_str(form, key, str(default)).replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return default


def _optional_form_float(form: Any, key: str) -> float | None:
    value = _form_str(form, key)
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _parse_ingredients(raw: str) -> dict[str, float]:
    ingredients: dict[str, float] = {}
    for line in re.split(r"[\n;]+|,(?=\s*[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])", raw):
        part = line.strip()
        if not part:
            continue
        if "=" in part:
            name, qty = part.split("=", 1)
        elif ":" in part:
            name, qty = part.split(":", 1)
        else:
            chunks = part.rsplit(" ", 2)
            if len(chunks) == 3 and chunks[-1].lower() in {"g", "gr", "kg", "ml", "l", "u", "un", "unidad", "unidades"}:
                name = chunks[0]
                qty = f"{chunks[1]}{chunks[2]}"
            else:
                chunks = part.rsplit(" ", 1)
                if len(chunks) != 2:
                    continue
                name, qty = chunks
        name = name.strip().lower()
        qty_value = _quantity_number(qty)
        if name and qty_value > 0:
            ingredients[name] = qty_value
    return ingredients


def _quantity_number(raw: str) -> float:
    cleaned = raw.strip().lower().replace(",", ".").replace(" ", "")
    cleaned = cleaned.replace("unidades", "u").replace("unidad", "u").replace("un", "u").replace("gr", "g")
    multiplier = 1
    if cleaned.endswith("kg"):
        multiplier = 1000
        cleaned = cleaned[:-2]
    elif cleaned.endswith("g"):
        cleaned = cleaned[:-1]
    elif cleaned.endswith("l") and not cleaned.endswith("ml"):
        multiplier = 1000
        cleaned = cleaned[:-1]
    elif cleaned.endswith("ml"):
        cleaned = cleaned[:-2]
    elif cleaned.endswith("u"):
        cleaned = cleaned[:-1]
    if "/" in cleaned:
        numerator, denominator = cleaned.split("/", 1)
        try:
            return (float(numerator) / float(denominator)) * multiplier
        except ValueError:
            return 0
    try:
        return float(cleaned.strip()) * multiplier
    except ValueError:
        return 0


def _feedback_item_for_scope(meal: dict[str, Any], scope: str) -> str:
    if scope == "principal":
        return str(meal.get("proteina") or meal.get("nombre") or "").strip().lower()
    if scope == "acompañamiento":
        side_items = _side_ingredients(meal)
        if side_items:
            return " ".join(side_items).strip().lower()
    return str(meal.get("nombre") or "").strip().lower()


def _side_ingredients(meal: dict[str, Any]) -> list[str]:
    protein_words = _simple_words(str(meal.get("proteina") or ""))
    sides: list[str] = []
    for ingredient in (meal.get("ingredientes") or {}):
        ingredient_text = str(ingredient).strip().lower()
        ingredient_words = _simple_words(ingredient_text)
        if ingredient_words and ingredient_words.isdisjoint(protein_words):
            sides.append(ingredient_text)
    return sides


def _simple_words(text: str) -> set[str]:
    normalized = text.lower()
    replacements = str.maketrans("áéíóúüñ", "aeiouun")
    return {part for part in normalized.translate(replacements).replace("-", " ").split() if len(part) > 2}


def _parse_tags(raw: str) -> list[str]:
    return [tag.strip().lower() for tag in raw.replace(";", ",").split(",") if tag.strip()]


def _clear_current_week(chat_id: int) -> None:
    start = week_start_for(_today()).isoformat()
    with DB.connect() as conn:
        conn.execute("DELETE FROM weekly_plans WHERE chat_id = ? AND week_start = ?", (chat_id, start))


def _conditions_with_feedback(chat_id: int, conditions: dict[str, Any]) -> tuple[dict[str, Any], set[str], set[str]]:
    updated = dict(conditions)
    avoid_items: list[str] = []
    blocked_names: set[str] = set()
    favorite_names: set[str] = set()
    for row in DB.list_feedback(chat_id, "negative"):
        item = str(row["item"]).strip()
        scope = str(row.get("note") or "")
        if not item:
            continue
        if scope == "plato":
            blocked_names.add(item)
        else:
            avoid_items.append(item)
    if avoid_items:
        updated["evitar"] = f"{updated.get('evitar', '')} {' '.join(avoid_items)}".strip()
    for row in DB.list_feedback(chat_id, "positive"):
        item = str(row["item"]).strip()
        if item:
            favorite_names.add(item)
    return updated, blocked_names, favorite_names


def _random_meal(chat_id: int, today: date, filtro: str = "") -> dict[str, Any]:
    user = DB.get_user(chat_id)
    conditions, blocked_names, _favorite_names = _conditions_with_feedback(chat_id, user["conditions"])
    avoid_words = _simple_words(str(conditions.get("evitar", "")))
    filter_words = _simple_words(filtro)
    candidates: list[dict[str, Any]] = []
    for meal_type in ("almuerzo", "cena"):
        for meal in MEALS[meal_type]:
            haystack = _simple_words(f"{meal.name} {meal.protein} {' '.join(meal.ingredients)} {' '.join(meal.tags)}")
            if meal.name.lower() in blocked_names or haystack & avoid_words:
                continue
            if "delivery" in meal.tags:
                continue
            if filter_words and not _random_filter_matches(filter_words, haystack):
                continue
            candidates.append(
                {
                    "nombre": meal.name,
                    "prep": meal.prep,
                    "proteina": meal.protein,
                    "ingredientes": meal.ingredients,
                    "porciones": int(user["profile"].get("personas") or 2),
                }
            )
    for dish in DB.list_community_dishes(chat_id, active_only=True):
        if str(dish.get("slot", "")).lower() not in {"almuerzo", "cena"}:
            continue
        name = str(dish["name"])
        haystack = _simple_words(f"{name} {dish.get('protein', '')} {' '.join(dish.get('ingredients') or {})} {' '.join(dish.get('tags') or [])}")
        if name.lower() in blocked_names:
            continue
        if filter_words and not _random_filter_matches(filter_words, haystack):
            continue
        candidates.append(
            {
                "nombre": name,
                "prep": str(dish.get("prep") or "Preparar según la receta cargada."),
                "proteina": str(dish.get("protein") or "usuario"),
                "ingredientes": dish.get("ingredients") or {},
                "porciones": int(user["profile"].get("personas") or 2),
            }
        )
    if not candidates:
        fallback = MEALS["cena"][0]
        return {
            "nombre": fallback.name,
            "prep": fallback.prep,
            "proteina": fallback.protein,
            "ingredientes": fallback.ingredients,
            "porciones": int(user["profile"].get("personas") or 2),
        }
    seed = f"{chat_id}-{today.isoformat()}-{datetime.now(TZ if isinstance(TZ, ZoneInfo) else ZoneInfo('America/Argentina/Buenos_Aires')).timestamp()}-{secrets.randbelow(100000)}"
    return candidates[sum(ord(char) for char in seed) % len(candidates)]


def _random_filter_matches(filter_words: set[str], haystack: set[str]) -> bool:
    aliases = {
        "rapido": {"rapido", "air", "fryer", "plancha", "tacos", "hamburguesas", "omelette"},
        "rápido": {"rapido", "air", "fryer", "plancha", "tacos", "hamburguesas", "omelette"},
        "rico": {"gusto", "semanal", "chatarra", "milanesa", "pizza", "hamburguesas", "papas"},
        "chatarra": {"chatarra", "pizza", "hamburguesas", "papas", "milanesa", "empanadas"},
        "carne": {"carne", "asado", "vacio", "entraña", "bife", "lomo", "nalga", "cuadril", "roast"},
        "liviano": {"ensalada", "bowl", "verduras", "saludable", "merluza", "pollo", "omelette"},
        "pollo": {"pollo", "pechuga", "suprema", "muslo"},
        "milanesa": {"milanesa", "milanesas"},
    }
    wanted: set[str] = set()
    for word in filter_words:
        wanted |= aliases.get(word, {word})
    return bool(haystack & wanted)


def _get_or_create(chat_id: int, day: date) -> dict[str, Any]:
    start = week_start_for(day)
    weekly = DB.get_weekly_plan(chat_id, start.isoformat())
    if weekly and not _plan_needs_refresh(weekly["plan"]):
        return weekly
    user = DB.get_user(chat_id)
    offers = DB.list_offers(chat_id)
    conditions, blocked_names, favorite_names = _conditions_with_feedback(chat_id, user["conditions"])
    plan, shopping = generate_week(
        start,
        user["profile"],
        conditions,
        offers,
        fetch_weather_context(user["profile"]),
        DB.list_community_dishes(chat_id, active_only=True),
        blocked_names,
        favorite_names,
    )
    DB.save_weekly_plan(chat_id, start.isoformat(), plan, shopping)
    return {"plan": plan, "shopping_list": shopping}


def _plan_needs_refresh(plan: list[dict[str, Any]]) -> bool:
    if not plan:
        return True
    comidas = plan[0].get("comidas", {})
    return "colación 2" in comidas or "clima" not in plan[0]


def _today() -> date:
    return datetime.now(TZ if isinstance(TZ, ZoneInfo) else ZoneInfo("America/Argentina/Buenos_Aires")).date()


def _login_screen(next_path: str, error: str | None = None) -> str:
    error_html = f'<div class="login-error">{escape(error)}</div>' if error else ""
    style = _auth_style()
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#d84f35">
  <title>Ingresar · Mesa Lista</title>
  <style>
{style}
  </style>
</head>
<body>
  <main>
    <img class="brand-art" src="/brand-plate.svg" alt="">
    <div class="brand-mark">Mesa Lista</div>
    <h1>Qué comemos hoy</h1>
    <p>Tu menú, recetas y compra de la semana en un lugar simple.</p>
    {error_html}
    <form method="post" action="/login">
      <input type="hidden" name="next" value="{escape(_safe_next(next_path), quote=True)}">
      <label>Email
        <input name="email" type="email" autocomplete="email" required>
      </label>
      <label>Contraseña
        <input name="password" type="password" autocomplete="current-password" required>
      </label>
      <button type="submit">Entrar</button>
    </form>
    <p style="margin-top:16px;">¿Primera vez? <a href="/register?next={escape(_safe_next(next_path), quote=True)}">Crear cuenta</a></p>
  </main>
</body>
</html>"""


def _register_screen(users: list[dict[str, Any]], next_path: str, error: str | None = None) -> str:
    options = '<option value="">Crear perfil nuevo</option>' + "".join(
        f'<option value="{user["chat_id"]}">{escape(user["label"])} · {user["chat_id"]}</option>'
        for user in users
    )
    error_html = f'<div class="login-error">{escape(error)}</div>' if error else ""
    style = _auth_style()
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#d84f35">
  <title>Crear cuenta · Mesa Lista</title>
  <style>
{style}
  </style>
</head>
<body>
  <main>
    <img class="brand-art" src="/brand-plate.svg" alt="">
    <div class="brand-mark">Mesa Lista</div>
    <h1>Crear cuenta</h1>
    <p>Te mandamos un código al email y dejamos tu perfil listo para generar menús.</p>
    {error_html}
    <form method="post" action="/register">
      <input type="hidden" name="next" value="{escape(_safe_next(next_path), quote=True)}">
      <label>Nombre
        <input name="display_name" autocomplete="name">
      </label>
      <label>Email
        <input name="email" type="email" autocomplete="email" required>
      </label>
      <label>Contraseña
        <input name="password" type="password" autocomplete="new-password" minlength="8" required>
      </label>
      <label>Perfil
        <select name="chat_id">{options}</select>
      </label>
      <button type="submit">Enviar código</button>
    </form>
    <p style="margin-top:16px;"><a href="/login?next={escape(_safe_next(next_path), quote=True)}">Ya tengo cuenta</a></p>
  </main>
</body>
</html>"""


def _verify_screen(email: str, next_path: str, error: str | None = None) -> str:
    error_html = f'<div class="login-error">{escape(error)}</div>' if error else ""
    style = _auth_style()
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#d84f35">
  <title>Activar cuenta · Mesa Lista</title>
  <style>
{style}
  </style>
</head>
<body>
  <main>
    <img class="brand-art" src="/brand-plate.svg" alt="">
    <div class="brand-mark">Mesa Lista</div>
    <h1>Activar cuenta</h1>
    <p>Ingresá el código de 6 dígitos que enviamos a {escape(email or "tu email")}.</p>
    {error_html}
    <form method="post" action="/verify">
      <input type="hidden" name="next" value="{escape(_safe_next(next_path), quote=True)}">
      <label>Email
        <input name="email" type="email" value="{escape(email, quote=True)}" required>
      </label>
      <label>Código
        <input name="code" inputmode="numeric" pattern="[0-9]{{6}}" autocomplete="one-time-code" required>
      </label>
      <button type="submit">Activar cuenta</button>
    </form>
    <p style="margin-top:16px;"><a href="/register?next={escape(_safe_next(next_path), quote=True)}">Enviar otro código</a></p>
  </main>
</body>
</html>"""


def _app_shell(title: str, active: str, body: str) -> str:
    nav = _app_route_nav(active)
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#d84f35">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Mesa">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/icon.svg" type="image/svg+xml">
  <title>{escape(title)} · Mesa Lista</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #fff4e8;
      --ink: #241b18;
      --muted: #78685f;
      --line: #ead7c7;
      --card: #fffdf8;
      --accent: #d84f35;
      --accent-strong: #8f2f22;
      --accent-soft: #ffe2d8;
      --warm: #ffd166;
      --tomato: #c8452d;
      --sky: #eaf1ff;
      --blue: #2d6cdf;
      --plum: #53386f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at 10% 0, rgba(255, 209, 102, .32), transparent 270px), linear-gradient(180deg, #fff4e8 0, #fffdf8 260px, #f8efe5 100%);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .route-nav {{
      position: sticky;
      top: 0;
      z-index: 5;
      display: flex;
      gap: 8px;
      padding: 12px 18px;
      background: rgba(255, 244, 232, .95);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }}
    .route-nav a,
    .route-nav button {{
      flex: 1;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 11px 8px;
      background: #fffdf8;
      color: var(--ink);
      font-size: 13px;
      font-weight: 800;
      text-align: center;
      text-decoration: none;
      font-family: inherit;
      cursor: pointer;
    }}
    .route-nav a.active {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    .route-nav form {{
      flex: .82;
      margin: 0;
      display: flex;
    }}
    .route-nav button {{
      width: 100%;
      color: var(--tomato);
    }}
    .screen {{
      width: min(1180px, 100%);
      margin: 0 auto;
      padding: 24px;
    }}
    .screen-header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 20px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 16px;
    }}
    h1 {{
      margin: 0;
      font-size: 42px;
      line-height: 1;
      letter-spacing: 0;
      color: var(--plum);
    }}
    h2, h3, h4 {{ letter-spacing: 0; }}
    .meta {{
      color: var(--muted);
      font-size: 15px;
      margin-top: 8px;
    }}
    .time-pill {{
      background: linear-gradient(135deg, var(--accent-soft), var(--sky));
      color: var(--accent-strong);
      border: 1px solid #f1c6b7;
      border-radius: 8px;
      padding: 10px 14px;
      font-weight: 800;
      min-width: 86px;
      text-align: center;
    }}
    .time-pill span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      margin-top: 3px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 10px 28px rgba(47, 45, 39, .07);
    }}
    .card h2, .card h3 {{
      margin: 0 0 12px;
      font-size: 20px;
    }}
    .stack {{
      display: flex;
      flex-direction: column;
      gap: 14px;
    }}
    .week-card {{
      display: grid;
      grid-template-columns: 140px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
    }}
    .week-card strong {{
      color: var(--plum);
      font-size: 18px;
    }}
    .meal-row {{
      display: grid;
      grid-template-columns: 92px minmax(0, 1fr);
      gap: 10px;
      padding: 7px 0;
      border-top: 1px solid var(--line);
      font-size: 14px;
    }}
    .meal-row:first-child {{ border-top: 0; padding-top: 0; }}
    .meal-row span:first-child {{
      color: var(--muted);
      font-weight: 800;
    }}
    .shopping-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(340px, .8fr);
      gap: 16px;
      align-items: start;
    }}
    .shopping-column {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .shopping-group {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .shopping-group h4 {{
      margin: 0 0 10px;
      color: var(--accent-strong);
      font-size: 13px;
      text-transform: uppercase;
    }}
    .shopping-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .shopping-list li {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fffaf0;
    }}
    .shopping-list li.checked {{
      opacity: .62;
      background: #f4efe9;
    }}
    .buy-line {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      font-weight: 800;
      line-height: 1.25;
    }}
    .buy-line span:last-child {{
      color: var(--blue);
      text-align: right;
      flex-shrink: 0;
    }}
    .buy-notes {{
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }}
    .kv {{
      display: grid;
      grid-template-columns: 160px minmax(0, 1fr);
      gap: 8px 12px;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    .kv:first-of-type {{ border-top: 0; padding-top: 0; }}
    .kv dt {{
      color: var(--muted);
      font-weight: 800;
    }}
    .kv dd {{
      margin: 0;
      overflow-wrap: anywhere;
    }}
    .dish-list {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .dish-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffaf0;
      padding: 14px;
    }}
    .dish-card h3 {{
      margin: 0 0 8px;
      font-size: 19px;
    }}
    .random-stage {{
      position: relative;
      min-height: 300px;
      display: grid;
      place-items: center;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: linear-gradient(135deg, #fffdf8 0%, #fff4e8 54%, #eaf1ff 100%);
      margin-bottom: 16px;
    }}
    .filter-row {{
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding-bottom: 12px;
      margin-bottom: 4px;
    }}
    .filter-pill {{
      flex: 0 0 auto;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fffdf8;
      color: var(--plum);
      padding: 9px 12px;
      font-size: 13px;
      font-weight: 900;
      text-decoration: none;
    }}
    .filter-pill.active {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    .random-card {{
      position: relative;
      z-index: 1;
      width: min(560px, calc(100% - 28px));
      padding: 22px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 253, 248, .94);
      box-shadow: 0 18px 44px rgba(83, 56, 111, .14);
      animation: random-pop .5s ease-out both;
    }}
    .random-card h2 {{
      margin: 8px 0 10px;
      color: var(--plum);
      font-size: 32px;
      line-height: 1.05;
    }}
    .random-orbit {{
      position: absolute;
      width: 240px;
      height: 240px;
      border-radius: 50%;
      animation: random-spin 5s linear infinite;
    }}
    .random-orbit span {{
      position: absolute;
      width: 46px;
      height: 46px;
      border-radius: 50%;
      background: var(--warm);
    }}
    .random-orbit span:nth-child(1) {{ top: 0; left: 96px; }}
    .random-orbit span:nth-child(2) {{ right: 0; top: 96px; background: var(--accent); }}
    .random-orbit span:nth-child(3) {{ bottom: 0; left: 96px; background: var(--blue); }}
    .random-orbit span:nth-child(4) {{ left: 0; top: 96px; background: var(--plum); }}
    .ingredients, .steps {{
      margin: 0;
      padding-left: 20px;
      color: var(--ink);
      line-height: 1.45;
    }}
    .ingredients li, .steps li {{
      margin: 8px 0;
    }}
    @keyframes random-spin {{
      from {{ transform: rotate(0deg) scale(1); }}
      50% {{ transform: rotate(180deg) scale(1.08); }}
      to {{ transform: rotate(360deg) scale(1); }}
    }}
    @keyframes random-pop {{
      from {{ opacity: 0; transform: translateY(12px) scale(.96); }}
      to {{ opacity: 1; transform: translateY(0) scale(1); }}
    }}
    .badge-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 8px 0;
    }}
    .badge {{
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent-strong);
      padding: 4px 8px;
      font-size: 12px;
      font-weight: 850;
    }}
    .command {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffaf0;
      padding: 10px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    .learned-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffaf0;
      padding: 10px;
    }}
    .learned-row strong,
    .learned-row span,
    .learned-row small {{
      display: block;
    }}
    .learned-row strong {{
      color: var(--accent-strong);
      font-size: 12px;
      text-transform: uppercase;
    }}
    .learned-row small {{
      color: var(--muted);
      margin-top: 2px;
    }}
    form {{
      margin: 0;
    }}
    label {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 800;
    }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf8;
      color: var(--ink);
      font: inherit;
      font-size: 15px;
      font-weight: 600;
      padding: 10px 11px;
    }}
    textarea {{
      min-height: 92px;
      resize: vertical;
      line-height: 1.35;
    }}
    .form-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .form-grid .wide {{
      grid-column: 1 / -1;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }}
    .button {{
      border: 1px solid var(--accent);
      border-radius: 8px;
      background: linear-gradient(135deg, var(--accent), var(--accent-strong));
      color: #fff;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      padding: 10px 14px;
      font: inherit;
      font-weight: 850;
      text-decoration: none;
    }}
    .button.secondary {{
      background: #fffdf8;
      border-color: var(--line);
      color: var(--ink);
    }}
    .button.danger {{
      background: var(--tomato);
      border-color: var(--tomato);
    }}
    .inline-form {{
      margin-top: 10px;
      display: grid;
      grid-template-columns: 92px 92px minmax(120px, 1fr) auto;
      gap: 8px;
      align-items: end;
    }}
    .checkline {{
      display: flex;
      flex-direction: row;
      align-items: center;
      gap: 8px;
      color: var(--ink);
      font-size: 13px;
      font-weight: 850;
    }}
    .checkline input {{
      width: auto;
    }}
    .inline-form input {{
      min-width: 0;
      padding: 8px;
      font-size: 13px;
    }}
    .inline-form .button {{
      min-height: 36px;
      padding: 8px 10px;
      font-size: 13px;
    }}
    @media (max-width: 900px) {{
      .screen {{ padding: 18px; }}
      .route-nav {{ overflow-x: auto; padding: 10px 12px; }}
      .route-nav a, .route-nav button {{ flex: 0 0 auto; min-width: 82px; }}
      .route-nav form {{ flex: 0 0 auto; }}
      .screen-header {{ align-items: start; }}
      h1 {{ font-size: 34px; }}
      .grid, .shopping-layout, .dish-list {{ grid-template-columns: 1fr; }}
      .week-card, .form-grid {{ grid-template-columns: 1fr; }}
      .inline-form {{ grid-template-columns: 1fr; }}
      .kv {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  {nav}
  <main class="screen">
    <header class="screen-header">
      <div>
        <h1>{escape(title)}</h1>
      </div>
    </header>
    {body}
  </main>
  <script>
    const params = window.location.search;
    if (params) {{
      document.querySelectorAll('[data-route-link]').forEach((link) => {{
        link.href = link.getAttribute('href') + params;
      }});
    }}
    if ('serviceWorker' in navigator) {{
      window.addEventListener('load', () => {{
        navigator.serviceWorker.register('/sw.js').catch(() => undefined);
      }});
    }}
  </script>
</body>
</html>"""


def _app_route_nav(active: str) -> str:
    routes = [
        ("hoy", "/", "Hoy"),
        ("semana", "/semana", "Semana"),
        ("compra", "/compra", "Compra"),
        ("random", "/random", "Random"),
        ("platos", "/platos", "Platos"),
        ("config", "/config", "Config"),
    ]
    links = "".join(
        f'<a data-route-link href="{href}" class="{"active" if key == active else ""}">{label}</a>'
        for key, href, label in routes
    )
    logout = '<form method="post" action="/logout"><button type="submit">Salir</button></form>'
    return f'<nav class="route-nav" aria-label="Navegación">{links}{logout}</nav>'


def _week_screen(week: list[dict[str, Any]]) -> str:
    cards = []
    for day in week:
        rows = "".join(
            f"""
            <div class="meal-row">
              <span>{escape(slot.title())}</span>
              <span>{escape(day["comidas"][slot]["nombre"])}</span>
            </div>
            """
            for slot in SLOTS
        )
        cards.append(
            f"""
            <article class="card week-card">
              <div>
                <strong>{escape(day["dia"].title())}</strong>
                <div class="meta">{escape(day["fecha"])}</div>
                <div class="meta">{escape(format_weather_summary(day.get("clima")))}</div>
              </div>
              <div>{rows}</div>
            </article>
            """
        )
    return f'<section class="stack">{"".join(cards)}</section>'


def _shopping_screen(
    chat_id: int,
    pin: str | None,
    shopping: str,
    disco_text: str,
    states: dict[str, dict[str, Any]],
) -> str:
    hidden = _hidden_context(chat_id, pin)
    return f"""
    <section class="card">
      <h2>Compra editable</h2>
      <div class="actions">
        <form method="post" action="/actions/clear_shopping_state">
          {hidden}
          <button class="button secondary" type="submit">Limpiar checks de la semana</button>
        </form>
      </div>
      <div class="meta">Marcá comprado, ajustá cantidad real y cargá sobrante. El sobrante se guarda en stock para descontarlo después.</div>
    </section>
    <br>
    <section class="shopping-layout">
      <div class="shopping-column">
        <div class="card">
          <h2>Lista por rubro</h2>
          <div class="stack">{_shopping_markup(shopping, chat_id, pin, states, editable=True)}</div>
        </div>
      </div>
      <div class="shopping-column">
        <div class="card">
          <h2>Productos Disco</h2>
          <div class="stack">{_shopping_markup(disco_text)}</div>
        </div>
      </div>
    </section>
    """


def _config_screen(
    chat_id: int,
    pin: str | None,
    user: dict[str, Any],
    pantry: dict[str, float],
    offers: list[dict[str, str | None]],
) -> str:
    profile = user["profile"]
    conditions = user["conditions"]
    hidden = _hidden_context(chat_id, pin)
    stock = "".join(f"<div class=\"command\">{escape(item)} = {qty:g}</div>" for item, qty in pantry.items())
    if not stock:
        stock = "<div class=\"meta\">Sin stock cargado.</div>"
    offer_rows = "".join(
        f"<div class=\"command\">{escape(row['item'])} {escape(row.get('price') or '')} {escape(row.get('note') or '')}</div>"
        for row in offers
    )
    if not offer_rows:
        offer_rows = "<div class=\"meta\">Sin ofertas cargadas.</div>"
    learned_rows = _learned_feedback_markup(chat_id, pin)
    return f"""
    <section class="card">
      <h2>Acciones</h2>
      <div class="actions">
        <form method="post" action="/actions/generate">
          {hidden}
          <button class="button" type="submit">Regenerar semana</button>
        </form>
        <a class="button secondary" href="/semana{_context_query(chat_id, pin)}">Ver semana</a>
        <a class="button secondary" href="/compra{_context_query(chat_id, pin)}">Ver compra</a>
        <form method="post" action="/logout">
          <button class="button secondary" type="submit">Salir</button>
        </form>
      </div>
    </section>
    <br>
    <section class="grid">
      <article class="card">
        <h2>Perfil</h2>
        <form method="post" action="/actions/profile">
          {hidden}
          <div class="form-grid">
            <label>Personas
              <input name="personas" type="number" min="1" step="1" value="{escape(str(profile.get("personas", 2)), quote=True)}">
            </label>
            <label>Ciudad
              <input name="ciudad" value="{escape(str(profile.get("ciudad", "")), quote=True)}">
            </label>
            <label>Provincia
              <input name="provincia" value="{escape(str(profile.get("provincia", "")), quote=True)}">
            </label>
            <label>Objetivo
              <input name="objetivo" value="{escape(str(profile.get("objetivo", "")), quote=True)}">
            </label>
            <label class="wide">Integrantes
              <textarea name="integrantes">{escape(str(profile.get("integrantes", "")))}</textarea>
            </label>
          </div>
          <div class="actions">
            <button class="button" type="submit">Guardar perfil</button>
          </div>
        </form>
      </article>
      <article class="card">
        <h2>Reglas</h2>
        <form method="post" action="/actions/conditions">
          {hidden}
          <div class="form-grid">
            <label class="wide">Preferencias
              <textarea name="preferencias">{escape(str(conditions.get("preferencias", "")))}</textarea>
            </label>
            <label class="wide">Evitar
              <textarea name="evitar">{escape(str(conditions.get("evitar", "")))}</textarea>
            </label>
            <label class="wide">Restricciones
              <textarea name="restricciones">{escape(str(conditions.get("restricciones", "")))}</textarea>
            </label>
            <label class="wide">Reglas de menú
              <textarea name="reglas">{escape(str(conditions.get("reglas", "")))}</textarea>
            </label>
            <label class="wide">Chefs de inspiración
              <input name="chefs" value="{escape(str(conditions.get("chefs", "")), quote=True)}">
            </label>
            <label class="wide">Estilo de platos
              <textarea name="estilo">{escape(str(conditions.get("estilo", "")))}</textarea>
            </label>
            <label class="wide">Compra
              <textarea name="compra">{escape(str(conditions.get("compra", "")))}</textarea>
            </label>
          </div>
          <div class="actions">
            <button class="button" type="submit">Guardar reglas</button>
          </div>
        </form>
      </article>
      <article class="card">
        <h2>Stock</h2>
        <div class="stack">{stock}</div>
        <form method="post" action="/actions/stock">
          {hidden}
          <div class="form-grid">
            <label>Producto
              <input name="item" placeholder="arroz, huevos, leche">
            </label>
            <label>Cantidad
              <input name="quantity" type="number" min="0" step="0.1" value="1">
            </label>
          </div>
          <div class="actions">
            <button class="button" type="submit">Agregar stock</button>
          </div>
        </form>
        <form method="post" action="/actions/clear_stock">
          {hidden}
          <div class="actions">
            <button class="button danger" type="submit">Vaciar stock</button>
          </div>
        </form>
      </article>
      <article class="card">
        <h2>Ofertas</h2>
        <div class="stack">{offer_rows}</div>
        <form method="post" action="/actions/offers">
          {hidden}
          <label>Oferta
            <input name="offer" placeholder="hamburguesas Paty $7550 pack 4">
          </label>
          <div class="actions">
            <button class="button" type="submit">Agregar oferta</button>
          </div>
        </form>
        <form method="post" action="/actions/clear_offers">
          {hidden}
          <div class="actions">
            <button class="button danger" type="submit">Limpiar ofertas</button>
          </div>
        </form>
      </article>
      <article class="card">
        <h2>Gustos aprendidos</h2>
        <p class="meta">Podés borrar cualquier bloqueo o favorito para que el menú vuelva a considerarlo.</p>
        <div class="stack">{learned_rows}</div>
      </article>
      <article class="card">
        <h2>Datos técnicos</h2>
        <dl class="kv">
          <dt>Usuario</dt><dd>{chat_id}</dd>
          <dt>Zona horaria</dt><dd>America/Argentina/Buenos_Aires</dd>
          <dt>App</dt><dd>PWA instalada desde el navegador</dd>
        </dl>
      </article>
    </section>
    """


def _dishes_screen(chat_id: int, pin: str | None, dishes: list[dict[str, Any]]) -> str:
    hidden = _hidden_context(chat_id, pin)
    dish_cards = "".join(_dish_card(chat_id, pin, dish) for dish in dishes)
    if not dish_cards:
        dish_cards = '<div class="meta">Todavía no hay platos cargados.</div>'
    return f"""
    <section class="grid">
      <article class="card">
        <h2>Crear plato</h2>
        <form method="post" action="/actions/dishes">
          {hidden}
          <div class="form-grid">
            <label class="wide">Nombre
              <input name="name" placeholder="Ej: Pollo al limón con papas">
            </label>
            <label>Momento
              <select name="slot">
                <option value="almuerzo">Almuerzo</option>
                <option value="cena">Cena</option>
                <option value="desayuno">Desayuno</option>
                <option value="merienda">Merienda</option>
                <option value="colación">Colación</option>
              </select>
            </label>
            <label>Proteína principal
              <input name="protein" placeholder="pollo, nalga, huevo, lentejas">
            </label>
            <label class="wide">Ingredientes por porción
              <textarea name="ingredients" placeholder="pollo=180&#10;papa=250&#10;limon=0.5"></textarea>
            </label>
            <label class="wide">Receta / preparación
              <textarea name="prep" placeholder="Dorar el pollo, sumar limón, cocinar papas en horno o air fryer..."></textarea>
            </label>
            <label class="wide">Tags
              <input name="tags" placeholder="proteico, rápido, gusto semanal">
            </label>
            <label class="checkline"><input name="public" type="checkbox" checked> Visible para otros</label>
            <label class="checkline"><input name="active" type="checkbox" checked> Usarlo en mi menú</label>
          </div>
          <div class="actions">
            <button class="button" type="submit">Crear plato</button>
          </div>
        </form>
      </article>
      <article class="card">
        <h2>Cómo impacta</h2>
        <dl class="kv">
          <dt>Compra</dt><dd>Los ingredientes del plato se suman a la compra semanal si el menú lo usa.</dd>
          <dt>Menú</dt><dd>Los platos activos entran como candidatos al regenerar la semana.</dd>
          <dt>Puntaje</dt><dd>Los platos mejor puntuados tienen más prioridad.</dd>
        </dl>
      </article>
    </section>
    <br>
    <section class="card">
      <h2>Mis platos y comunidad</h2>
      <p class="meta">Acá aparecen tus platos y los platos marcados como visibles para otros usuarios.</p>
      <div class="dish-list">{dish_cards}</div>
    </section>
    """


def _learned_feedback_markup(chat_id: int, pin: str | None) -> str:
    rows = [
        row
        for row in DB.list_feedback(chat_id)
        if row["sentiment"] in {"negative", "positive"}
    ]
    if not rows:
        return '<div class="meta">Todavía no hay gustos aprendidos.</div>'
    labels = {
        "negative": "Evitar",
        "positive": "Favorito",
    }
    html = []
    for row in rows[:30]:
        hidden = _hidden_context(chat_id, pin)
        html.append(
            f"""
            <div class="learned-row">
              <div>
                <strong>{escape(labels.get(str(row["sentiment"]), str(row["sentiment"])))}</strong>
                <span>{escape(str(row["item"]))}</span>
                <small>{escape(str(row.get("note") or ""))}</small>
              </div>
              <form method="post" action="/actions/delete_feedback">
                {hidden}
                <input type="hidden" name="feedback_id" value="{int(row["id"])}">
                <button class="button secondary" type="submit">Borrar</button>
              </form>
            </div>
            """
        )
    return "".join(html)


def _random_screen(chat_id: int, pin: str | None, meal: dict[str, Any], filtro: str = "") -> str:
    hidden = _hidden_context(chat_id, pin)
    recipe = _recipe_for("random", meal, [])
    ingredients = "".join(f"<li>{escape(item)}</li>" for item in recipe["ingredients"])
    steps = "".join(f"<li>{escape(step)}</li>" for step in recipe["steps"])
    def filter_href(value: str) -> str:
        params: dict[str, str | int] = {"chat_id": chat_id, "filtro": value}
        if pin:
            params["pin"] = pin
        return f"/random?{urlencode(params)}"

    filters = "".join(
        f'<a class="filter-pill {"active" if filtro == value else ""}" href="{escape(filter_href(value), quote=True)}">{label}</a>'
        for value, label in (
            ("rapido", "Rápido"),
            ("rico", "Rico"),
            ("carne", "Carne"),
            ("liviano", "Liviano"),
            ("chatarra", "Chatarra"),
            ("milanesa", "Milanesa"),
        )
    )
    return f"""
    <section class="filter-row">{filters}</section>
    <section class="random-stage">
      <div class="random-orbit" aria-hidden="true">
        <span></span><span></span><span></span><span></span>
      </div>
      <article class="random-card">
        <div class="slot">Random rico</div>
        <h2>{escape(str(meal["nombre"]))}</h2>
        <p>{escape(_short_description(meal))}</p>
        <div class="actions">
          <form method="get" action="/random">
            {hidden}
            <input type="hidden" name="filtro" value="{escape(filtro, quote=True)}">
            <button class="button" type="submit">Tirar otra</button>
          </form>
        </div>
      </article>
    </section>
    <section class="grid">
      <article class="card">
        <h2>Ingredientes</h2>
        <ul class="ingredients">{ingredients}</ul>
      </article>
      <article class="card">
        <h2>Paso a paso</h2>
        <ol class="steps">{steps}</ol>
      </article>
    </section>
    """


def _dish_card(chat_id: int, pin: str | None, dish: dict[str, Any]) -> str:
    hidden = _hidden_context(chat_id, pin)
    tags = "".join(f'<span class="badge">{escape(str(tag))}</span>' for tag in dish.get("tags", []))
    ingredients = ", ".join(
        f"{name}: {format_quantity(str(name), float(qty))}"
        for name, qty in (dish.get("ingredients") or {}).items()
    )
    if not ingredients:
        ingredients = "sin ingredientes cargados"
    rating = f'{float(dish.get("avg_rating") or 0):.1f}'.rstrip("0").rstrip(".")
    visibility = "público" if dish.get("public") else "privado"
    active = "activo" if dish.get("active") else "inactivo"
    return f"""
    <article class="dish-card">
      <h3>{escape(str(dish["name"]))}</h3>
      <div class="meta">{escape(str(dish["slot"]).title())} · {escape(str(dish["protein"]))} · {visibility} · {active}</div>
      <div class="badge-row">{tags}</div>
      <div class="buy-notes">Ingredientes: {escape(ingredients)}</div>
      <p class="meta">{escape(str(dish["prep"]))}</p>
      <div class="meta">Puntaje: {rating}/5 · {int(dish.get("rating_count") or 0)} votos</div>
      <form class="inline-form" method="post" action="/actions/rate_dish">
        {hidden}
        <input type="hidden" name="dish_id" value="{int(dish["id"])}">
        <label>Puntos
          <input name="rating" type="number" min="1" max="5" step="1" value="5">
        </label>
        <label>Nota
          <input name="note" placeholder="rico, repetir, ajustar...">
        </label>
        <button class="button" type="submit">Puntuar</button>
      </form>
    </article>
    """


def _onboarding_screen(chat_id: int, pin: str | None, user: dict[str, Any]) -> str:
    profile = user["profile"]
    conditions = user["conditions"]
    hidden = _hidden_context(chat_id, pin)
    return f"""
    <section class="card">
      <h2>Primera configuración</h2>
      <p class="meta">Estas 5 respuestas dejan armada la base del menú, la compra y las recetas para este usuario.</p>
      <form method="post" action="/onboarding">
        {hidden}
        <div class="form-grid">
          <label>1. Cuántos comen
            <input name="personas" type="number" min="1" step="1" value="{escape(str(profile.get("personas", 2)), quote=True)}">
          </label>
          <label>Ciudad
            <input name="ciudad" value="{escape(str(profile.get("ciudad", "Mar del Plata")), quote=True)}">
          </label>
          <label>Provincia
            <input name="provincia" value="{escape(str(profile.get("provincia", "Buenos Aires")), quote=True)}">
          </label>
          <label>2. Objetivo
            <input name="objetivo" value="{escape(str(profile.get("objetivo", "bajar grasa y sostener proteína")), quote=True)}">
          </label>
          <label class="wide">Integrantes
            <textarea name="integrantes">{escape(str(profile.get("integrantes", "2 adultos")))}</textarea>
          </label>
          <label class="wide">3. Qué evitar o cuidar
            <textarea name="evitar">{escape(str(conditions.get("evitar", "kiwi, mucho lactosa, cerdo frecuente")))}</textarea>
          </label>
          <label class="wide">4. Qué les gusta comer
            <textarea name="preferencias">{escape(str(conditions.get("preferencias", "comida argentina, carne, milanesas, pollo, pastas, arroz medido, verduras, frutas, postres Danette o Copa Cindor en oferta")))}</textarea>
          </label>
          <label class="wide">Estilo de cocina
            <textarea name="estilo">{escape(str(conditions.get("estilo", "variado, rico, saludable en semana, más gustoso el finde, recetas para 2 porciones")))}</textarea>
          </label>
          <label class="wide">5. Cómo comprar
            <textarea name="compra">{escape(str(conditions.get("compra", "armar compra semanal por rubro, preferir ofertas, paquetes de 500 g o 1 kg cuando corresponda, registrar sobrantes para la semana siguiente")))}</textarea>
          </label>
        </div>
        <div class="actions">
          <button class="button" type="submit">Guardar y generar semana</button>
        </div>
      </form>
    </section>
    """


def _dict_details(values: dict[str, Any]) -> str:
    if not values:
        return '<div class="meta">Sin datos.</div>'
    rows = "".join(
        f"<dt>{escape(str(key))}</dt><dd>{escape(str(value))}</dd>"
        for key, value in values.items()
    )
    return f'<dl class="kv">{rows}</dl>'


def _shopping_markup(
    shopping: str,
    chat_id: int | None = None,
    pin: str | None = None,
    states: dict[str, dict[str, Any]] | None = None,
    editable: bool = False,
) -> str:
    groups: list[tuple[str, list[str]]] = []
    current_title = "Varios"
    current_items: list[str] = []

    def flush() -> None:
        nonlocal current_items
        if current_items:
            groups.append((current_title, current_items))
            current_items = []

    for raw_line in shopping.splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("-"):
            flush()
            current_title = line
            continue
        current_items.append(
            _shopping_item_markup(
                line.removeprefix("- ").strip(),
                chat_id=chat_id,
                pin=pin,
                states=states or {},
                editable=editable,
            )
        )
    flush()

    return "\n".join(
        f"""
        <section class="shopping-group">
          <h4>{escape(title)}</h4>
          <ul class="shopping-list">{''.join(items)}</ul>
        </section>
        """
        for title, items in groups
    )


def _shopping_item_markup(
    line: str,
    chat_id: int | None = None,
    pin: str | None = None,
    states: dict[str, dict[str, Any]] | None = None,
    editable: bool = False,
) -> str:
    main, *notes = [part.strip() for part in line.split(" | ")]
    if ": comprar " in main:
        item, quantity = main.split(": comprar ", 1)
    elif ": " in main:
        item, quantity = main.split(": ", 1)
    else:
        item, quantity = main, ""
    notes_html = f"<div class=\"buy-notes\">{escape(' · '.join(notes))}</div>" if notes else ""
    normalized = item.strip().lower()
    state = (states or {}).get(normalized, {})
    checked = bool(state.get("checked"))
    form_html = ""
    if editable and chat_id is not None:
        hidden = _hidden_context(chat_id, pin) + f'<input type="hidden" name="item" value="{escape(normalized, quote=True)}">'
        checked_attr = " checked" if checked else ""
        bought = "" if state.get("bought_quantity") is None else f'{state["bought_quantity"]:g}'
        leftover = "" if state.get("leftover_quantity") is None else f'{state["leftover_quantity"]:g}'
        note = escape(str(state.get("note") or ""), quote=True)
        form_html = f"""
        <form class="inline-form" method="post" action="/actions/shopping_item">
          {hidden}
          <label class="checkline"><input name="checked" type="checkbox"{checked_attr}> Comprado</label>
          <label>Cant.
            <input name="bought_quantity" type="number" min="0" step="0.1" value="{bought}">
          </label>
          <label>Sobrante
            <input name="leftover_quantity" type="number" min="0" step="0.1" value="{leftover}">
          </label>
          <label>Nota
            <input name="note" value="{note}">
          </label>
          <button class="button" type="submit">Guardar</button>
        </form>
        """
    return (
        f'<li class="{"checked" if checked else ""}">'
        f"<div class=\"buy-line\"><span>{escape(item)}</span><span>{escape(quantity)}</span></div>"
        f"{notes_html}"
        f"{form_html}"
        "</li>"
    )


def _page(
    today_plan: dict[str, Any],
    week: list[dict[str, Any]],
    shopping: str,
    conditions: dict[str, Any],
    chat_id: int,
    pin: str | None,
) -> str:
    meals = today_plan["comidas"]
    chef_preferences = _chef_preferences(conditions)
    recipes = [_recipe_for(slot, meals[slot], chef_preferences) for slot in SLOTS]
    hidden = _hidden_context(chat_id, pin)
    meal_cards = "\n".join(
        f"""
        <article class="meal">
          <div class="slot">{escape(slot.title())}</div>
          <h2>{escape(meals[slot]["nombre"])}</h2>
          <p>{escape(_short_description(meals[slot]))}</p>
          <div class="meal-actions">
            <button class="recipe-button" type="button" data-recipe="{index}">Ver receta</button>
            <form method="post" action="/actions/dislike_meal">
              {hidden}
              <input type="hidden" name="slot" value="{escape(slot, quote=True)}">
              <input type="hidden" name="scope" value="plato">
              <button class="swap-button" type="submit">No más este plato</button>
            </form>
            <form method="post" action="/actions/favorite_meal">
              {hidden}
              <input type="hidden" name="meal_name" value="{escape(str(meals[slot]["nombre"]), quote=True)}">
              <button class="favorite-button" type="submit">Me gustó</button>
            </form>
            <div class="split-actions">
              <form method="post" action="/actions/dislike_meal">
                {hidden}
                <input type="hidden" name="slot" value="{escape(slot, quote=True)}">
                <input type="hidden" name="scope" value="principal">
                <button class="mini-button" type="submit">Cambiar principal</button>
              </form>
              <form method="post" action="/actions/dislike_meal">
                {hidden}
                <input type="hidden" name="slot" value="{escape(slot, quote=True)}">
                <input type="hidden" name="scope" value="acompañamiento">
                <button class="mini-button" type="submit">Cambiar acomp.</button>
              </form>
            </div>
          </div>
        </article>
        """
        for index, slot in enumerate(SLOTS)
    )
    week_rows = "\n".join(
        f"""
        <div class="day">
          <strong>{escape(day["dia"].title())}</strong>
          <span>{escape(day["comidas"]["almuerzo"]["nombre"])}</span>
          <span>{escape(day["comidas"]["cena"]["nombre"])}</span>
        </div>
        """
        for day in week
    )
    shopping_sections = _shopping_markup(shopping)
    local_now = datetime.now(TZ if isinstance(TZ, ZoneInfo) else ZoneInfo("America/Argentina/Buenos_Aires"))
    now = local_now.strftime("%H:%M")
    recipes_json = escape(json.dumps(recipes, ensure_ascii=False), quote=False)
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="900">
  <meta name="theme-color" content="#d84f35">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Mesa">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/icon.svg" type="image/svg+xml">
  <title>Mesa Lista · Hoy</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #fff4e8;
      --ink: #241b18;
      --muted: #78685f;
      --line: #ead7c7;
      --card: #fffdf8;
      --accent: #d84f35;
      --accent-strong: #8f2f22;
      --accent-soft: #ffe2d8;
      --warm: #ffd166;
      --tomato: #c8452d;
      --sky: #eaf1ff;
      --blue: #2d6cdf;
      --plum: #53386f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at 10% 0, rgba(255, 209, 102, .35), transparent 260px), linear-gradient(180deg, #fff4e8 0, #fffdf8 260px, #f8efe5 100%);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(340px, .65fr);
      gap: 24px;
      padding: 28px;
    }}
    .app-nav {{
      position: sticky;
      top: 0;
      z-index: 4;
      display: flex;
      gap: 8px;
      padding: 10px 18px;
      background: rgba(255, 244, 232, .94);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }}
    .app-nav a,
    .app-nav button {{
      flex: 1;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 8px;
      background: #fffdf8;
      color: var(--ink);
      font-size: 13px;
      font-weight: 800;
      text-align: center;
      text-decoration: none;
      font-family: inherit;
      cursor: pointer;
    }}
    .app-nav form {{
      flex: .82;
      margin: 0;
      display: flex;
    }}
    .app-nav button {{
      width: 100%;
      color: var(--tomato);
    }}
    .app-nav a:first-child {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 22px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
    }}
    .today-visual {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 150px;
      gap: 16px;
      align-items: end;
    }}
    .brand-chip {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
      color: var(--accent-strong);
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
    }}
    .plate-art {{
      width: 150px;
      aspect-ratio: 1 / 1;
      object-fit: contain;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 12px 28px rgba(83, 56, 111, .12);
      background: #fff4e8;
    }}
    h1 {{
      margin: 0;
      font-size: 44px;
      line-height: 1;
      letter-spacing: 0;
      color: var(--plum);
    }}
    .date {{
      color: var(--muted);
      font-size: 18px;
      margin-top: 8px;
    }}
    .time {{
      background: linear-gradient(135deg, var(--accent-soft), var(--sky));
      color: var(--accent-strong);
      border: 1px solid #f1c6b7;
      border-radius: 8px;
      padding: 10px 14px;
      font-weight: 700;
      min-width: 76px;
      text-align: center;
    }}
    .tz {{
      display: block;
      margin-top: 3px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }}
    .meals {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .meal, .panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 10px 28px rgba(47, 45, 39, .07);
    }}
    .meal {{
      min-height: 176px;
      padding: 18px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .slot {{
      color: var(--accent-strong);
      font-size: 13px;
      font-weight: 800;
      text-transform: uppercase;
    }}
    h2 {{
      margin: 10px 0;
      font-size: clamp(20px, 2.4vw, 26px);
      line-height: 1.12;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }}
    p {{
      margin: 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.35;
    }}
    button {{
      font: inherit;
    }}
    .recipe-button {{
      align-self: flex-start;
      margin-top: 16px;
      border: 1px solid var(--accent);
      background: linear-gradient(135deg, var(--accent), var(--accent-strong));
      color: #fff;
      border-radius: 8px;
      padding: 10px 14px;
      font-weight: 800;
      cursor: pointer;
    }}
    .meal-actions {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-top: 16px;
    }}
    .meal-actions form {{
      margin: 0;
    }}
    .recipe-button, .swap-button, .mini-button, .favorite-button {{
      width: 100%;
    }}
    .swap-button, .mini-button, .favorite-button {{
      border: 1px solid var(--line);
      background: #fff7ef;
      color: var(--plum);
      border-radius: 8px;
      padding: 9px 12px;
      font-weight: 850;
      cursor: pointer;
    }}
    .favorite-button {{
      background: #fff3c4;
      border-color: #f1cf73;
      color: #6b4b00;
    }}
    .split-actions {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .mini-button {{
      min-height: 40px;
      font-size: 12px;
      color: var(--accent-strong);
    }}
    .recipe-button:active, .swap-button:active, .mini-button:active {{
      transform: translateY(1px);
    }}
    aside {{
      display: flex;
      flex-direction: column;
      gap: 16px;
      min-height: 0;
    }}
    .panel {{
      padding: 18px;
      overflow: hidden;
    }}
    .panel h3 {{
      margin: 0 0 14px;
      font-size: 20px;
      letter-spacing: 0;
    }}
    .day {{
      display: grid;
      grid-template-columns: 90px minmax(0, 1fr);
      gap: 4px 12px;
      border-top: 1px solid var(--line);
      padding: 10px 0;
      font-size: 14px;
    }}
    .day:first-of-type {{ border-top: 0; }}
    .day strong {{ color: var(--plum); grid-row: span 2; }}
    .day span {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .shopping {{
      max-height: 360px;
      overflow: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding-right: 4px;
    }}
    .shopping-group {{
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }}
    .shopping-group:first-child {{ border-top: 0; padding-top: 0; }}
    .shopping-group h4 {{
      margin: 0 0 8px;
      color: var(--plum);
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .shopping-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .shopping-list li {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 10px;
      background: #fffaf0;
      font-size: 14px;
      line-height: 1.25;
    }}
    .buy-line {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      font-weight: 800;
    }}
    .buy-line span:last-child {{
      color: var(--blue);
      text-align: right;
      flex-shrink: 0;
    }}
    .buy-notes {{
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.3;
    }}
    .highlight {{
      background: var(--warm);
      border-radius: 8px;
      padding: 3px 8px;
      display: inline-block;
    }}
    .modal {{
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: rgba(28, 27, 24, .42);
      z-index: 10;
    }}
    .modal.open {{
      display: flex;
    }}
    .recipe-dialog {{
      width: min(900px, 100%);
      max-height: min(86vh, 900px);
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 24px 70px rgba(28, 27, 24, .28);
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}
    .recipe-header {{
      padding: 22px 24px 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }}
    .recipe-header h2 {{
      margin: 4px 0 0;
      font-size: 30px;
    }}
    .close-button {{
      border: 1px solid var(--line);
      background: #fffdf8;
      color: var(--ink);
      border-radius: 8px;
      min-width: 44px;
      height: 44px;
      font-size: 24px;
      line-height: 1;
      cursor: pointer;
    }}
    .recipe-body {{
      padding: 20px 24px 24px;
      overflow: auto;
      display: grid;
      grid-template-columns: minmax(220px, .75fr) minmax(0, 1.25fr);
      gap: 22px;
    }}
    .recipe-body h3 {{
      margin: 0 0 12px;
      font-size: 18px;
    }}
    .ingredients, .steps {{
      margin: 0;
      padding-left: 20px;
    }}
    .ingredients li, .steps li {{
      font-size: 16px;
      line-height: 1.35;
      margin: 10px 0;
    }}
    .tip {{
      margin-top: 18px;
      padding: 12px;
      border-radius: 8px;
      background: var(--accent-soft);
      color: var(--accent-strong);
      font-weight: 700;
      line-height: 1.3;
    }}
    @media (max-width: 900px) {{
      main {{ grid-template-columns: 1fr; padding: 18px; }}
      .app-nav {{ overflow-x: auto; padding: 10px 12px; }}
      .app-nav a, .app-nav button {{ flex: 0 0 auto; min-width: 82px; }}
      .app-nav form {{ flex: 0 0 auto; }}
      .meals {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 34px; }}
      .recipe-body {{ grid-template-columns: 1fr; }}
      header {{ align-items: start; }}
      .today-visual {{ grid-template-columns: 1fr 86px; align-items: start; }}
      .plate-art {{ width: 86px; }}
    }}
    @media (max-width: 520px) {{
      main {{ padding: 14px; }}
      header {{ gap: 10px; }}
      .today-visual {{ grid-template-columns: 1fr; }}
      .plate-art {{ display: none; }}
      .time {{ min-width: 68px; padding: 9px 10px; }}
    }}
  </style>
</head>
<body>
  <nav class="app-nav" aria-label="Navegación">
    <a href="/">Hoy</a>
    <a href="/semana">Semana</a>
    <a href="/compra">Compra</a>
    <a href="/random">Random</a>
    <a href="/platos">Platos</a>
    <a href="/config">Config</a>
    <form method="post" action="/logout"><button type="submit">Salir</button></form>
  </nav>
  <main>
    <section id="hoy">
      <header>
        <div class="today-visual">
          <div>
            <div class="brand-chip">Mesa Lista</div>
            <h1>Menú de hoy</h1>
            <div class="date">{escape(today_plan["dia"].title())} · {escape(today_plan["fecha"])}</div>
            <div class="date">{escape(format_weather_summary(today_plan.get("clima")))}</div>
          </div>
          <img class="plate-art" src="/brand-plate.svg" alt="">
        </div>
        <div class="time">{escape(now)}<span class="tz">GMT-3</span></div>
      </header>
      <section class="meals">{meal_cards}</section>
    </section>
    <aside>
      <section class="panel" id="semana">
        <h3><span class="highlight">Semana</span></h3>
        {week_rows}
      </section>
      <section class="panel" id="compra">
        <h3>Compra</h3>
        <div class="shopping">{shopping_sections}</div>
      </section>
    </aside>
  </main>
  <div class="modal" id="recipe-modal" aria-hidden="true">
    <section class="recipe-dialog" role="dialog" aria-modal="true" aria-labelledby="recipe-title">
      <div class="recipe-header">
        <div>
          <div class="slot" id="recipe-slot"></div>
          <h2 id="recipe-title"></h2>
        </div>
        <button class="close-button" type="button" id="close-recipe" aria-label="Cerrar">×</button>
      </div>
      <div class="recipe-body">
        <section>
          <h3>Ingredientes</h3>
          <ul class="ingredients" id="recipe-ingredients"></ul>
          <div class="tip" id="recipe-tip"></div>
        </section>
        <section>
          <h3>Paso a paso</h3>
          <ol class="steps" id="recipe-steps"></ol>
        </section>
      </div>
    </section>
  </div>
  <script id="recipes-data" type="application/json">{recipes_json}</script>
  <script>
    const params = window.location.search;
    if (params) {{
      document.querySelectorAll('.app-nav a').forEach((link) => {{
        link.href = link.getAttribute('href') + params;
      }});
    }}
    const recipes = JSON.parse(document.getElementById('recipes-data').textContent);
    const modal = document.getElementById('recipe-modal');
    const title = document.getElementById('recipe-title');
    const slot = document.getElementById('recipe-slot');
    const ingredients = document.getElementById('recipe-ingredients');
    const steps = document.getElementById('recipe-steps');
    const tip = document.getElementById('recipe-tip');
    const close = document.getElementById('close-recipe');

    function renderList(node, items) {{
      node.innerHTML = '';
      for (const item of items) {{
        const li = document.createElement('li');
        li.textContent = item;
        node.appendChild(li);
      }}
    }}

    function openRecipe(index) {{
      const recipe = recipes[index];
      title.textContent = recipe.name;
      slot.textContent = recipe.slot;
      renderList(ingredients, recipe.ingredients);
      renderList(steps, recipe.steps);
      tip.textContent = recipe.tip;
      modal.classList.add('open');
      modal.setAttribute('aria-hidden', 'false');
    }}

    function closeRecipe() {{
      modal.classList.remove('open');
      modal.setAttribute('aria-hidden', 'true');
    }}

    document.querySelectorAll('[data-recipe]').forEach((button) => {{
      button.addEventListener('click', () => openRecipe(Number(button.dataset.recipe)));
    }});
    close.addEventListener('click', closeRecipe);
    modal.addEventListener('click', (event) => {{
      if (event.target === modal) closeRecipe();
    }});
    document.addEventListener('keydown', (event) => {{
      if (event.key === 'Escape') closeRecipe();
    }});
    if ('serviceWorker' in navigator) {{
      window.addEventListener('load', () => {{
        navigator.serviceWorker.register('/sw.js').catch(() => undefined);
      }});
    }}
  </script>
</body>
</html>"""


def _short_description(meal: dict[str, Any]) -> str:
    if meal["proteina"] == "delivery":
        return "Cena flexible de la semana."
    return "Ingredientes listos y preparación completa en la receta."


def _recipe_for(slot: str, meal: dict[str, Any], chef_preferences: list[str]) -> dict[str, Any]:
    ingredients = meal.get("ingredientes") or _ingredients_for_name(meal["nombre"])
    style = _style_for_recipe(meal["nombre"], ingredients, chef_preferences)
    return {
        "slot": slot.title(),
        "name": meal["nombre"],
        "ingredients": [_format_ingredient(name, qty) for name, qty in ingredients.items()],
        "steps": _recipe_steps(meal["nombre"], meal["prep"], ingredients, style),
        "tip": _recipe_tip(meal["nombre"], ingredients, style),
    }


def _ingredients_for_name(name: str) -> dict[str, float]:
    for options in MEALS.values():
        for meal in options:
            if meal.name == name:
                return dict(meal.ingredients)
    return {}


def _format_ingredient(name: str, qty: Any) -> str:
    if isinstance(qty, (int, float)):
        if qty == 0:
            return name
        return f"{name}: {format_quantity(name, qty)}"
    return f"{name}: {qty}"


def _recipe_steps(name: str, prep: str, ingredients: dict[str, Any], style: str | None = None) -> list[str]:
    lowered = name.lower()
    prefix = [f"Estilo de inspiración: {style}"] if style else []
    if "delivery" in lowered:
        return prefix + [
            "Elegir el delivery de la noche sin intentar compensar salteando comidas.",
            "Priorizar una porción razonable y, si se puede, sumar bebida sin azúcar o agua.",
            "Guardar sobrantes solo si realmente sirven para otro día; si no, cerrar la comida y seguir el plan mañana.",
        ]
    if "café" in lowered or "cafe" in lowered or "tostadas" in lowered:
        return prefix + [
            "Preparar la infusión: café, té o mate cocido. Si lleva leche, calentar leche zero lactosa sin hervirla.",
            "Tostar el pan hasta que quede firme, no quemado, para que soporte bien el topping.",
            "Preparar el topping indicado: pisar palta, revolver huevos, cortar tomate o medir una porción chica de dulce/mermelada.",
            "Armar las tostadas justo antes de comer para que no se humedezcan.",
            "Servir con la infusión caliente y dejar la fruta o extra dulce solo si ese día quedó hambre real.",
        ]
    if "milanesa" in lowered:
        return prefix + [
            "Secar la carne o pollo con papel de cocina para que el rebozado se adhiera mejor.",
            "Batir huevo con sal, pimienta y, si tienen, un toque de mostaza o limón.",
            "Pasar cada pieza por huevo y después por rebozador Preferido o pan rallado, presionando bien.",
            "Para horno: colocar en placa apenas aceitada y cocinar a temperatura fuerte, dando vuelta a mitad de cocción.",
            "Para air fryer: cocinar en tandas sin encimar, rociando apenas con aceite para dorar parejo.",
            "Preparar la guarnición mientras se cocina la milanesa y servir con ensalada o papa según el menú.",
        ]
    if "hamburguesas paty" in lowered:
        return prefix + [
            "Calentar una plancha o sartén amplia a fuego medio-alto sin exceso de aceite.",
            "Cocinar las hamburguesas Paty de ambos lados hasta que estén bien doradas y calientes en el centro.",
            "Si el menú lleva papa, cocinarla en horno o air fryer mientras se hacen las hamburguesas.",
            "Lavar y cortar lechuga y tomate; condimentar con poca sal, limón o vinagre.",
            "Servir al plato o en pan, según el menú, cuidando que la guarnición de verduras quede presente.",
        ]
    if _is_meat_recipe(lowered, " ".join(ingredients)):
        return prefix + [
            "Sacar la carne de la heladera unos minutos antes para que no vaya helada a la plancha, horno o parrilla.",
            "Secar bien la superficie con papel de cocina; eso ayuda a lograr mejor dorado.",
            "Salar con criterio justo antes de cocinar y usar fuego fuerte al principio para sellar.",
            "Cocinar hasta el punto deseado, bajando el fuego si el corte necesita más tiempo.",
            "Dejar reposar la carne 3 a 5 minutos antes de cortar para que conserve jugos.",
            "Mientras reposa, preparar la guarnición o ensalada indicada con los vegetales concretos del plato.",
            "Cortar, servir y terminar con limón, pimienta o un toque de aceite de oliva si corresponde.",
        ]
    if "fideos" in lowered or "pastas" in lowered:
        return prefix + [
            "Poner agua a hervir con sal y cocinar los fideos hasta que estén al dente.",
            "Mientras tanto preparar la proteína o vegetales en una sartén amplia.",
            "Reservar un poco de agua de cocción antes de colar la pasta.",
            "Mezclar fideos con salsa, proteína o verduras; ajustar textura con el agua reservada.",
            "Servir en porción medida y completar con ensalada si el plato quedó corto de verduras.",
        ]
    if "arroz" in lowered or "bowl" in lowered:
        return prefix + [
            "Enjuagar el arroz si hace falta y cocinarlo con agua hasta que quede tierno.",
            "Cortar verduras y proteína en piezas parejas para que se cocinen al mismo tiempo.",
            "Dorar la proteína primero y retirarla si la sartén queda chica.",
            "Saltear verduras, volver a sumar la proteína y condimentar.",
            "Armar el bowl con arroz abajo, proteína y verduras arriba; terminar con limón o condimento simple.",
        ]
    if "ensalada" in lowered or "atún" in lowered or "atun" in lowered:
        return prefix + [
            "Lavar y escurrir bien las verduras para que la ensalada no quede aguada.",
            "Preparar la proteína: abrir atún, hervir huevo o cocinar la carne indicada.",
            "Cortar vegetales en tamaños fáciles de comer y mezclar en un bowl grande.",
            "Condimentar al final con aceite medido, limón o vinagre, sal y pimienta.",
            "Servir enseguida; si sobra, guardar sin condimentar para que aguante mejor.",
        ]
    return prefix + [
        "Separar todos los ingredientes antes de empezar para no cortar la cocción a mitad de camino.",
        prep,
        "Cocinar primero la proteína o base principal y después sumar verduras o guarnición.",
        "Probar, ajustar sal y condimentos, y servir en porciones parejas.",
        "Guardar sobrantes en recipiente cerrado apenas se enfríen.",
    ]


def _recipe_tip(name: str, ingredients: dict[str, Any], style: str | None = None) -> str:
    lowered = name.lower()
    if style and "Petersen" in style:
        return "Tip Petersen: secar bien la carne, dorar fuerte, salar con criterio y dejar reposar antes de cortar."
    if "desayuno" in lowered or "café" in lowered or "cafe" in lowered:
        return "Usar leche deslactosada y variar toppings durante la semana para no aburrirse."
    if "milanesa" in lowered:
        return "Conviene hacer alguna milanesa extra y dejarla lista para una comida rápida."
    if "hamburguesas paty" in lowered:
        return "Para compra, priorizar Paty en pack o la oferta equivalente de carne vacuna."
    if "delivery" in lowered:
        return "Es el gusto flexible semanal: no hace falta reemplazarlo por otra comida."
    if "dannette" in lowered or "cindor" in lowered:
        return "Elegir el postre que esté en oferta y mantenerlo como gusto puntual."
    return "Si falta un ingrediente, reemplazar por uno parecido sin cambiar toda la comida."


def _chef_preferences(conditions: dict[str, Any]) -> list[str]:
    raw = f"{conditions.get('chefs', '')} {conditions.get('reglas', '')} {conditions.get('estilo', '')}"
    normalized = raw.lower()
    return [key for key in CHEF_STYLES if key in normalized]


def _style_for_recipe(name: str, ingredients: dict[str, Any], chef_preferences: list[str]) -> str | None:
    lowered = name.lower()
    ingredient_text = " ".join(ingredients).lower()
    if _is_meat_recipe(lowered, ingredient_text) and "petersen" in chef_preferences:
        return CHEF_STYLES["petersen"]
    if ("fideos" in lowered or "pastas" in lowered or "pizza" in lowered) and "donato de santis" in chef_preferences:
        return CHEF_STYLES["donato de santis"]
    if ("verduras" in lowered or "ensalada" in lowered) and "narda lepes" in chef_preferences:
        return CHEF_STYLES["narda lepes"]
    if ("milanesa" in lowered or "hamburguesas" in lowered or "tostadas" in lowered) and "paulina cocina" in chef_preferences:
        return CHEF_STYLES["paulina cocina"]
    for key in chef_preferences:
        return CHEF_STYLES[key]
    return None


def _is_meat_recipe(name: str, ingredients: str) -> bool:
    meat_words = (
        "vacio",
        "vacío",
        "entraña",
        "asado",
        "bife",
        "costilla",
        "lomo",
        "peceto",
        "cuadril",
        "nalga",
        "roast beef",
        "hamburguesas",
        "carne",
    )
    haystack = f"{name} {ingredients}"
    return any(word in haystack for word in meat_words)
