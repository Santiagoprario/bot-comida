from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .db import Database
from .presets import get_preset


def seed_default_user(db: Database) -> None:
    chat_id = os.getenv("DEFAULT_CHAT_ID", "").strip()
    if not chat_id:
        return

    seed_path = Path(os.getenv("SEED_PATH", "data/default_seed.json"))
    if not seed_path.exists():
        return

    data: dict[str, Any] = json.loads(seed_path.read_text(encoding="utf-8"))
    _seed_user(
        db,
        int(chat_id),
        data.get("profile", {}),
        data.get("conditions", {}),
        data.get("product_preferences", []),
    )

    for extra_user in data.get("users", []):
        extra_chat_id = extra_user.get("chat_id")
        if not extra_chat_id:
            continue
        preset = get_preset(str(extra_user.get("preset", ""))) if extra_user.get("preset") else None
        profile = {**(preset or {}).get("profile", {}), **extra_user.get("profile", {})}
        conditions = {**(preset or {}).get("conditions", {}), **extra_user.get("conditions", {})}
        _seed_user(
            db,
            int(extra_chat_id),
            profile,
            conditions,
            extra_user.get("product_preferences", []),
        )
        db.authorize_user(int(extra_chat_id))


def _seed_user(
    db: Database,
    chat_id: int,
    profile: dict[str, Any],
    conditions: dict[str, Any],
    product_preferences: list[dict[str, Any]],
) -> None:
    user = db.get_user(chat_id)
    if not user["profile"]:
        db.update_profile(chat_id, profile)
    if not user["conditions"]:
        db.update_conditions(chat_id, conditions)

    for preference in product_preferences:
        db.upsert_product_preference(
            chat_id,
            preference["ingredient"],
            preference["preferred_product"],
            preference.get("brand"),
            preference.get("package_size"),
            preference.get("category"),
            preference.get("notes"),
        )
