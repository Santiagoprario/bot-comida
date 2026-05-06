from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any
from unicodedata import normalize
from urllib.parse import quote

import httpx


DISCO_SEARCH_URL = "https://www.disco.com.ar/api/catalog_system/pub/products/search"
DEFAULT_SALES_CHANNEL = "33"
DISCO_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Carnes y proteínas", ("asado", "atún", "bife", "hamburguesa", "huevo", "merluza", "milanesa", "nalga", "pollo", "vacío")),
    ("Frutas y verduras", ("banana", "batata", "cebolla", "espinaca", "fruta", "lechuga", "palta", "papa", "pepino", "pimiento", "rucula", "tomate", "zanahoria", "zapallo")),
    ("Lácteos", ("danette", "leche", "manteca", "queso", "ricota", "yogur")),
    ("Almacén", ("arroz", "café", "cafe", "cous cous", "dulce", "fideos", "galletas", "garbanzos", "granola", "lentejas", "maní", "mermelada", "rebozador")),
    ("Panificados y masas", ("pan", "prepizza", "tapa", "tortillas")),
    ("Congelados", ("mccain", "papas tipo")),
    ("Limpieza e higiene", ("algodon", "alcohol", "desodorante", "detergente", "jabon", "limpiavidrios", "pano", "papel", "pasta dental", "rollo", "separadores")),
)


@dataclass(frozen=True)
class DiscoProduct:
    name: str
    brand: str
    price: float
    list_price: float | None
    available: bool
    package_quantity: float | None
    package_unit: str | None
    link: str
    promotions: tuple[str, ...]


@dataclass(frozen=True)
class DiscoLine:
    ingredient: str
    quantity: float
    product: DiscoProduct | None
    units: int
    subtotal: float


def search_disco_products(query: str, sales_channel: str = DEFAULT_SALES_CHANNEL, limit: int = 5) -> list[DiscoProduct]:
    url = f"{DISCO_SEARCH_URL}?ft={quote(query)}&sc={quote(sales_channel)}"
    try:
        response = httpx.get(
            url,
            headers={
                "accept": "application/json",
                "user-agent": "menu-telegram-bot/1.0",
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return []

    products = [_parse_product(raw) for raw in payload[: max(limit * 3, limit)]]
    products = [product for product in products if product is not None]
    products.sort(
        key=lambda product: (
            not product.available,
            -_match_score(product, query),
            product.price,
            product.name,
        )
    )
    return products[:limit]


def simulate_disco_purchase(
    shopping: dict[str, float],
    sales_channel: str = DEFAULT_SALES_CHANNEL,
    max_items: int = 14,
) -> tuple[list[DiscoLine], list[str]]:
    lines: list[DiscoLine] = []
    missing: list[str] = []
    for ingredient, quantity in list(shopping.items())[:max_items]:
        products = search_disco_products(_search_query_for(ingredient), sales_channel=sales_channel, limit=4)
        product = next((candidate for candidate in products if candidate.available), products[0] if products else None)
        if not product:
            missing.append(ingredient)
            lines.append(DiscoLine(ingredient, quantity, None, 0, 0))
            continue
        units = _estimate_units(quantity, product)
        lines.append(DiscoLine(ingredient, quantity, product, units, units * product.price))
    return lines, missing


def format_disco_search(products: list[DiscoProduct], query: str) -> str:
    if not products:
        return f"No encontré productos en Disco para: {query}"
    lines = [f"Disco: resultados para {query}"]
    for product in products:
        stock = "stock" if product.available else "sin stock"
        package = _format_package(product)
        promo = f" | {'; '.join(product.promotions[:2])}" if product.promotions else ""
        lines.append(f"- {product.name} ({product.brand}) {package}: {_money(product.price)} | {stock}{promo}")
    return "\n".join(lines)


def format_disco_simulation(lines: list[DiscoLine], missing: list[str], sales_channel: str) -> str:
    if not lines:
        return "No hay compra semanal para simular. Usá /generar_semana primero."

    total = sum(line.subtotal for line in lines)
    output = [
        f"Simulación Disco (sc={sales_channel})",
        "Precios públicos estimados; la cuenta/localidad puede cambiar stock y final.",
    ]
    for line in lines:
        quantity = int(line.quantity) if line.quantity == int(line.quantity) else round(line.quantity, 1)
        if not line.product:
            output.append(f"- {line.ingredient}: {quantity} aprox. | no encontrado")
            continue
        package = _format_package(line.product)
        promo = f" | {'; '.join(line.product.promotions[:1])}" if line.product.promotions else ""
        output.append(
            f"- {line.ingredient}: {quantity} aprox. -> {line.units} x {line.product.name} "
            f"{package} = {_money(line.subtotal)}{promo}"
        )
    output.append(f"\nTotal parcial estimado: {_money(total)}")
    if missing:
        output.append("Sin match: " + ", ".join(missing))
    output.append("Para ubicación real en Disco usá /disco_config sc=NUMERO, zona=texto.")
    return "\n".join(output)


def format_disco_product_list(lines: list[DiscoLine], missing: list[str], sales_channel: str) -> str:
    if not lines:
        return "Productos Disco: sin compra semanal para mapear."

    total = sum(line.subtotal for line in lines)
    output = [
        f"Productos sugeridos en Disco (sc={sales_channel})",
        "Estimado por productos reales del catálogo online.",
    ]
    grouped: dict[str, list[str]] = {}
    for line in lines:
        quantity = _format_quantity(line.quantity)
        if not line.product:
            grouped.setdefault(_shopping_category_for(line.ingredient), []).append(
                f"- {line.ingredient}: {quantity} -> sin producto sugerido"
            )
            continue
        promo = f" | promo: {'; '.join(line.product.promotions[:1])}" if line.product.promotions else ""
        grouped.setdefault(_shopping_category_for(line.ingredient), []).append(
            f"- {line.ingredient}: {quantity} -> {line.units} x {line.product.name} "
            f"({_money(line.product.price)} c/u) = {_money(line.subtotal)}{promo}"
        )
    for category, _keywords in DISCO_CATEGORIES:
        entries = grouped.pop(category, [])
        if entries:
            output.append(f"\n{category}")
            output.extend(sorted(entries))
    if grouped:
        output.append("\nVarios")
        for entries in grouped.values():
            output.extend(sorted(entries))
    output.append(f"Total estimado Disco: {_money(total)}")
    if missing:
        output.append("Revisar manualmente: " + ", ".join(missing))
    return "\n".join(output)


def _parse_product(raw: dict[str, Any]) -> DiscoProduct | None:
    item = (raw.get("items") or [{}])[0]
    seller = _default_seller(item.get("sellers") or [])
    offer = seller.get("commertialOffer") or {}
    price = _safe_float(offer.get("Price"))
    if price is None or price <= 0:
        return None

    product_data = _json_first(raw.get("ProductData"))
    package_quantity = _safe_float(product_data.get("unit_multiplier_un"))
    package_unit = product_data.get("measurement_unit_un")
    promotions = tuple(
        value
        for value in {
            **(raw.get("clusterHighlights") or {}),
            **(raw.get("productClusters") or {}),
        }.values()
        if _looks_like_promotion(str(value))
    )
    return DiscoProduct(
        name=str(raw.get("productName") or item.get("name") or "Producto sin nombre"),
        brand=str(raw.get("brand") or ""),
        price=price,
        list_price=_safe_float(offer.get("ListPrice")),
        available=bool(offer.get("IsAvailable")),
        package_quantity=package_quantity,
        package_unit=str(package_unit) if package_unit else None,
        link=str(raw.get("link") or ""),
        promotions=promotions,
    )


def _default_seller(sellers: list[dict[str, Any]]) -> dict[str, Any]:
    for seller in sellers:
        if seller.get("sellerDefault"):
            return seller
    return sellers[0] if sellers else {}


def _json_first(values: Any) -> dict[str, Any]:
    if not values:
        return {}
    try:
        return json.loads(values[0])
    except (TypeError, ValueError, json.JSONDecodeError, IndexError):
        return {}


def _estimate_units(quantity: float, product: DiscoProduct) -> int:
    if quantity <= 0:
        return 1
    base = _package_base_amount(product)
    if quantity < 20 or not base:
        return max(1, math.ceil(quantity))
    return max(1, math.ceil(quantity / base))


def _package_base_amount(product: DiscoProduct) -> float | None:
    if not product.package_quantity or not product.package_unit:
        return None
    unit = product.package_unit.lower().strip(".")
    if unit in {"kg", "kilo", "kilos"}:
        return product.package_quantity * 1000
    if unit in {"lt", "l", "litro", "litros"}:
        return product.package_quantity * 1000
    if unit in {"gr", "g", "gramo", "gramos", "ml", "cc"}:
        return product.package_quantity
    return None


def _search_query_for(ingredient: str) -> str:
    replacements = {
        "leche zero lactosa": "leche la serenisima zerolact",
        "hamburguesas Paty": "hamburguesa paty",
        "dannette o copa cindor": "danette copa cindor",
        "papas tipo McCain para air fryer": "papas mccain",
        "pan rallado": "rebozador",
        "fideos": "fideos matarazzo",
    }
    return replacements.get(ingredient, ingredient)


def _shopping_category_for(item: str) -> str:
    normalized = _normalize_text(item)
    matches: list[tuple[int, str]] = []
    for category, keywords in DISCO_CATEGORIES:
        for keyword in keywords:
            normalized_keyword = _normalize_text(keyword)
            if normalized_keyword in normalized:
                matches.append((len(normalized_keyword), category))
    return sorted(matches, reverse=True)[0][1] if matches else "Varios"


def _match_score(product: DiscoProduct, query: str) -> int:
    haystack = f"{product.name} {product.brand}".lower()
    score = 0
    for word in query.lower().split():
        if len(word) <= 2:
            continue
        if word in haystack:
            score += 2
    if query.lower() in haystack:
        score += 5
    if product.package_quantity and product.package_quantity >= 900:
        score += 1
    return score


def _looks_like_promotion(value: str) -> bool:
    text = value.lower()
    return any(word in text for word in ("oferta", "off", "2x1", "3x2", "4x3", "descuento", "%"))


def _format_package(product: DiscoProduct) -> str:
    if not product.package_quantity or not product.package_unit:
        return ""
    quantity = (
        int(product.package_quantity)
        if product.package_quantity == int(product.package_quantity)
        else product.package_quantity
    )
    return f"x {quantity} {product.package_unit}"


def _format_quantity(value: float) -> str:
    quantity = int(value) if value == int(value) else round(value, 1)
    unit = "u" if value < 20 else "g/ml aprox."
    return f"{quantity} {unit}"


def _money(value: float) -> str:
    formatted = f"{value:,.0f}".replace(",", ".")
    return f"${formatted}"


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(value: str) -> str:
    return "".join(char for char in normalize("NFD", value.lower()) if char.isascii())
