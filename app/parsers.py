"""Free-text parsers: extract make, model, year, km from titles/descriptions.

Strategy: regex with confidence scoring. Cross-reference make against a known
list; if model token follows make, mark high; if it's just a year regex, mark
medium; if we're guessing from context only, low.
"""
from __future__ import annotations
import re
from typing import Optional, Tuple
from .resolvers.base import Field

# Known makes commonly listed in El Salvador and LATAM. Order matters for
# multi-word makes (Land Rover, Alfa Romeo) — those come first.
KNOWN_MAKES = [
    "Land Rover", "Alfa Romeo", "Mercedes Benz", "Mercedes-Benz",
    "Aston Martin", "Rolls Royce", "Range Rover",
    "Toyota", "Honda", "Nissan", "Mazda", "Mitsubishi", "Subaru", "Suzuki",
    "Isuzu", "Lexus", "Acura", "Infiniti",
    "Hyundai", "Kia", "Daewoo", "SsangYong",
    "Ford", "Chevrolet", "GMC", "Cadillac", "Dodge", "Chrysler", "Jeep",
    "Ram", "Buick", "Lincoln", "Tesla",
    "Volkswagen", "VW", "BMW", "Audi", "Porsche", "Mercedes", "Mini",
    "Opel", "Seat", "Skoda", "Volvo",
    "Renault", "Peugeot", "Citroën", "Citroen", "Fiat", "Lancia",
    "Geely", "BYD", "Chery", "Great Wall", "JAC", "Haval", "MG", "Changan",
    "Tata", "Mahindra",
    "Ferrari", "Lamborghini", "Maserati", "Bentley", "Jaguar",
]


def extract_year(text: str) -> Optional[Tuple[int, str]]:
    """Find a plausible model year. Returns (year, confidence) or None."""
    if not text:
        return None
    # Years 1990-2026, must be word-boundaried
    candidates = re.findall(r"\b(19[9]\d|20[0-2]\d)\b", text)
    if not candidates:
        return None
    years = [int(c) for c in candidates if 1990 <= int(c) <= 2027]
    if not years:
        return None
    # If multiple, pick the most plausible (typically the highest, since
    # listings tend to be recent cars). High confidence if there's exactly one.
    if len(set(years)) == 1:
        return years[0], "high"
    return max(years), "medium"


def extract_make(text: str) -> Optional[Tuple[str, str]]:
    """Find a known make in text. Returns (make, confidence) or None."""
    if not text:
        return None
    t = text.lower()
    for make in KNOWN_MAKES:
        # word-boundary match, case-insensitive
        if re.search(r"\b" + re.escape(make.lower()) + r"\b", t):
            return make, "high"
    return None


def extract_model(text: str, make: Optional[str]) -> Optional[Tuple[str, str]]:
    """Extract model name as the token(s) right after the make in the text.
    Returns (model, confidence) or None.
    """
    if not text or not make:
        return None
    # Look for "<make> <token>" pattern, case-insensitive
    pat = re.compile(r"\b" + re.escape(make) + r"\s+([A-Za-z0-9\-]{2,20}(?:\s+[A-Za-z0-9\-]{2,15})?)",
                     re.IGNORECASE)
    m = pat.search(text)
    if not m:
        return None
    model = m.group(1).strip()
    # Strip common noise words and standalone years
    noise = {"el", "la", "lo", "los", "las", "de", "del", "en", "para",
             "automatic", "automatica", "manual", "usado", "nuevo", "venta"}
    parts = [p for p in model.split()
             if p.lower() not in noise
             and not re.fullmatch(r"(19|20)\d{2}", p)]
    if not parts:
        return None
    model = " ".join(parts[:2])  # keep at most 2 tokens
    return model, "medium"


def extract_km(text: str) -> Optional[Tuple[int, str]]:
    """Extract kilometres reading. Returns (km, confidence) or None."""
    if not text:
        return None
    # patterns: "5,790 km", "5790 km", "kilometraje5,790", "km: 12000"
    patterns = [
        r"kilometraje[:\s]*([0-9][\d,\.]{1,8})",
        r"\b([0-9][\d,\.]{1,8})\s*km\b",
        r"\bkm[:\s]+([0-9][\d,\.]{1,8})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", "").replace(".", "")
            try:
                km = int(raw)
                if 0 < km < 1_000_000:
                    return km, "high"
            except ValueError:
                continue
    return None


def extract_price_usd(text: str) -> Optional[Tuple[int, str]]:
    """Extract USD price. Returns (price, confidence) or None.
    Handles formats: "$ 28,500", "$28,500", "USD 14,000", "14500 USD".
    """
    if not text:
        return None
    patterns = [
        r"\$\s*([0-9][\d,\.]{2,9})",
        r"USD\s*([0-9][\d,\.]{2,9})",
        r"([0-9][\d,\.]{2,9})\s*USD\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", "").replace(".", "")
            try:
                price = int(raw)
                if 500 <= price <= 200_000:
                    return price, "high"
            except ValueError:
                continue
    return None


def extract_transmission(text: str) -> Optional[Tuple[str, str]]:
    if not text:
        return None
    t = text.lower()
    if re.search(r"\b(autom[aá]tica|automatic|automatico|at\b)", t):
        return "Automático", "high"
    if re.search(r"\b(manual|mt\b|estandar|estándar)", t):
        return "Manual", "high"
    return None


def extract_fuel(text: str) -> Optional[Tuple[str, str]]:
    if not text:
        return None
    t = text.lower()
    if re.search(r"\b(diesel|di[eé]sel)\b", t):
        return "Diésel", "high"
    if re.search(r"\b(h[ií]brido|hybrid)\b", t):
        return "Híbrido", "high"
    if re.search(r"\b(el[eé]ctrico|electric|ev)\b", t):
        return "Eléctrico", "high"
    if re.search(r"\b(gasolina|gasoline|petrol|nafta)\b", t):
        return "Gasolina", "high"
    return None


def to_field(result: Optional[Tuple]) -> Optional[Field]:
    """Convert (value, confidence) tuple → Field, or None."""
    if result is None:
        return None
    value, confidence = result
    return Field(value=value, confidence=confidence)
