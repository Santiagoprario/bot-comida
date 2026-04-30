from __future__ import annotations

import re
from typing import Any


def parse_key_values(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_part in re.split(r"[,;\n]+", text):
        part = raw_part.strip()
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
        elif ":" in part:
            key, value = part.split(":", 1)
        else:
            continue
        key = normalize_key(key)
        value = value.strip()
        if key in {"personas", "calorias", "presupuesto"}:
            number = re.sub(r"[^\d]", "", value)
            result[key] = int(number) if number else value
        else:
            result[key] = value
    return result


def parse_offer(text: str) -> tuple[str, str | None, str | None]:
    text = text.strip()
    price_match = re.search(r"(\$?\s*\d+(?:[.,]\d+)?)", text)
    price = price_match.group(1).replace(" ", "") if price_match else None
    item = text[: price_match.start()].strip(" -,:") if price_match else text
    note = text[price_match.end() :].strip(" -,:") if price_match else None
    return item or text, price, note or None


def normalize_key(key: str) -> str:
    cleaned = key.strip().lower()
    replacements = {
        "objetivo": "objetivo",
        "personas": "personas",
        "persona": "personas",
        "calorias": "calorias",
        "calorías": "calorias",
        "presupuesto": "presupuesto",
        "restricciones": "restricciones",
        "restriccion": "restricciones",
        "restricción": "restricciones",
        "evitar": "evitar",
        "preferencias": "preferencias",
        "prefiero": "preferencias",
        "cocina": "cocina",
    }
    return replacements.get(cleaned, cleaned.replace(" ", "_"))
