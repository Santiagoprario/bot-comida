from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    profile TEXT NOT NULL DEFAULT '{}',
                    conditions TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS offers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    item TEXT NOT NULL,
                    price TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS weekly_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    week_start TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    shopping_list TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(chat_id, week_start)
                );

                CREATE TABLE IF NOT EXISTS product_preferences (
                    chat_id INTEGER NOT NULL,
                    ingredient TEXT NOT NULL,
                    preferred_product TEXT NOT NULL,
                    brand TEXT,
                    package_size TEXT,
                    category TEXT,
                    notes TEXT,
                    times_seen INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(chat_id, ingredient)
                );

                CREATE TABLE IF NOT EXISTS pantry_items (
                    chat_id INTEGER NOT NULL,
                    item TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(chat_id, item)
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    item TEXT NOT NULL,
                    sentiment TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS authorized_users (
                    chat_id INTEGER PRIMARY KEY,
                    invited_by INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS invites (
                    code TEXT PRIMARY KEY,
                    created_by INTEGER NOT NULL,
                    used_by INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    used_at TEXT
                );

                CREATE TABLE IF NOT EXISTS shopping_item_state (
                    chat_id INTEGER NOT NULL,
                    week_start TEXT NOT NULL,
                    item TEXT NOT NULL,
                    checked INTEGER NOT NULL DEFAULT 0,
                    bought_quantity REAL,
                    leftover_quantity REAL,
                    note TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(chat_id, week_start, item)
                );
                """
            )

    def ensure_user(self, chat_id: int) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO users(chat_id) VALUES (?)", (chat_id,))

    def get_user(self, chat_id: int) -> dict[str, Any]:
        self.ensure_user(chat_id)
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        return {
            "chat_id": chat_id,
            "profile": json.loads(row["profile"]),
            "conditions": json.loads(row["conditions"]),
        }

    def update_profile(self, chat_id: int, values: dict[str, Any]) -> dict[str, Any]:
        user = self.get_user(chat_id)
        profile = {**user["profile"], **values}
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET profile = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
                (json.dumps(profile, ensure_ascii=False), chat_id),
            )
        return profile

    def update_conditions(self, chat_id: int, values: dict[str, Any]) -> dict[str, Any]:
        user = self.get_user(chat_id)
        conditions = {**user["conditions"], **values}
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET conditions = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
                (json.dumps(conditions, ensure_ascii=False), chat_id),
            )
        return conditions

    def add_offer(self, chat_id: int, item: str, price: str | None, note: str | None) -> None:
        self.ensure_user(chat_id)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO offers(chat_id, item, price, note) VALUES (?, ?, ?, ?)",
                (chat_id, item.strip().lower(), price, note),
            )

    def list_offers(self, chat_id: int, limit: int = 30) -> list[dict[str, str | None]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT item, price, note, created_at
                FROM offers
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_offers(self, chat_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM offers WHERE chat_id = ?", (chat_id,))

    def save_weekly_plan(
        self,
        chat_id: int,
        week_start: str,
        plan: list[dict[str, Any]],
        shopping_list: dict[str, float],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO weekly_plans(chat_id, week_start, plan, shopping_list)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, week_start) DO UPDATE SET
                    plan = excluded.plan,
                    shopping_list = excluded.shopping_list,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    chat_id,
                    week_start,
                    json.dumps(plan, ensure_ascii=False),
                    json.dumps(shopping_list, ensure_ascii=False),
                ),
            )

    def get_weekly_plan(self, chat_id: int, week_start: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT plan, shopping_list FROM weekly_plans WHERE chat_id = ? AND week_start = ?",
                (chat_id, week_start),
            ).fetchone()
        if not row:
            return None
        return {
            "plan": json.loads(row["plan"]),
            "shopping_list": json.loads(row["shopping_list"]),
        }

    def list_chat_ids(self) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT chat_id FROM users").fetchall()
        return [int(row["chat_id"]) for row in rows]

    def upsert_product_preference(
        self,
        chat_id: int,
        ingredient: str,
        preferred_product: str,
        brand: str | None = None,
        package_size: str | None = None,
        category: str | None = None,
        notes: str | None = None,
    ) -> None:
        self.ensure_user(chat_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO product_preferences(
                    chat_id, ingredient, preferred_product, brand, package_size, category, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, ingredient) DO UPDATE SET
                    preferred_product = excluded.preferred_product,
                    brand = excluded.brand,
                    package_size = excluded.package_size,
                    category = excluded.category,
                    notes = excluded.notes,
                    times_seen = product_preferences.times_seen + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    chat_id,
                    ingredient.strip().lower(),
                    preferred_product.strip(),
                    brand,
                    package_size,
                    category,
                    notes,
                ),
            )

    def get_product_preferences(self, chat_id: int) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT ingredient, preferred_product, brand, package_size, category, notes, times_seen
                FROM product_preferences
                WHERE chat_id = ?
                ORDER BY ingredient
                """,
                (chat_id,),
            ).fetchall()
        return {row["ingredient"]: dict(row) for row in rows}

    def upsert_pantry_item(self, chat_id: int, item: str, quantity: float = 1) -> None:
        self.ensure_user(chat_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pantry_items(chat_id, item, quantity)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, item) DO UPDATE SET
                    quantity = excluded.quantity,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (chat_id, item.strip().lower(), quantity),
            )

    def list_pantry_items(self, chat_id: int) -> dict[str, float]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT item, quantity FROM pantry_items WHERE chat_id = ? ORDER BY item",
                (chat_id,),
            ).fetchall()
        return {row["item"]: float(row["quantity"]) for row in rows}

    def clear_pantry(self, chat_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM pantry_items WHERE chat_id = ?", (chat_id,))

    def get_shopping_item_states(self, chat_id: int, week_start: str) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT item, checked, bought_quantity, leftover_quantity, note, updated_at
                FROM shopping_item_state
                WHERE chat_id = ? AND week_start = ?
                ORDER BY item
                """,
                (chat_id, week_start),
            ).fetchall()
        return {
            row["item"]: {
                "checked": bool(row["checked"]),
                "bought_quantity": row["bought_quantity"],
                "leftover_quantity": row["leftover_quantity"],
                "note": row["note"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def upsert_shopping_item_state(
        self,
        chat_id: int,
        week_start: str,
        item: str,
        checked: bool = False,
        bought_quantity: float | None = None,
        leftover_quantity: float | None = None,
        note: str | None = None,
    ) -> None:
        normalized = item.strip().lower()
        if not normalized:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO shopping_item_state(
                    chat_id, week_start, item, checked, bought_quantity, leftover_quantity, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, week_start, item) DO UPDATE SET
                    checked = excluded.checked,
                    bought_quantity = excluded.bought_quantity,
                    leftover_quantity = excluded.leftover_quantity,
                    note = excluded.note,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    chat_id,
                    week_start,
                    normalized,
                    1 if checked else 0,
                    bought_quantity,
                    leftover_quantity,
                    note,
                ),
            )

    def clear_shopping_item_states(self, chat_id: int, week_start: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM shopping_item_state WHERE chat_id = ? AND week_start = ?",
                (chat_id, week_start),
            )

    def add_feedback(self, chat_id: int, item: str, sentiment: str, note: str | None = None) -> None:
        self.ensure_user(chat_id)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO feedback(chat_id, item, sentiment, note) VALUES (?, ?, ?, ?)",
                (chat_id, item.strip().lower(), sentiment, note),
            )

    def authorize_user(self, chat_id: int, invited_by: int | None = None) -> None:
        self.ensure_user(chat_id)
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO authorized_users(chat_id, invited_by) VALUES (?, ?)",
                (chat_id, invited_by),
            )

    def is_authorized_user(self, chat_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM authorized_users WHERE chat_id = ?", (chat_id,)).fetchone()
        return row is not None

    def create_invite(self, created_by: int) -> str:
        self.authorize_user(created_by)
        code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
        with self.connect() as conn:
            conn.execute("INSERT INTO invites(code, created_by) VALUES (?, ?)", (code, created_by))
        return code

    def consume_invite(self, code: str, used_by: int) -> bool:
        normalized = code.strip().upper()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT created_by, used_by FROM invites WHERE code = ?",
                (normalized,),
            ).fetchone()
            if not row or row["used_by"] is not None:
                return False
            conn.execute(
                "UPDATE invites SET used_by = ?, used_at = CURRENT_TIMESTAMP WHERE code = ?",
                (used_by, normalized),
            )
        self.authorize_user(used_by, int(row["created_by"]))
        return True
