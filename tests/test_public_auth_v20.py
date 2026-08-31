import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main_v20 import app
from app.public_auth import PublicAuthConfigError, public_supabase_config


class PublicAuthConfigTests(unittest.TestCase):
    def test_publishable_key_can_be_exposed(self):
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://demo.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_demo",
            "SUPABASE_SERVICE_ROLE_KEY": "service-secret",
        }, clear=False):
            config = public_supabase_config()
        self.assertEqual(config["provider"], "supabase")
        self.assertEqual(config["url"], "https://demo.supabase.co")
        self.assertEqual(config["publishable_key"], "sb_publishable_demo")
        self.assertNotIn("service_role", config)

    def test_legacy_anon_key_is_supported(self):
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://demo.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "",
            "SUPABASE_ANON_KEY": "public-anon-jwt",
            "SUPABASE_SERVICE_ROLE_KEY": "service-secret",
        }, clear=False):
            config = public_supabase_config()
        self.assertEqual(config["publishable_key"], "public-anon-jwt")

    def test_service_role_is_never_exposed(self):
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://demo.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "same-secret",
            "SUPABASE_SERVICE_ROLE_KEY": "same-secret",
        }, clear=False):
            with self.assertRaises(PublicAuthConfigError):
                public_supabase_config()

    def test_missing_public_key_fails_closed(self):
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://demo.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "",
            "SUPABASE_ANON_KEY": "",
        }, clear=False):
            with self.assertRaises(PublicAuthConfigError):
                public_supabase_config()

    def test_financing_cors_allows_authorization_for_cartrade_origin(self):
        client = TestClient(app)
        response = client.options(
            "/financing/intake",
            headers={
                "Origin": "https://cartrade.live",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "https://cartrade.live",
        )
        allowed = response.headers.get("access-control-allow-headers", "").lower()
        self.assertIn("authorization", allowed)


if __name__ == "__main__":
    unittest.main()
