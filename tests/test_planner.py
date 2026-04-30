from datetime import date

from menu_bot.planner import generate_week, week_start_for, _protein_key


def test_week_start_for_monday():
    assert week_start_for(date(2026, 4, 30)).isoformat() == "2026-04-27"


def test_generate_week_creates_seven_days_and_shopping_list():
    plan, shopping = generate_week(
        date(2026, 4, 27),
        {"personas": 2},
        {"evitar": "atún"},
        [{"item": "pollo oferta", "price": None, "note": None}],
    )

    assert len(plan) == 7
    assert all(len(day["comidas"]) == 5 for day in plan)
    assert all("colación 2" not in day["comidas"] for day in plan)
    assert any("pollo" in item for item in shopping)
    assert all("Atún" not in meal["nombre"] for day in plan for meal in day["comidas"].values())


def test_custom_rules_limit_repetition_and_force_milanesas():
    plan, shopping = generate_week(
        date(2026, 4, 27),
        {
            "personas": 2,
            "ciudad": "Mar del Plata",
            "objetivo": "bajar grasa",
        },
        {
            "evitar": "kiwi cerdo",
            "preferencias": "carne pollo atun fideos arroz verduras frutas",
            "reglas": "delivery postre milanesas dos veces arroz una vez fideos maximo dos air fryer",
        },
        [{"item": "nalga oferta"}, {"item": "papas mcain oferta"}],
    )

    meals = [meal for day in plan for meal in day["comidas"].values()]
    names = [meal["nombre"].lower() for meal in meals]
    main_proteins = [
        _protein_key(day["comidas"][slot]["proteina"])
        for day in plan
        for slot in ("almuerzo", "cena")
        if day["comidas"][slot]["proteina"] != "delivery"
    ]

    assert sum("milanesa" in name or "milanesas" in name for name in names) >= 2
    assert sum("atún" in name or "atun" in name for name in names) <= 1
    assert len(main_proteins) == len(set(main_proteins))
    assert shopping.get("arroz", 0) <= 160
    assert sum("fideos" in name or "pastas" in name for name in names) <= 2
    assert any("papas tipo McCain para air fryer" == item for item in shopping)
    assert any(item in shopping for item in ("papel higienico", "detergente", "rollo de cocina"))
