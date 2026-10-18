"""Staging smoke tests. The Carly upstream is replaced with a fake transport."""
import pytest
from fastapi.testclient import TestClient
from app.deals_api import _client
from staging.api import app

client=TestClient(app)

def test_health_and_public_ui():
    assert client.get("/health").status_code==200
    page=client.get("/")
    assert page.status_code==200
    assert "CarTrade" in page.text
    assert "Confirmar creación del Deal" in page.text

def test_staging_chat_needs_session():
    response=client.post("/api/broker/chat",json={
        "country":"sv","actor_role":"broker",
        "messages":[{"role":"user","content":"busco un carro"}]})
    assert response.status_code==401

def test_invalid_role_cannot_use_chat():
    app.dependency_overrides[_client]=lambda:(None,"test")
    try:
        assert client.post("/api/broker/chat",json={
            "country":"sv","actor_role":"admin",
            "messages":[{"role":"user","content":"hola"}]}).status_code==422
    finally:
        app.dependency_overrides.clear()

def test_chat_uses_real_upstream_contract_and_never_forwards_token(monkeypatch):
    import staging.api as staging
    seen={}
    class FakeResp:
        status_code=200
        def json(self): return {"reply":"Respuesta de Carly","phase":"conversation"}
    class FakeHTTP:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,json,headers):
            seen.update({"url":url,"payload":json,"headers":headers})
            return FakeResp()
    monkeypatch.setattr(staging.httpx,"AsyncClient",FakeHTTP)
    app.dependency_overrides[_client]=lambda:(None,"test")
    try:
        response=client.post("/api/broker/chat",json={
            "country":"gt","actor_role":"broker",
            "messages":[{"role":"user","content":"Abrí un Deal para mi cliente"}]})
        assert response.status_code==200
        assert response.json()["suggest_create_deal"] is True
        assert response.json()["reply"]=="Respuesta de Carly"
        assert seen["payload"]["country"]=="gt"
        assert seen["url"]=="https://resolver.cartrade.live/carly/chat"
        assert "Authorization" not in seen["headers"]
        assert seen["payload"]["messages"][0]["role"]=="user"
    finally:
        app.dependency_overrides.clear()
