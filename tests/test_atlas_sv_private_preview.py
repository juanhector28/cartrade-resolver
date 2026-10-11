"""Tests for opt-in Atlas SV private read-only adapter. No external requests."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.atlas_sv_private_preview import (
    install, map_vehicle, atlas_sv_preview, ALLOWED_SOURCES, PREVIEW_PATH,
)

PREVIEW_TOKEN="private-preview-requires-separate-token"
UPSTREAM_TOKEN="atlas-backend-token-never-expose-1234567"
BASE_URL="https://cartrade-atlas-production.up.railway.app"

def row(**changes):
    record={
        "source_id":"sv-easycar","listing_key":"easycar:123",
        "record_kind":"vehicle_listing",
        "make":"Toyota","model":"Corolla","year":2022,
        "price_usd":13500,"mileage_km":45000,
        "photo_url":"https://images.example/vehicle123456.jpg",
        "url":"https://easycar.example/autos/123",
        "observed_at":"2026-10-10T12:00:00+00:00",
    }
    record.update(changes)
    return record

class FakeResponse:
    def __init__(self, payload):self._payload=payload
    def raise_for_status(self):return None
    def json(self):return self._payload

class FakeClient:
    def __init__(self,payload):self.payload=payload;self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def get(self,url,params,headers):
        self.calls.append((url,params,headers))
        return FakeResponse(self.payload)

class AtlasPreviewTests(unittest.TestCase):
    def test_disabled_by_default_and_no_carly_route_touch(self):
        with patch.dict(os.environ,{"CARLY_ATLAS_PREVIEW_ENABLED":"0"}):
            app=FastAPI()
            before=[r.path for r in app.routes]
            self.assertFalse(install(app))
            self.assertEqual(before,[r.path for r in app.routes])

    def test_authenticated_preview_filters_catalogs_missing_photos_and_other_sites(self):
        payload={"staging":True,"published":False,"records":[
            row(),
            row(source_id="sv-bac",record_kind="model_catalog"),
            row(photo_url=None,listing_key="x"),
            row(source_id="sv-carvimax",listing_key="y"),
        ]}
        client=FakeClient(payload)
        with patch.dict(os.environ,{
            "CARLY_ATLAS_PREVIEW_ENABLED":"1",
            "CARLY_ATLAS_PREVIEW_TOKEN":PREVIEW_TOKEN,
            "ATLAS_SV_SEARCH_TOKEN":UPSTREAM_TOKEN,
            "CARLY_ATLAS_SV_BASE_URL":BASE_URL,
        }):
            app=FastAPI()
            self.assertTrue(install(app))
            with patch("app.atlas_sv_private_preview.httpx.Client",return_value=client):
                http=TestClient(app)
                self.assertEqual(http.get(PREVIEW_PATH,params={"q":"Toyota"}).status_code,403)
                response=http.get(PREVIEW_PATH,params={"q":"Toyota","limit":3},
                                  headers={"X-Carly-Atlas-Preview-Token":PREVIEW_TOKEN})
            self.assertEqual(response.status_code,200)
            data=response.json()
            self.assertEqual(data["count"],1)
            self.assertEqual(data["records"][0]["source_id"],"sv-easycar")
            self.assertEqual(data["records"][0]["km"],45000)
            self.assertFalse(data["customer_facing"])
            self.assertFalse(data["published"])
            self.assertFalse(data["availability_verified"])
            self.assertTrue(data["records"][0]["requires_availability_confirmation"])
            self.assertNotIn("vin",data["records"][0])
            self.assertNotIn(UPSTREAM_TOKEN,response.text)
            self.assertNotIn(PREVIEW_TOKEN,response.text)
            self.assertEqual(client.calls[0][2]["Authorization"],"Bearer "+UPSTREAM_TOKEN)

    def test_non_verified_upstream_contract_is_rejected(self):
        client=FakeClient({"staging":True,"published":True,"records":[row()]})
        with patch.dict(os.environ,{"ATLAS_SV_SEARCH_TOKEN":UPSTREAM_TOKEN,
                                      "CARLY_ATLAS_SV_BASE_URL":BASE_URL}):
            with patch("app.atlas_sv_private_preview.httpx.Client",return_value=client):
                with self.assertRaises(HTTPException) as ctx:
                    atlas_sv_preview("Toyota")
        self.assertEqual(ctx.exception.status_code,502)

    def test_invalid_source_and_url_rejected(self):
        self.assertIsNone(map_vehicle(row(source_id="sv-bac")))
        self.assertIsNone(map_vehicle(row(url="javascript:alert('x')")))
        self.assertIsNone(map_vehicle(row(photo_url="http://unsafe.example/img.jpg")))
        self.assertIsNone(map_vehicle(row(price_usd=None)))
        self.assertIsNone(map_vehicle(row(record_kind="model_catalog")))
        self.assertIsNone(map_vehicle(row(year="not-a-year")))
        self.assertEqual(len(ALLOWED_SOURCES),6)
        with self.assertRaises(HTTPException) as e:
            atlas_sv_preview("Toyota",source_id="sv-bac")
        self.assertEqual(e.exception.status_code,422)

    def test_missing_environment_cannot_fetch(self):
        with patch.dict(os.environ,{"ATLAS_SV_SEARCH_TOKEN":"",
                                    "CARLY_ATLAS_SV_BASE_URL":BASE_URL}):
            with self.assertRaises(HTTPException) as e:
                atlas_sv_preview("Toyota")
        self.assertEqual(e.exception.status_code,503)

if __name__=="__main__":
    unittest.main()
