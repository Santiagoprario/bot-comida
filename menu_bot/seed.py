from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .db import Database


def seed_default_user(db: Database) -> None:
    chat_id = os.getenv("DEFAULT_CHAT_ID", "").strip()
    if not chat_id:
        return

    seed_path = Path(os.getenv("SEED_PATH", "data/default_seed.json"))
    if not seed_path.exists():
        return

    data: dict[str, Any] = json.loads(seed_path.read_text(encoding="utf-8"))
    numeric_chat_id = int(chat_id)
    user = db.get_user(numeric_chat_id)
    if not user["profile"]:
        db.update_profile(numeric_chat_id, data.get("profile", {}))
    if not user["conditions"]:
        db.update_conditions(numeric_chat_id, data.get("conditions", {}))

    for preference in data.get("product_preferences", []):
        db.upsert_product_preference(
            numeric_chat_id,
            preference["ingredient"],
            preference["preferred_product"],
            preference.get("brand"),
            preference.get("package_size"),
            preference.get("category"),
            preference.get("notes"),
        )
