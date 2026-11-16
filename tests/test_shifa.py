"""SHIFA test suite — slot-lock state machine, receipts, invoice parsing +
inventory sync, reminders, dashboard, API endpoints."""
import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp()
os.environ["SHIFA_DB"] = os.path.join(TMP, "test.db")

from app import db as dbmod  # noqa: E402
from app.parser import parse_bill_text  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
DATE = "2026-11-18"
TOMORROW = "2026-11-19"


@pytest.fixture(scope="module", autouse=True)
def _seed():
    dbmod.init_db()


def _book(slot="10:00", date=DATE, name="Test Patient (DEMO)"):
    r = client.post("/api/bookings", json={
        "patient_name": name, "patient_phone": "03001234567",
        "doctor_id": 1, "service_id": 1, "appt_date": date, "slot": slot})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------- slot state machine
def test_booking_starts_tentative_with_demo_qr():
    b = _book("10:30")
    assert b["status"] == "tentative"
    assert b["fee_pkr"] == 1500
    assert b["raast_demo_merchant_id"] == "DEMO-RAAST-0000"
    assert "DEMO-RAAST-0000" in b["raast_payload"]
    assert "DEMO" in b["raast_payload"]


def test_double_booking_same_slot_rejected():
    _book("11:00")
    r = client.post("/api/bookings", json={
        "patient_name": "Second", "patient_phone": "03009998888",
        "doctor_id": 1, "service_id": 1, "appt_date": DATE, "slot": "11:00"})
    assert r.status_code == 409


def test_confirm_locks_slot_and_release_frees_it():
    b = _book("11:30")
    r = client.post(f"/api/bookings/{b['id']}/confirm-payment", json={})
    assert r.status_code == 200
    assert r.json()["booking"]["status"] == "confirmed"
    assert r.json()["receipt"]["receipt_no"].startswith("R-")
    # confirmed slot still blocked
    r2 = client.post("/api/bookings", json={
        "patient_name": "X", "patient_phone": "03001112222",
        "doctor_id": 1, "service_id": 1, "appt_date": DATE, "slot": "11:30"})
    assert r2.status_code == 409
    # tentative booking can be released, then the slot is free again
    b2 = _book("12:00")
    assert client.post(f"/api/bookings/{b2['id']}/release").json()["booking"]["status"] == "released"
    b3 = _book("12:00")
    assert b3["status"] == "tentative"


def test_invalid_transitions_rejected():
    b = _book("12:30")
    # tentative -> completed is illegal
    assert client.post(f"/api/bookings/{b['id']}/complete").status_code == 400
    # tentative -> no-show is illegal
    assert client.post(f"/api/bookings/{b['id']}/no-show").status_code == 400
    # double confirm is illegal
    client.post(f"/api/bookings/{b['id']}/confirm-payment", json={})
    assert client.post(f"/api/bookings/{b['id']}/confirm-payment", json={}).status_code == 400
    # released booking cannot be confirmed
    b2 = _book("17:00")
    client.post(f"/api/bookings/{b2['id']}/release")
    assert client.post(f"/api/bookings/{b2['id']}/confirm-payment", json={}).status_code == 400


def test_slots_endpoint_reflects_state():
    slots = {s["time"]: s["status"] for s in
             client.get(f"/api/slots?doctor_id=1&date={DATE}").json()}
    assert slots["11:30"] == "confirmed"
    assert slots["12:00"] == "tentative"
    assert slots["10:00"] == "free"


def test_qr_endpoint_returns_png():
    b = _book("17:30")
    r = client.get(f"/api/bookings/{b['id']}/qr.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------------ receipts
def test_receipt_generated_only_on_confirmation():
    b = _book("18:00")
    assert client.get(f"/api/receipts/{b['id']}").status_code == 404
    client.post(f"/api/bookings/{b['id']}/confirm-payment", json={})
    r = client.get(f"/api/receipts/{b['id']}")
    assert r.status_code == 200
    assert r.json()["amount_pkr"] == 1500
    assert r.json()["method"] == "Raast (DEMO)"
    page = client.get(f"/receipt/{b['id']}")
    assert page.status_code == 200
    assert r.json()["receipt_no"] in page.text
    assert "Print receipt" in page.text


# ------------------------------------------------- invoice parsing + inventory
def test_parse_bill_text_formats():
    text = """Paracetamol 500mg x 100 @ 12.50 = 1250
Amoxicillin 500mg, 50, 180
Omeprazole 20mg x 25 @ 220
Item, Qty, Price
Total: 99999
"""
    out = parse_bill_text(text)
    assert len(out["items"]) == 3
    names = [i["name"] for i in out["items"]]
    assert "Paracetamol 500mg" in names
    assert out["items"][0]["line_total_pkr"] == 1250
    assert out["items"][1]["qty"] == 50 and out["items"][1]["unit_price_pkr"] == 180
    assert out["total_pkr"] == 1250 + 9000 + 5500
    assert out["unparsed_lines"] == []


def test_parse_endpoint_and_inventory_sync():
    r = client.post("/api/invoices/parse", data={
        "text": "TestMed 100mg x 40 @ 25 = 1000\nTestMed2 200mg, 10, 50"})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2
    sync = client.post("/api/invoices/sync", json={"items": r.json()["items"]})
    assert sync.status_code == 200
    assert sync.json()["synced_items"] == 2
    inv = {i["name"]: i for i in client.get("/api/inventory").json()}
    assert inv["TestMed 100mg"]["qty"] == 40
    # sync again adds stock (upsert)
    client.post("/api/invoices/sync", json={"items": r.json()["items"]})
    inv = {i["name"]: i for i in client.get("/api/inventory").json()}
    assert inv["TestMed 100mg"]["qty"] == 80


def test_low_stock_flag():
    inv = client.get("/api/inventory?low_stock_only=true").json()
    names = [i["name"] for i in inv]
    assert "Cetirizine 10mg Tablets" in names  # seeded qty 8 < threshold 20
    assert "Paracetamol 500mg Tablets" not in names  # seeded qty 120


def test_ocr_status_endpoint_is_honest():
    r = client.get("/api/ocr-status").json()
    assert "tesseract_installed" in r
    assert isinstance(r["tesseract_installed"], bool)


# ------------------------------------------------------------------ reminders
def test_reminders_roman_urdu_and_simulator_send():
    b = _book("18:30", date=TOMORROW, name="Reminder Patient (DEMO)")
    client.post(f"/api/bookings/{b['id']}/confirm-payment", json={})
    gen = client.post("/api/reminders/generate", json={"date": TOMORROW})
    assert gen.json()["reminders_queued"] >= 1
    rems = client.get("/api/reminders?status=queued").json()
    mine = [x for x in rems if x["booking_id"] == b["id"]]
    assert mine
    msg = mine[0]["message"]
    assert "Assalam-o-Alaikum" in msg and "yaad-dihani" in msg
    sent = client.post(f"/api/reminders/{mine[0]['id']}/send")
    assert sent.status_code == 200
    assert sent.json()["via"] == "simulator"  # real WhatsApp is OFF by default
    assert sent.json()["sent"] is True
    assert client.post(f"/api/reminders/{mine[0]['id']}/send").status_code == 400


# ------------------------------------------------------------------ dashboard
def test_dashboard_counts():
    d = client.get(f"/api/dashboard?date={DATE}").json()
    assert d["counts"]["confirmed"] >= 2
    assert d["counts"]["tentative"] >= 1
    assert d["collections_pkr"] >= 3000
    assert "appointments" in d and len(d["appointments"]) == sum(
        d["counts"][s] for s in ("tentative", "confirmed", "completed", "no-show", "released"))


def test_no_show_flow_counts():
    b = _book("19:00", date=TOMORROW)
    client.post(f"/api/bookings/{b['id']}/confirm-payment", json={})
    assert client.post(f"/api/bookings/{b['id']}/no-show").status_code == 200
    d = client.get(f"/api/dashboard?date={TOMORROW}").json()
    assert d["no_show_count"] >= 1


def test_doctors_endpoint():
    docs = client.get("/api/doctors").json()
    assert len(docs) == 3
    assert all("DEMO" in d["name"] for d in docs)
    assert docs[0]["services"]
