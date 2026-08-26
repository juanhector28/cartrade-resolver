from app.carly_decision_room import build_decision, compare_decisions, evidence_for_car, execution_for_car


def _result(price=10500, second_price=9400):
    return {
        "phase": "recommendation",
        "profile": {
            "country": "sv",
            "primary_job": "first_car",
            "max_price": 12000,
            "max_km": 65000,
            "daily_km": 20,
        },
        "pool_size": 234,
        "recommendations": [
            {
                "id": 1, "url": "https://example.com/swift", "make": "Suzuki",
                "model": "Swift", "year": 2021, "km": 47000, "price_usd": price,
                "location": "San Salvador", "body_type": "hatchback",
            },
            {
                "id": 2, "url": "https://example.com/rio", "make": "Kia",
                "model": "RIO", "year": 2021, "km": 32424, "price_usd": second_price,
                "location": "San Salvador", "body_type": "sedan",
            },
        ],
        "explore": [],
    }


def test_decision_is_stable_and_opinionated():
    a = build_decision(_result(), country="sv")
    b = build_decision(_result(price=9900), country="sv")
    assert a["id"] == b["id"]
    assert a["status"] == "active"
    assert a["verdict"]["code"] == "start_here"
    assert "Suzuki Swift 2021" in a["verdict"]["headline"]
    assert a["considered_count"] == 234
    assert a["criteria"][1]["key"] == "max_price"


def test_evidence_separates_known_from_pending():
    car = _result()["recommendations"][0]
    ev = evidence_for_car(car)
    known_keys = {x["key"] for x in ev["known"]}
    pending_keys = {x["key"] for x in ev["pending"]}
    assert {"price", "km", "year", "location"}.issubset(known_keys)
    assert {"availability", "seller", "documents", "inspection"}.issubset(pending_keys)


def test_execution_has_one_next_action():
    car = _result()["recommendations"][0]
    ex = execution_for_car(car)
    assert ex["stage"] == "discovered"
    assert ex["next_action"]["id"] == "confirm_availability"

    car["availability_confirmed"] = True
    car["seller_verified"] = True
    car["documents_verified"] = True
    car["inspection_complete"] = True
    ex = execution_for_car(car)
    assert ex["stage"] == "ready_to_close"
    assert ex["next_action"]["id"] == "start_verified_purchase"


def test_market_watch_reports_price_drop_and_new_top():
    previous = build_decision(_result(), country="sv")
    current_result = _result(price=9000, second_price=9400)
    current_result["recommendations"] = list(reversed(current_result["recommendations"]))
    current = build_decision(current_result, country="sv")
    changes = compare_decisions(previous, current)
    kinds = {c["type"] for c in changes}
    assert "new_top_pick" in kinds
    assert "price_drop" in kinds
    assert "ranking_change" in kinds
