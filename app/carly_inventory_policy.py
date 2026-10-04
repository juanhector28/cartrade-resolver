"""Expose historical inventory policy without changing observation timestamps."""
from datetime import datetime, timedelta, timezone
from functools import wraps
import inspect

POLICY = {"mode": "historical", "max_age_seconds": None,
          "source_allowlist": None, "status": "staging", "listing_state": "indexed",
          "requires_price_and_photo": True}


def annotate(data, *, now=None):
    if not isinstance(data, dict):
        return data
    data["inventory_policy"] = dict(POLICY)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=24)
    historical = False
    for key in ("recommendations", "explore", "results", "cars"):
        for car in data.get(key) or []:
            if not isinstance(car, dict):
                continue
            observed = car.get("last_seen_at")
            try:
                seen = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=timezone.utc)
                needs_reconfirmation = seen < cutoff
            except (ValueError, TypeError):
                needs_reconfirmation = True
            car["requires_availability_confirmation"] = needs_reconfirmation
            historical |= needs_reconfirmation
    if historical and data.get("recommendations") and data.get("reply"):
        data["reply"] += " Estas opciones incluyen anuncios históricos; confirma disponibilidad y precio antes de avanzar."
    return data


def install(app):
    for route in app.routes:
        if getattr(route, "path", None) not in {"/carly/chat", "/carly/search", "/carly/runtime"}:
            continue
        prior = route.endpoint
        if inspect.iscoroutinefunction(prior):
            @wraps(prior)
            async def endpoint(*args, __prior=prior, **kwargs):
                return annotate(await __prior(*args, **kwargs))
        else:
            @wraps(prior)
            def endpoint(*args, __prior=prior, **kwargs):
                return annotate(__prior(*args, **kwargs))
        route.endpoint = endpoint
        route.dependant.call = endpoint
