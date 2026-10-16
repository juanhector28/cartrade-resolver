"""Conservative constraints for Carly search."""
import re
import unicodedata

def normalize(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value or "").lower()) if not unicodedata.combining(c))

MODELS = {"toyota": ("rav4", "corolla cross", "corolla", "raize", "tacoma"),
          "honda": ("cr-v", "hr-v", "civic"),
          "porsche": ("macan",), "volkswagen": ("amarok",)}

def parse(text):
    t = normalize(text)
    pairs = [(make, model) for make, models in MODELS.items()
             for model in models if re.search(r"\b" + re.escape(model) + r"\b", t)]
    def number(pattern):
        match = re.search(pattern, t)
        return int(match.group(1).replace(",", "")) if match else None
    return {
        "models": pairs,
        "body": "pickup" if re.search(r"\b(pickup|pick up)\b", t) else
                "suv" if re.search(r"\b(suv|crossover)\b", t) else None,
        "year_min": number(r"\b(20\d\d)\s*(?:en adelante|o posterior)"),
        "km_max": number(r"menos de\s*([\d,]+)\s*km"),
        "price_max": number(r"(?:presupuesto maximo de|precio maximo de|hasta)\s*\$\s*([\d,]+)"),
        "monthly_max": number(r"\$\s*([\d,]+)\s*(?:mensuales|al mes)"),
        "down_payment": number(r"(?:dar|prima de)\s*\$\s*([\d,]+)"),
        "fuel": "diesel" if "diesel" in t else None,
        "drive": "4x4" if "4x4" in t else None,
    }

def eligible(car, intent):
    if intent["models"] and not any(
        normalize(car.get("make")) == make and
        normalize(car.get("model")).startswith(model)
        for make, model in intent["models"]
    ):
        return False
    if intent["body"] and normalize(car.get("body_type")) != intent["body"]:
        return False
    for name, key, comparison in (
        ("price_max", "price_usd", "max"),
        ("monthly_max", "monthly_est", "max"),
        ("year_min", "year", "min"),
        ("km_max", "km", "strict_max"),
    ):
        target = intent[name]
        if target is None:
            continue
        try:
            current = float(car.get(key))
        except (ValueError, TypeError):
            return False
        if comparison == "max" and current > target:
            return False
        if comparison == "strict_max" and current >= target:
            return False
        if comparison == "min" and current < target:
            return False
    if intent["fuel"] and normalize(car.get("fuel_type")) != intent["fuel"]:
        return False
    if intent["drive"] and normalize(car.get("drivetrain")) not in ("4x4", "4wd"):
        return False
    return True
