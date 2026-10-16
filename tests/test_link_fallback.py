from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import link_fallback

def client(monkeypatch, db=None):
    class FakeQuery:
        def __init__(self): self.rows=[]
        def insert(self, row):
            self.rows.append(row)
            return self
        def execute(self): return {"data":self.rows}
    class FakeDB:
        def __init__(self): self.q=FakeQuery()
        def table(self, name):
            assert name=="buyer_intents"
            return self.q
    import app.main as main
    fake=db or FakeDB()
    monkeypatch.setattr(main, "supabase", fake)
    link_fallback._rate_window.clear()
    app=FastAPI()
    app.include_router(link_fallback.router)
    return TestClient(app), fake

def test_guatemala_encuentra24_fallback_records_contact_and_link(monkeypatch):
    cli, db=client(monkeypatch)
    url="https://www.encuentra24.com/guatemala-es/autos-usados/porsche-911-carrera-45-cabriolet-2014-color-blanco/33032350"
    response=cli.post("/link-interest",json={"listing_url":url,"buyer_contact":"+502 5555 5555","contact_channel":"whatsapp","consent_to_contact":True})
    assert response.status_code==201
    row=db.q.rows[0]
    assert row["listing_url"]==url and row["country"]=="gt" and row["source"]=="encuentra24"
    assert row["price_usd"] is None and row["consent_to_contact"] is True
    assert "buyer_contact" not in response.json()

def test_consent_required_and_invalid_contact_rejected(monkeypatch):
    cli, db=client(monkeypatch)
    data={"listing_url":"https://www.encuentra24.com/el-salvador-es/autos-usados/toyota/12345678","buyer_contact":"buyer@example.com","contact_channel":"email","consent_to_contact":False}
    assert cli.post("/link-interest",json=data).status_code==422
    data["consent_to_contact"]=True
    data["buyer_contact"]="bad-number"
    assert cli.post("/link-interest",json=data).status_code==422
    assert not db.q.rows

def test_write_failure_not_reported_as_success(monkeypatch):
    cli,_=client(monkeypatch)
    import app.main as main
    class Broken:
        def table(self,n): raise RuntimeError("backend down")
    monkeypatch.setattr(main,"supabase",Broken())
    response=cli.post("/link-interest",json={"listing_url":"https://example.com/vehicle","buyer_contact":"buyer@example.com","contact_channel":"email","consent_to_contact":True})
    assert response.status_code==503
    assert response.json()["detail"].startswith("No se pudo")
