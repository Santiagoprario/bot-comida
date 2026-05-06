from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def _dish_from_row(row: sqlite3.Row) -> dict[str, Any]:
    dish = dict(row)
    dish["tags"] = json.loads(dish["tags"])
    dish["ingredients"] = json.loads(dish["ingredients"])
    dish["public"] = bool(dish["public"])
    dish["active"] = bool(dish["active"])
    dish["avg_rating"] = float(dish["avg_rating"])
    dish["rating_count"] = int(dish["rating_count"])
    return dish


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

                CREATE TABLE IF NOT EXISTS web_accounts (
                    email TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS community_dishes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    slot TEXT NOT NULL,
                    protein TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    ingredients TEXT NOT NULL DEFAULT '{}',
                    prep TEXT NOT NULL,
                    public INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS dish_ratings (
                    dish_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    rating INTEGER NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(dish_id, chat_id)
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

    def create_web_account(
        self,
        email: str,
        chat_id: int,
        password_hash: str,
        display_name: str | None = None,
    ) -> None:
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ValueError("email is required")
        self.authorize_user(chat_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO web_accounts(email, chat_id, password_hash, display_name)
                VALUES (?, ?, ?, ?)
                """,
                (normalized_email, chat_id, password_hash, display_name),
            )

    def get_web_account(self, email: str) -> dict[str, Any] | None:
        normalized_email = email.strip().lower()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT email, chat_id, password_hash, display_name, created_at, updated_at
                FROM web_accounts
                WHERE email = ?
                """,
                (normalized_email,),
            ).fetchone()
        return dict(row) if row else None

    def list_web_accounts(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT email, chat_id, display_name, created_at, updated_at
                FROM web_accounts
                ORDER BY email
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def count_web_accounts(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM web_accounts").fetchone()
        return int(row["total"])

    def create_community_dish(
        self,
        chat_id: int,
        name: str,
        slot: str,
        protein: str,
        tags: list[str],
        ingredients: dict[str, float],
        prep: str,
        public: bool = True,
        active: bool = True,
    ) -> int:
        self.ensure_user(chat_id)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO community_dishes(
                    chat_id, name, slot, protein, tags, ingredients, prep, public, active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    name.strip(),
                    slot.strip().lower(),
                    protein.strip(),
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(ingredients, ensure_ascii=False),
                    prep.strip(),
                    1 if public else 0,
                    1 if active else 0,
                ),
            )
        return int(cursor.lastrowid)

    def list_community_dishes(self, viewer_chat_id: int | None = None, active_only: bool = False) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = []
        if viewer_chat_id is not None:
            where.append("(dish.public = 1 OR dish.chat_id = ?)")
            params.append(viewer_chat_id)
        else:
            where.append("dish.public = 1")
        if active_only:
            where.append("dish.active = 1")
        where_sql = " AND ".join(where)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    dish.*,
                    COALESCE(AVG(rating.rating), 0) AS avg_rating,
                    COUNT(rating.rating) AS rating_count
                FROM community_dishes dish
                LEFT JOIN dish_ratings rating ON rating.dish_id = dish.id
                WHERE {where_sql}
                GROUP BY dish.id
                ORDER BY avg_rating DESC, rating_count DESC, dish.created_at DESC
                """,
                params,
            ).fetchall()
        return [_dish_from_row(row) for row in rows]

    def rate_community_dish(self, dish_id: int, chat_id: int, rating: int, note: str | None = None) -> None:
        bounded_rating = min(5, max(1, int(rating)))
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO dish_ratings(dish_id, chat_id, rating, note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(dish_id, chat_id) DO UPDATE SET
                    rating = excluded.rating,
                    note = excluded.note,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (dish_id, chat_id, bounded_rating, note),
            )

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
