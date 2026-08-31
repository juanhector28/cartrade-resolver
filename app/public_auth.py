"""Safe browser-facing Supabase configuration.

Only Supabase publishable/anon credentials are eligible for exposure. The
service-role credential is explicitly rejected even if someone accidentally
copies it into the public-key environment variable.
"""
from __future__ import annotations

import os


class PublicAuthConfigError(RuntimeError):
    pass


def public_supabase_config() -> dict[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip()
    public_key = (
        os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
        or os.getenv("SUPABASE_ANON_KEY", "").strip()
    )
    service_role = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not url or not public_key:
        raise PublicAuthConfigError("public Supabase auth is not configured")
    if service_role and public_key == service_role:
        raise PublicAuthConfigError("refusing to expose Supabase service-role credential")

    return {
        "provider": "supabase",
        "url": url,
        "publishable_key": public_key,
    }
