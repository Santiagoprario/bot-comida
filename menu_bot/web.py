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
from fastapi.responses import HTMLResponse, JSONResponse
from telegram.ext import Application

from .bot import DB, TZ, build_application
from .planner import (
    DAYS,
    MEALS,
    SLOTS,
    format_shopping_list,
    generate_week,
    week_start_for,
)
from .seed import seed_default_user


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

CHEF_STYLES = {
    "paulina cocina": "Paulina Cocina: práctico, casero, rendidor y sin complicarla.",
    "narda lepes": "Narda Lepes: verduras con más intención, frescura, acidez y buenos condimentos.",
    "germán martitegui": "Germán Martitegui: plato prolijo, buen punto de cocción y sabores más definidos.",
    "german martitegui": "Germán Martitegui: plato prolijo, buen punto de cocción y sabores más definidos.",
    "donato de santis": "Donato De Santis: toque italiano, pastas cuidadas, salsa simple y buen queso.",
    "petersen": "Los Petersen: carnes bien tratadas, buen dorado, reposo y guarniciones clásicas.",
}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    chat_id = _active_chat_id()
    today = _today()
    weekly = _get_or_create(chat_id, today)
    today_plan = weekly["plan"][today.weekday()]
    user = DB.get_user(chat_id)
    preferences = DB.get_product_preferences(chat_id)
    shopping = format_shopping_list(weekly["shopping_list"], preferences)
    return _page(today_plan, weekly["plan"], shopping, user["conditions"])


@app.get("/api/menu")
def api_menu() -> JSONResponse:
    chat_id = _active_chat_id()
    today = _today()
    weekly = _get_or_create(chat_id, today)
    return JSONResponse(
        {
            "today": weekly["plan"][today.weekday()],
            "week": weekly["plan"],
            "shopping_list": weekly["shopping_list"],
        }
    )


def _active_chat_id() -> int:
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
    if weekly:
        return weekly
    user = DB.get_user(chat_id)
    offers = DB.list_offers(chat_id)
    plan, shopping = generate_week(start, user["profile"], user["conditions"], offers)
    DB.save_weekly_plan(chat_id, start.isoformat(), plan, shopping)
    return {"plan": plan, "shopping_list": shopping}


def _today() -> date:
    return datetime.now(TZ if isinstance(TZ, ZoneInfo) else ZoneInfo("America/Argentina/Buenos_Aires")).date()


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
    shopping_items = "\n".join(
        f"<li>{escape(line.removeprefix('- ').strip())}</li>"
        for line in shopping.splitlines()[1:]
    )
    now = datetime.now().strftime("%H:%M")
    recipes_json = escape(json.dumps(recipes, ensure_ascii=False), quote=False)
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="900">
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
    ul {{
      margin: 0;
      padding-left: 18px;
      max-height: 320px;
      overflow: auto;
    }}
    li {{
      margin: 8px 0;
      font-size: 14px;
      line-height: 1.25;
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
      main {{ grid-template-columns: 1fr; padding: 18px; }}
      .meals {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 34px; }}
      .recipe-body {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section>
      <header>
        <div>
          <h1>Menú de hoy</h1>
          <div class="date">{escape(today_plan["dia"].title())} · {escape(today_plan["fecha"])}</div>
        </div>
        <div class="time">{escape(now)}</div>
      </header>
      <section class="meals">{meal_cards}</section>
    </section>
    <aside>
      <section class="panel">
        <h3><span class="highlight">Semana</span></h3>
        {week_rows}
      </section>
      <section class="panel">
        <h3>Compra</h3>
        <ul>{shopping_items}</ul>
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
        if qty < 10:
            unit = "unidad" if qty == 1 else "unidades"
            return f"{name}: {qty:g} {unit}"
        return f"{name}: {qty:g} g/ml aprox."
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
