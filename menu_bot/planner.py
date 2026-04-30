from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from unicodedata import normalize


@dataclass(frozen=True)
class Meal:
    name: str
    protein: str
    tags: tuple[str, ...]
    ingredients: dict[str, float]
    prep: str


MEALS: dict[str, list[Meal]] = {
    "desayuno": [
        Meal("Café con leche zero lactosa y tostadas con queso untable", "leche zero lactosa", ("infusión", "rápido", "baja lactosa"), {"café": 1, "leche zero lactosa": 200, "pan de molde": 2, "queso blanco light": 50}, "Preparar café con leche y tostar el pan con queso untable."),
        Meal("Café con leche zero lactosa y tostadas con dulce de leche", "leche zero lactosa", ("infusión", "gusto moderado"), {"café": 1, "leche zero lactosa": 200, "pan de molde": 2, "dulce de leche": 35}, "Preparar café con leche y usar una porción chica de dulce de leche."),
        Meal("Café o mate cocido con tostadas de palta y tomate", "palta", ("infusión", "saludable"), {"café": 1, "pan de molde": 2, "palta": 0.5, "tomate": 1}, "Tostar el pan, pisar palta y sumar tomate."),
        Meal("Café con leche zero lactosa y huevos revueltos con tostadas", "huevo", ("infusión", "proteico"), {"café": 1, "leche zero lactosa": 200, "huevo": 2, "pan de molde": 2}, "Hacer huevos revueltos y acompañar con tostadas."),
        Meal("Té o café con tostadas con manteca y mermelada", "manteca", ("infusión", "gusto moderado"), {"café": 1, "pan de molde": 2, "manteca": 20, "mermelada": 30}, "Preparar infusión y sumar tostadas con topping dulce."),
        Meal("Café con leche zero lactosa y tostadas con queso y tomate", "leche zero lactosa", ("infusión", "baja lactosa"), {"café": 1, "leche zero lactosa": 200, "pan de molde": 2, "queso cremoso": 50, "tomate": 1}, "Tostar el pan y sumar queso con tomate."),
    ],
    "almuerzo": [
        Meal("Bowl de peceto, arroz y verduras grilladas", "peceto", ("proteico", "batch"), {"peceto": 180, "arroz": 80, "zanahoria": 100, "pimiento rojo": 80, "cebolla": 70}, "Cocinar arroz y sumar peceto a la plancha con zanahoria, pimiento y cebolla."),
        Meal("Hamburguesas Paty con papa y ensalada de lechuga y tomate", "hamburguesas Paty", ("proteico", "rápido"), {"hamburguesas Paty": 2, "papa": 250, "lechuga": 80, "tomate": 1}, "Cocinar las hamburguesas a la plancha y servir con papa y ensalada de lechuga y tomate."),
        Meal("Ensalada de atún, garbanzos, huevo, tomate y zanahoria", "atún", ("rápido",), {"atún": 1, "garbanzos": 160, "huevo": 1, "tomate": 1, "zanahoria": 100, "lechuga": 80}, "Mezclar atún, garbanzos, huevo, tomate, zanahoria y lechuga; condimentar al final."),
        Meal("Lentejas guisadas con arroz, zanahoria y pimiento", "lentejas", ("vegetariano", "económico"), {"lentejas": 120, "arroz": 60, "zanahoria": 120, "pimiento rojo": 80, "cebolla": 70}, "Cocinar como guiso liviano con zanahoria, pimiento y cebolla."),
        Meal("Fideos con muslo de pollo, tomate y espinaca", "muslo de pollo", ("proteico", "rápido"), {"muslo de pollo": 170, "fideos": 80, "tomate": 1, "espinaca": 100}, "Saltear pollo y verduras mientras se hacen los fideos."),
        Meal("Tacos de roast beef con pimiento, cebolla y tomate", "roast beef", ("proteico", "rápido"), {"roast beef": 170, "tortillas": 2, "pimiento rojo": 100, "cebolla": 80, "tomate": 1}, "Saltear carne con pimiento y cebolla, armar tacos y terminar con tomate."),
        Meal("Arroz salteado con atún, zanahoria y pimiento", "atún", ("rápido", "económico"), {"arroz": 80, "atún": 1, "zanahoria": 120, "pimiento rojo": 100, "cebolla": 70}, "Usar arroz cocido y saltear con atún, zanahoria, pimiento y cebolla."),
        Meal("Milanesas de pechuga al horno con ensalada", "pechuga de pollo milanesa", ("milanesa", "proteico"), {"pechuga de pollo para milanesa": 180, "pan rallado": 40, "huevo": 0.5, "lechuga": 80, "tomate": 1}, "Hornear o air fryer y servir con ensalada."),
        Meal("Milanesas de nalga al horno con puré", "nalga milanesa", ("milanesa", "proteico"), {"nalga para milanesa": 180, "pan rallado": 40, "huevo": 0.5, "papa": 250}, "Hornear o air fryer y acompañar con puré."),
        Meal("Wok de cuadril con zanahoria, pimiento y cebolla", "cuadril", ("proteico", "rápido"), {"cuadril": 180, "zanahoria": 120, "pimiento rojo": 100, "cebolla": 80}, "Saltear tiras de cuadril con zanahoria, pimiento y cebolla a fuego fuerte."),
        Meal("Merluza con papas air fryer y ensalada", "merluza", ("proteico", "rápido"), {"merluza": 180, "papas tipo McCain para air fryer": 180, "lechuga": 80, "tomate": 1}, "Cocinar papas en air fryer y hacer la merluza a la plancha."),
        Meal("Shakshuka simple con tostadas", "huevo shakshuka", ("nuevo", "proteico"), {"huevo": 2, "tomate perita lata": 200, "pimiento rojo": 120, "pan de molde": 2}, "Cocinar tomate y morrón especiados, cascar huevos arriba y servir con tostadas."),
    ],
    "merienda": [
        Meal("Yogur con granola y fruta", "yogur", ("rápido",), {"yogur": 200, "granola": 40, "fruta de estación": 1}, "Servir en bowl."),
        Meal("Sándwich integral de queso y tomate", "queso", ("rápido",), {"pan integral": 2, "queso": 60, "tomate": 1}, "Armar y tostar si querés."),
        Meal("Mate o café con tostadas y ricota", "ricota", ("simple",), {"pan integral": 2, "ricota": 80}, "Untar ricota y acompañar con infusión."),
        Meal("Tostadas con mantequilla de maní y banana", "maní", ("rápido", "baja lactosa"), {"pan integral": 2, "mantequilla de maní": 30, "banana": 1}, "Armar tostadas y sumar banana."),
        Meal("Yogur bajo lactosa con fruta", "yogur bajo lactosa", ("rápido", "baja lactosa"), {"yogur bajo lactosa": 200, "fruta de estación": 1}, "Servir frío."),
    ],
    "cena": [
        Meal("Tortilla de papa con ensalada", "huevo", ("económico",), {"huevo": 3, "papa": 250, "lechuga": 80, "tomate": 1}, "Preparar tortilla y servir con ensalada."),
        Meal("Fideos con ricota baja lactosa, espinaca y tomate", "ricota baja lactosa", ("batch",), {"fideos": 80, "ricota baja lactosa": 120, "espinaca": 100, "tomate": 1}, "Saltear espinaca y tomate, sumar fideos y ricota al final."),
        Meal("Omelette de espinaca con ensalada de lechuga y zanahoria", "huevo", ("rápido",), {"huevo": 3, "espinaca": 100, "lechuga": 80, "zanahoria": 100}, "Hacer omelette de espinaca y acompañar con lechuga y zanahoria."),
        Meal("Bife de bola de lomo con ensalada de rúcula, tomate y batata", "bola de lomo", ("proteico", "saludable"), {"bola de lomo": 200, "batata": 220, "rucula": 80, "tomate": 1}, "Plancha fuerte para el bife y ensalada de rúcula y tomate."),
        Meal("Vacío al horno con ensalada de lechuga, tomate y papas", "vacío", ("gusto semanal", "asado"), {"vacío": 220, "papa": 250, "lechuga": 80, "tomate": 1}, "Cocinar el vacío al horno o parrilla y acompañar con ensalada de lechuga y tomate."),
        Meal("Entraña a la plancha con ensalada criolla", "entraña", ("gusto semanal", "asado"), {"entraña": 200, "tomate": 1, "pimiento rojo": 120, "cebolla": 80}, "Dorar la entraña fuerte y servir con ensalada criolla de tomate, pimiento y cebolla."),
        Meal("Asado al horno con papa, zanahoria y cebolla", "asado", ("gusto semanal", "asado"), {"asado": 230, "papa": 180, "zanahoria": 120, "cebolla": 100}, "Cocinar el asado lento y sumar papa, zanahoria y cebolla al horno."),
        Meal("Bife de costilla con papas air fryer", "bife de costilla", ("gusto semanal", "asado"), {"bife de costilla": 230, "papas tipo McCain para air fryer": 180, "lechuga": 80, "tomate": 1}, "Cocinar el bife a la plancha o parrilla y acompañar con papas air fryer."),
        Meal("Hamburguesas Paty con papas al horno", "hamburguesas Paty", ("gusto semanal", "chatarra moderada"), {"hamburguesas Paty": 2, "pan de hamburguesa": 1, "papa": 250, "lechuga": 50, "tomate": 1}, "Cocinar hamburguesas Paty y hornear las papas."),
        Meal("Milanesa de pechuga al horno con puré y ensalada de zanahoria", "pechuga de pollo milanesa", ("gusto semanal", "milanesa"), {"pechuga de pollo para milanesa": 180, "pan rallado": 40, "huevo": 0.5, "papa": 250, "zanahoria": 100}, "Hornear la milanesa y acompañar con puré y zanahoria rallada."),
        Meal("Milanesa de nalga con papas air fryer", "nalga milanesa", ("gusto semanal", "milanesa", "chatarra moderada"), {"nalga para milanesa": 180, "pan rallado": 40, "huevo": 0.5, "papas tipo McCain para air fryer": 180}, "Hornear la milanesa y hacer las papas en air fryer."),
        Meal("Tarta de pollo, espinaca y cebolla", "pollo desmenuzado", ("proteico",), {"pollo desmenuzado": 160, "tapa de tarta": 0.5, "espinaca": 120, "cebolla": 80}, "Rellenar con pollo, espinaca y cebolla; hornear."),
        Meal("Pastas con salsa bolognesa magra", "nalga picada", ("gusto semanal",), {"fideos": 90, "nalga picada": 170, "tomate": 1}, "Preparar salsa rápida y mezclar con la pasta."),
        Meal("Pizza casera con muzzarella, tomate y pimiento", "muzzarella", ("gusto semanal", "chatarra moderada"), {"prepizza": 1, "muzzarella": 120, "tomate": 1, "pimiento rojo": 80}, "Armar pizza casera con tomate y pimiento arriba o al costado."),
        Meal("Empanadas de carne al horno con ensalada", "cuadrada", ("gusto semanal", "chatarra moderada"), {"tapas de empanada": 4, "cuadrada": 170, "lechuga": 80, "tomate": 1}, "Preparar relleno magro, hornear y acompañar con ensalada."),
        Meal("Lomito al plato con papas air fryer y ensalada de tomate", "lomo", ("gusto semanal", "chatarra moderada"), {"lomo": 180, "papas tipo McCain para air fryer": 180, "huevo": 1, "tomate": 1, "lechuga": 60}, "Cocinar el lomo a la plancha, las papas en air fryer y sumar tomate con lechuga."),
        Meal("Risotto falso de calabaza y queso", "queso cremoso", ("nuevo", "gusto semanal"), {"arroz": 80, "zapallo": 220, "queso cremoso": 80, "queso rallado": 20}, "Cocinar arroz cremoso con calabaza, terminar con queso y servir caliente."),
        Meal("Pollo estilo mediterráneo con cous cous, tomate y pepino", "suprema de pollo", ("nuevo", "proteico"), {"suprema de pollo": 180, "cous cous": 70, "tomate": 1, "pepino": 100, "limon": 0.5}, "Dorar pollo, hidratar cous cous y servir con tomate, pepino y limón."),
        Meal("Delivery libre de la semana", "delivery", ("delivery", "gusto semanal"), {}, "Elegir delivery para la cena y retomar el plan al día siguiente."),
    ],
    "colación": [
        Meal("Fruta con maní", "maní", ("rápido",), {"fruta de estación": 1, "maní": 25}, "Listo para llevar."),
        Meal("Huevo duro y fruta", "huevo", ("proteico",), {"huevo": 1, "fruta de estación": 1}, "Hervir huevos en tanda semanal."),
        Meal("Queso fresco con tomate", "queso", ("simple",), {"queso": 60, "tomate": 1}, "Cortar y condimentar."),
        Meal("Yogur bebible", "yogur", ("rápido",), {"yogur bebible": 1}, "Mantener refrigerado."),
        Meal("Atún con galletas de arroz", "atún", ("proteico", "rápido"), {"atún": 1, "galletas de arroz": 3}, "Abrir lata y acompañar."),
        Meal("Postre Dannette o Copa Cindor", "lácteo", ("postre", "gusto semanal"), {"dannette o copa cindor": 1}, "Comprar el que esté en oferta y usar como gusto."),
    ],
}

DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
SLOTS = ["desayuno", "colación 1", "almuerzo", "merienda", "cena"]
HOUSEHOLD_ROTATION: list[dict[str, float]] = [
    {"papel higienico": 1, "detergente": 1, "pasta dental": 1},
    {"rollo de cocina": 1, "desodorante hombre": 1, "desodorante mujer": 1},
    {"jabon en pan": 2, "limpiavidrios": 1, "pano multiuso": 1},
    {"algodon": 1, "alcohol": 1, "separadores freezer": 1},
]


def week_start_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


def generate_week(
    start: date,
    profile: dict[str, Any],
    conditions: dict[str, Any],
    offers: list[dict[str, str | None]],
    weather_context: dict[str, dict[str, float | str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    people = int(profile.get("personas") or 2)
    avoid = _words(f"{conditions.get('restricciones', '')} {conditions.get('evitar', '')}")
    avoid -= {"lactosa", "menos", "mejor", "cuanto", "intolerancia"}
    preferred = _words(f"{conditions.get('preferencias', '')} {profile.get('objetivo', '')}")
    rules = _words(f"{conditions.get('reglas', '')} {conditions.get('estilo', '')}")
    offer_words = _words(" ".join(offer["item"] or "" for offer in offers))
    delivery_day = _stable_delivery_day(profile, conditions, start)
    discovery_day = _stable_discovery_day(start, delivery_day)

    plan: list[dict[str, Any]] = []
    shopping: defaultdict[str, float] = defaultdict(float)
    used_names: defaultdict[str, int] = defaultdict(int)
    used_main_proteins: defaultdict[str, int] = defaultdict(int)
    used_limited_ingredients: defaultdict[str, int] = defaultdict(int)
    milanesa_days = _milanesa_days(delivery_day)

    for day_index, day_name in enumerate(DAYS):
        daily: dict[str, Any] = {
            "fecha": (start + timedelta(days=day_index)).isoformat(),
            "dia": day_name,
            "comidas": {},
            "clima": (weather_context or {}).get((start + timedelta(days=day_index)).isoformat()),
        }
        for slot in SLOTS:
            meal_type = "colación" if slot.startswith("colación") else slot
            forced_tag = None
            if slot == "cena" and day_index == delivery_day and "delivery" in rules:
                forced_tag = "delivery"
            elif slot == "almuerzo" and day_index in milanesa_days:
                forced_tag = "milanesa"
            elif slot == "cena" and day_index >= 5:
                forced_tag = "gusto semanal"
            elif slot in {"almuerzo", "cena"} and day_index == discovery_day:
                forced_tag = "nuevo"
            protein_scope = _protein_limited_slot(slot, meal_type)
            meal = _pick_meal(
                MEALS[meal_type],
                avoid,
                preferred,
                offer_words,
                used_names,
                day_index,
                forced_tag=forced_tag,
                blocked_proteins=used_main_proteins if protein_scope else None,
                ingredient_counts=used_limited_ingredients,
                weather=daily["clima"],
            )
            used_names[meal.name] += 1
            if protein_scope:
                used_main_proteins[_protein_key(meal.protein)] += 1
            for limited in ("arroz", "fideos", "dannette o copa cindor"):
                if limited in meal.ingredients:
                    used_limited_ingredients[limited] += 1
            daily["comidas"][slot] = {
                "nombre": meal.name,
                "prep": meal.prep,
                "proteina": meal.protein,
                "ingredientes": meal.ingredients,
                "porciones": people,
            }
            for ingredient, qty in meal.ingredients.items():
                shopping[ingredient] += qty * people
        plan.append(daily)

    _add_household_items(shopping, start, people)
    return plan, dict(sorted(shopping.items()))


def format_day(day: dict[str, Any]) -> str:
    lines = [f"Menú de {day['dia']} ({day['fecha']})"]
    for slot in SLOTS:
        meal = day["comidas"][slot]
        lines.append(f"- {slot.title()}: {meal['nombre']}. {meal['prep']}")
    return "\n".join(lines)


def format_week(plan: list[dict[str, Any]]) -> str:
    chunks = []
    for day in plan:
        meals = day["comidas"]
        chunks.append(
            f"{day['dia'].title()} {day['fecha']}\n"
            f"Des: {meals['desayuno']['nombre']}\n"
            f"Col: {meals['colación 1']['nombre']}\n"
            f"Alm: {meals['almuerzo']['nombre']}\n"
            f"Mer: {meals['merienda']['nombre']}\n"
            f"Cena: {meals['cena']['nombre']}"
        )
    return "\n\n".join(chunks)


def format_shopping_list(shopping: dict[str, float], preferences: dict[str, dict[str, Any]] | None = None) -> str:
    lines = ["Compra semanal"]
    for item, qty in shopping.items():
        unit = "u" if qty < 20 else "g/ml aprox."
        pretty_qty = int(qty) if qty == int(qty) else round(qty, 1)
        preferred = _preferred_product_for(item, preferences or {})
        suffix = f" | sugerido: {preferred}" if preferred else ""
        lines.append(f"- {item}: {pretty_qty} {unit}{suffix}")
    return "\n".join(lines)


def format_product_preferences(preferences: dict[str, dict[str, Any]]) -> str:
    if not preferences:
        return "Todavía no hay preferencias de compra cargadas."
    lines = ["Preferencias de compra:"]
    for ingredient, preference in preferences.items():
        brand = f" ({preference['brand']})" if preference.get("brand") else ""
        size = f" - {preference['package_size']}" if preference.get("package_size") else ""
        lines.append(f"- {ingredient}: {preference['preferred_product']}{brand}{size}")
    return "\n".join(lines)


def format_household_rotation() -> str:
    lines = ["Rotación de limpieza e higiene:"]
    for index, items in enumerate(HOUSEHOLD_ROTATION, start=1):
        pretty_items = ", ".join(f"{item} x{qty:g}" for item, qty in items.items())
        lines.append(f"- Semana {index}: {pretty_items}")
    lines.append("\nAdemás se chequea papel higiénico todas las semanas.")
    return "\n".join(lines)


def _preferred_product_for(item: str, preferences: dict[str, dict[str, Any]]) -> str | None:
    normalized_item = _normalize_text(item)
    exact = preferences.get(normalized_item)
    if exact:
        return exact["preferred_product"]

    contains_item = [
        (len(ingredient), preference["preferred_product"])
        for ingredient, preference in preferences.items()
        if ingredient in normalized_item
    ]
    if contains_item:
        return sorted(contains_item, reverse=True)[0][1]

    contains_preference = [
        (len(ingredient), preference["preferred_product"])
        for ingredient, preference in preferences.items()
        if normalized_item in ingredient
    ]
    return sorted(contains_preference, reverse=True)[0][1] if contains_preference else None


def _pick_meal(
    options: list[Meal],
    avoid: set[str],
    preferred: set[str],
    offer_words: set[str],
    used_names: dict[str, int],
    day_index: int,
    forced_tag: str | None = None,
    blocked_proteins: dict[str, int] | None = None,
    ingredient_counts: dict[str, int] | None = None,
    weather: dict[str, float | str] | None = None,
) -> Meal:
    if forced_tag:
        tagged = [meal for meal in options if forced_tag in meal.tags]
        if forced_tag == "gusto semanal":
            tagged = [meal for meal in tagged if "delivery" not in meal.tags]
        if tagged:
            options = tagged

    scored: list[tuple[int, Meal]] = []
    for index, meal in enumerate(options):
        haystack = _words(f"{meal.name} {meal.protein} {' '.join(meal.ingredients)} {' '.join(meal.tags)}")
        if haystack & avoid:
            continue
        if "milanesa" in meal.tags and forced_tag != "milanesa":
            continue
        if "postre" in meal.tags and forced_tag != "postre":
            continue
        protein_key = _protein_key(meal.protein)
        if blocked_proteins and blocked_proteins.get(protein_key, 0) >= 1:
            continue
        if _limited_ingredient_blocked(meal, ingredient_counts):
            continue
        score = 0
        score += 6 * len(haystack & offer_words)
        score += 2 * len(haystack & preferred)
        score += 4 if "milanesa" in meal.tags and forced_tag == "milanesa" else 0
        score += _weather_score(meal, weather)
        score -= 10 * used_names[meal.name]
        score -= index
        score += (day_index + index) % 3
        scored.append((score, meal))
    if not scored:
        scored = []
        for meal in options:
            haystack = _words(f"{meal.name} {meal.protein} {' '.join(meal.ingredients)} {' '.join(meal.tags)}")
            if not (haystack & avoid):
                if "milanesa" in meal.tags and forced_tag != "milanesa":
                    continue
                if "postre" in meal.tags and forced_tag != "postre":
                    continue
                protein_key = _protein_key(meal.protein)
                if _hard_blocked_protein(protein_key, blocked_proteins):
                    continue
                if _hard_blocked_limited_ingredient(meal, ingredient_counts):
                    continue
                scored.append((-used_names[meal.name], meal))
        if not scored:
            scored = [
                (-used_names[meal.name], meal)
                for meal in options
                if not ("milanesa" in meal.tags and forced_tag != "milanesa")
                and not ("postre" in meal.tags and forced_tag != "postre")
                and not _hard_blocked_protein(_protein_key(meal.protein), blocked_proteins)
                and not _hard_blocked_limited_ingredient(meal, ingredient_counts)
            ]
        if not scored:
            scored = [(-used_names[meal.name], meal) for meal in options]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _stable_delivery_day(profile: dict[str, Any], conditions: dict[str, Any], start: date) -> int:
    seed = f"{profile.get('ciudad', '')}-{conditions.get('reglas', '')}-{start.isoformat()}"
    return sum(ord(char) for char in seed) % 7


def _milanesa_days(delivery_day: int) -> set[int]:
    preferred_days = [1, 4, 5, 2, 6, 0, 3]
    selected: list[int] = []
    for day in preferred_days:
        if day != delivery_day:
            selected.append(day)
        if len(selected) == 2:
            break
    return set(selected)


def _stable_discovery_day(start: date, delivery_day: int) -> int:
    preferred_days = [2, 3, 4, 1, 5, 0, 6]
    week_offset = start.isocalendar().week % len(preferred_days)
    ordered = preferred_days[week_offset:] + preferred_days[:week_offset]
    for day in ordered:
        if day != delivery_day:
            return day
    return 3


def _protein_limited_slot(slot: str, meal_type: str) -> bool:
    return meal_type in {"almuerzo", "cena"} or slot.startswith("colación")


def _protein_key(protein: str) -> str:
    ignored = {"de", "del", "para", "milanesa", "milanesas", "picada", "picado"}
    key = " ".join(sorted(_words(protein) - ignored))
    return key or protein.lower()


def _hard_blocked_protein(protein_key: str, blocked_proteins: dict[str, int] | None) -> bool:
    if not blocked_proteins:
        return False
    return protein_key == "atun" and blocked_proteins.get(protein_key, 0) >= 1


def _limited_ingredient_blocked(meal: Meal, ingredient_counts: dict[str, int] | None) -> bool:
    if not ingredient_counts:
        return False
    if "arroz" in meal.ingredients and ingredient_counts.get("arroz", 0) >= 1:
        return True
    if "fideos" in meal.ingredients and ingredient_counts.get("fideos", 0) >= 2:
        return True
    if "dannette o copa cindor" in meal.ingredients and ingredient_counts.get("dannette o copa cindor", 0) >= 1:
        return True
    return False


def _hard_blocked_limited_ingredient(meal: Meal, ingredient_counts: dict[str, int] | None) -> bool:
    if not ingredient_counts:
        return False
    return "dannette o copa cindor" in meal.ingredients and ingredient_counts.get("dannette o copa cindor", 0) >= 1


def _weather_score(meal: Meal, weather: dict[str, float | str] | None) -> int:
    if not weather:
        return 0
    profile = str(weather.get("profile", "templado"))
    haystack = _words(f"{meal.name} {meal.prep} {' '.join(meal.ingredients)} {' '.join(meal.tags)}")
    fresh = {"ensalada", "bowl", "tacos", "palta", "tomate", "lechuga", "pepino", "rucula"}
    warm = {"horno", "guiso", "guisadas", "tarta", "fideos", "pastas", "risotto", "sopa", "pure"}
    fryer = {"air", "fryer", "papas", "milanesa"}
    if profile == "calor":
        return 4 * len(haystack & fresh) - 3 * len(haystack & warm)
    if profile in {"frio", "lluvia"}:
        return 4 * len(haystack & warm) + 2 * len(haystack & fryer) - 2 * len(haystack & fresh)
    return 1 * len(haystack & fresh)


def _add_household_items(shopping: defaultdict[str, float], start: date, people: int) -> None:
    rotation_index = (start.isocalendar().week - 1) % len(HOUSEHOLD_ROTATION)
    for item, qty in HOUSEHOLD_ROTATION[rotation_index].items():
        shopping[item] += qty

    # Hygiene essentials for two people rotate weekly, but these basics are checked every week.
    if people >= 2:
        shopping["papel higienico"] += 1


def _words(text: str) -> set[str]:
    plain = _normalize_text(text)
    return {word.strip(".,;:()").lower() for word in plain.split() if len(word.strip(".,;:()")) > 2}


def _normalize_text(text: str) -> str:
    return normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
