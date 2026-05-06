from __future__ import annotations

import os
import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from telegram.ext import Application

from .bot import DB, TZ, build_application
from .planner import (
    DAYS,
    MEALS,
    SLOTS,
    format_quantity,
    format_shopping_list,
    generate_week,
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


app = FastAPI(title="Menu Bot", lifespan=lifespan)
PWA_CACHE_VERSION = "menu-bot-v1"

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
        "name": "Menú Familiar",
        "short_name": "Menú",
        "description": "Menú semanal, recetas y compra familiar.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#f6f4ef",
        "theme_color": "#2f6f5e",
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
const APP_SHELL = ['/', '/offline', '/manifest.webmanifest', '/icon.svg'];

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
  <rect width="512" height="512" rx="96" fill="#2f6f5e"/>
  <path d="M152 126h208c18 0 32 14 32 32v220c0 18-14 32-32 32H152c-18 0-32-14-32-32V158c0-18 14-32 32-32Z" fill="#f6f4ef"/>
  <path d="M176 178h160M176 238h128M176 298h160" stroke="#2f6f5e" stroke-width="28" stroke-linecap="round"/>
  <circle cx="352" cy="238" r="17" fill="#f3c969"/>
  <circle cx="352" cy="298" r="17" fill="#f3c969"/>
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
  <meta name="theme-color" content="#2f6f5e">
  <title>Menú sin conexión</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f6f4ef; color: #1c1b18; font-family: system-ui, sans-serif; }
    main { width: min(520px, calc(100vw - 32px)); border: 1px solid #d8d1c4; border-radius: 8px; background: #fff; padding: 24px; }
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


@app.get("/", response_class=HTMLResponse)
def home(request: Request, pin: str | None = None, chat_id: int | None = None) -> str:
    _guard_web(request, pin)
    chat_id = _active_chat_id(chat_id)
    today = _today()
    weekly = _get_or_create(chat_id, today)
    today_plan = weekly["plan"][today.weekday()]
    user = DB.get_user(chat_id)
    preferences = DB.get_product_preferences(chat_id)
    pantry = DB.list_pantry_items(chat_id)
    shopping = format_shopping_list(weekly["shopping_list"], preferences, pantry)
    return _page(today_plan, weekly["plan"], shopping, user["conditions"])


@app.get("/api/menu")
def api_menu(request: Request, pin: str | None = None, chat_id: int | None = None) -> JSONResponse:
    _guard_web(request, pin)
    chat_id = _active_chat_id(chat_id)
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
    expected = os.getenv("DASHBOARD_PIN", "").strip()
    if not expected:
        return
    header_pin = request.headers.get("x-dashboard-pin")
    if pin == expected or header_pin == expected:
        return
    raise HTTPException(status_code=401, detail="PIN requerido")


def _active_chat_id(requested_chat_id: int | None = None) -> int:
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


def _get_or_create(chat_id: int, day: date) -> dict[str, Any]:
    start = week_start_for(day)
    weekly = DB.get_weekly_plan(chat_id, start.isoformat())
    if weekly and not _plan_needs_refresh(weekly["plan"]):
        return weekly
    user = DB.get_user(chat_id)
    offers = DB.list_offers(chat_id)
    plan, shopping = generate_week(
        start,
        user["profile"],
        user["conditions"],
        offers,
        fetch_weather_context(user["profile"]),
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


def _shopping_markup(shopping: str) -> str:
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
        current_items.append(_shopping_item_markup(line.removeprefix("- ").strip()))
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


def _shopping_item_markup(line: str) -> str:
    main, *notes = [part.strip() for part in line.split(" | ")]
    if ": comprar " in main:
        item, quantity = main.split(": comprar ", 1)
    elif ": " in main:
        item, quantity = main.split(": ", 1)
    else:
        item, quantity = main, ""
    notes_html = f"<div class=\"buy-notes\">{escape(' · '.join(notes))}</div>" if notes else ""
    return (
        "<li>"
        f"<div class=\"buy-line\"><span>{escape(item)}</span><span>{escape(quantity)}</span></div>"
        f"{notes_html}"
        "</li>"
    )


def _page(today_plan: dict[str, Any], week: list[dict[str, Any]], shopping: str, conditions: dict[str, Any]) -> str:
    meals = today_plan["comidas"]
    chef_preferences = _chef_preferences(conditions)
    recipes = [_recipe_for(slot, meals[slot], chef_preferences) for slot in SLOTS]
    meal_cards = "\n".join(
        f"""
        <article class="meal">
          <div class="slot">{escape(slot.title())}</div>
          <h2>{escape(meals[slot]["nombre"])}</h2>
          <p>{escape(_short_description(meals[slot]))}</p>
          <button class="recipe-button" type="button" data-recipe="{index}">Ver receta</button>
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
  <meta name="theme-color" content="#2f6f5e">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Menú">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/icon.svg" type="image/svg+xml">
  <title>Menú de hoy</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f4ef;
      --ink: #1c1b18;
      --muted: #68645d;
      --line: #d8d1c4;
      --card: #ffffff;
      --accent: #2f6f5e;
      --accent-soft: #dfeee8;
      --warm: #f3c969;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
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
      display: none;
      gap: 8px;
      padding: 10px 18px;
      background: rgba(246, 244, 239, .94);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }}
    .app-nav a {{
      flex: 1;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 8px;
      background: #fff;
      color: var(--ink);
      font-size: 13px;
      font-weight: 800;
      text-align: center;
      text-decoration: none;
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
    h1 {{
      margin: 0;
      font-size: 44px;
      line-height: 1;
      letter-spacing: 0;
    }}
    .date {{
      color: var(--muted);
      font-size: 18px;
      margin-top: 8px;
    }}
    .time {{
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid #b7d8cc;
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
      box-shadow: 0 8px 24px rgba(47, 45, 39, .06);
    }}
    .meal {{
      min-height: 176px;
      padding: 18px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .slot {{
      color: var(--accent);
      font-size: 13px;
      font-weight: 800;
      text-transform: uppercase;
    }}
    h2 {{
      margin: 10px 0;
      font-size: 24px;
      line-height: 1.12;
      letter-spacing: 0;
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
      border: 1px solid #b7d8cc;
      background: var(--accent);
      color: #fff;
      border-radius: 8px;
      padding: 10px 14px;
      font-weight: 800;
      cursor: pointer;
    }}
    .recipe-button:active {{
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
    .day strong {{ color: var(--accent); grid-row: span 2; }}
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
      color: var(--accent);
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
      background: #fbfaf7;
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
      color: var(--accent);
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
      background: #fff;
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
      color: var(--accent);
      font-weight: 700;
      line-height: 1.3;
    }}
    @media (max-width: 900px) {{
      .app-nav {{ display: flex; }}
      main {{ grid-template-columns: 1fr; padding: 18px; }}
      .meals {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 34px; }}
      .recipe-body {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <nav class="app-nav" aria-label="Navegación">
    <a href="#hoy">Hoy</a>
    <a href="#semana">Semana</a>
    <a href="#compra">Compra</a>
  </nav>
  <main>
    <section id="hoy">
      <header>
        <div>
          <h1>Menú de hoy</h1>
          <div class="date">{escape(today_plan["dia"].title())} · {escape(today_plan["fecha"])}</div>
          <div class="date">{escape(format_weather_summary(today_plan.get("clima")))}</div>
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
