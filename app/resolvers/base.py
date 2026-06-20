"""Shared types and helpers for all resolvers.

Each resolver returns a Listing populated with Field(value, confidence) entries.
The confidence level guides the frontend: high = pre-fill confidently,
medium = pre-fill with a "confirm" badge, low = leave the field for the user
to enter but show our guess as a suggestion.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Literal, Any
from datetime import datetime, timezone

Confidence = Literal["high", "medium", "low"]
Platform = Literal["encuentra24", "olx", "facebook", "mercadolibre", "unknown"]


@dataclass
class Field:
    value: Any
    confidence: Confidence

    def to_dict(self) -> dict:
        return {"value": self.value, "confidence": self.confidence}


@dataclass
class Listing:
    platform: Platform
    url: str
    title: Optional[Field] = None
    make: Optional[Field] = None
    model: Optional[Field] = None
    year: Optional[Field] = None
    price_usd: Optional[Field] = None
    price_local: Optional[Field] = None
    currency: Optional[Field] = None
    km: Optional[Field] = None
    transmission: Optional[Field] = None
    fuel: Optional[Field] = None
    location: Optional[Field] = None
    description: Optional[Field] = None
    photos: List[str] = field(default_factory=list)
    seller_name: Optional[Field] = None
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    errors: List[str] = field(default_factory=list)
    cached: bool = False

    def to_dict(self) -> dict:
        d = {
            "platform": self.platform,
            "url": self.url,
            "photos": self.photos,
            "scraped_at": self.scraped_at,
            "errors": self.errors,
            "cached": self.cached,
        }
        for k in ("title", "make", "model", "year", "price_usd", "price_local",
                  "currency", "km", "transmission", "fuel", "location",
                  "description", "seller_name"):
            v = getattr(self, k)
            d[k] = v.to_dict() if v is not None else None
        return d
