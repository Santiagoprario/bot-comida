from __future__ import annotations

from copy import deepcopy
from typing import Any


PRESETS: dict[str, dict[str, Any]] = {
    "sanda": {
        "label": "Comida Sanda",
        "description": "2 adultos y 2 chicos, comida argentina familiar, Santa Clara del Mar.",
        "profile": {
            "familia": "sanda",
            "personas": 4,
            "integrantes": "2 adultos y 2 chicos",
            "objetivo": "comida argentina familiar saludable, rica y rendidora",
            "pais": "Argentina",
            "provincia": "Buenos Aires",
            "partido": "Mar Chiquita",
            "ciudad": "Santa Clara del Mar",
            "weather_latitude": -37.836,
            "weather_longitude": -57.508,
        },
        "conditions": {
            "estilo": "comida argentina familiar, casera, variada y apta para chicos",
            "preferencias": (
                "milanesas tartas empanadas pastas arroz pollo carne hamburguesas guisos "
                "verduras frutas huevos tostadas sandwiches caseros"
            ),
            "evitar": "picante fuerte alcohol en preparaciones para chicos platos demasiado sofisticados",
            "reglas": (
                "Siempre calcular porciones para 4 personas: 2 adultos y 2 chicos. Priorizar comida "
                "argentina familiar, rica, simple de comprar y rendidora. Incluir verduras y frutas de "
                "forma concreta en cada comida cuando corresponda. Las recetas deben funcionar para una "
                "mesa familiar y evitar sabores muy picantes. Ajustar platos segun el clima de Santa Clara del Mar."
            ),
            "chefs": "Paulina Cocina, Narda Lepes, German Martitegui, Donato De Santis, Petersen",
        },
    }
}


def list_presets() -> dict[str, dict[str, Any]]:
    return deepcopy(PRESETS)


def get_preset(name: str) -> dict[str, Any] | None:
    key = _normalize_name(name)
    preset = PRESETS.get(key)
    return deepcopy(preset) if preset else None


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_")
