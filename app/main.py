"""SHIFA (شفا) — Clinic & Pharmacy AI for Islamabad (demo).

FastAPI + SQLite + plain HTML/JS. Demo/study aid — NOT medical advice.
No real payments: a booking is "confirmed" only when marked confirmed in
this app. Raast QR is DEMO (merchant ID DEMO-RAAST-0000); a real Raast
merchant QR needs the clinic's real bank-issued merchant ID.
"""
import io
import os
import re
import sqlite3
from datetime import date, datetime, timedelta

import qrcode
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import db as dbmod
from app.parser import ocr_available, ocr_image_bytes, parse_bill_text
from app.reminders import reminder_message, send_whatsapp

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_MERCHANT_ID = "DEMO-RAAST-0000"

# Slot state machine — the no-show protection. Honest transitions only.
TRANSITIONS = {
    "tentative": {"confirmed", "released"},
    "confirmed": {"completed", "no-show"},
    "released": set(),
    "completed": set(),
    "no-show": set(),
}
SLOT_TIMES = ["10:00", "10:30", "11:00", "11:30", "12:00", "12:30",
              "17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00"]

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    dbmod.init_db()
    yield


app = FastAPI(title="SHIFA — Clinic & Pharmacy AI (Demo)", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


def conn() -> sqlite3.Connection:
    return dbmod.get_conn()


def row_to_dict(r: sqlite3.Row) -> dict:
    return dict(r)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ref(booking_id: int) -> str:
    return f"SHF-{date.today().strftime('%Y%m%d')}-{booking_id:04d}"


def _receipt_no(booking_id: int) -> str:
    return f"R-{date.today().strftime('%Y%m%d')}-{booking_id:04d}"


def raast_payload(booking: dict) -> str:
    """DEMO Raast payment payload — labelled DEMO, never a real merchant ID."""
    return (
        f"RAAST-DEMO|MERCHANT:{DEMO_MERCHANT_ID}|CLINIC:SHIFA-DEMO-CLINIC|"
        f"REF:{booking['ref']}|AMOUNT:{booking['fee_pkr']}|CURRENCY:PKR|"
        f"NOTE:DEMO ONLY — no real payment. Real Raast QR needs the clinic's "
        f"bank-issued merchant ID."
    )


@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(BASE_DIR, "static", "index.html")) as f:
        return f.read()


# ---------------------------------------------------------------- doctors
@app.get("/api/doctors")
def list_doctors():
    c = conn()
    doctors = [row_to_dict(r) for r in c.execute("SELECT * FROM doctors")]
    for d in doctors:
        d["services"] = [row_to_dict(r) for r in c.execute(
            "SELECT * FROM services WHERE doctor_id = ?", (d["id"],))]
    c.close()
    return doctors


# ------------------------------------------------------------------ slots
@app.get("/api/slots")
def list_slots(doctor_id: int, date: str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    c = conn()
    booked = {r["slot"]: r["status"] for r in c.execute(
        "SELECT slot, status FROM bookings WHERE doctor_id = ? AND appt_date = ?"
        " AND status IN ('tentative', 'confirmed')", (doctor_id, date))}
    c.close()
    return [{"time": t, "status": booked.get(t, "free")} for t in SLOT_TIMES]


# --------------------------------------------------------------- bookings
@app.post("/api/bookings")
async def create_booking(req: Request):
    body = await req.json()
    for field in ("patient_name", "patient_phone", "doctor_id", "service_id", "appt_date", "slot"):
        if not body.get(field):
            raise HTTPException(400, f"missing field: {field}")
    if body["slot"] not in SLOT_TIMES:
        raise HTTPException(400, "invalid slot")
    c = conn()
    svc = c.execute("SELECT * FROM services WHERE id = ? AND doctor_id = ?",
                    (body["service_id"], body["doctor_id"])).fetchone()
    if not svc:
        c.close()
        raise HTTPException(400, "service does not belong to this doctor")
    clash = c.execute(
        "SELECT id FROM bookings WHERE doctor_id = ? AND appt_date = ? AND slot = ?"
        " AND status IN ('tentative', 'confirmed')",
        (body["doctor_id"], body["appt_date"], body["slot"])).fetchone()
    if clash:
        c.close()
        raise HTTPException(409, "slot already booked (tentative or confirmed)")
    cur = c.execute(
        "INSERT INTO bookings (ref, patient_name, patient_phone, doctor_id, service_id,"
        " appt_date, slot, status, fee_pkr, created_at, updated_at)"
        " VALUES ('', ?, ?, ?, ?, ?, ?, 'tentative', ?, ?, ?)",
        (body["patient_name"].strip(), body["patient_phone"].strip(),
         body["doctor_id"], body["service_id"], body["appt_date"], body["slot"],
         svc["fee_pkr"], _now(), _now()))
    bid = cur.lastrowid
    ref = _ref(bid)
    c.execute("UPDATE bookings SET ref = ? WHERE id = ?", (ref, bid))
    c.commit()
    booking = row_to_dict(c.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone())
    c.close()
    booking["raast_payload"] = raast_payload(booking)
    booking["raast_demo_merchant_id"] = DEMO_MERCHANT_ID
    booking["payment_note"] = ("DEMO Raast QR — scan shows a DEMO payload only. "
                               "The slot stays TENTATIVE until payment is marked confirmed.")
    return JSONResponse(booking, status_code=201)


@app.get("/api/bookings")
def list_bookings(date: str | None = None, status: str | None = None):
    c = conn()
    q = ("SELECT b.*, d.name AS doctor_name, s.name AS service_name FROM bookings b "
         "JOIN doctors d ON d.id = b.doctor_id JOIN services s ON s.id = b.service_id")
    clauses, params = [], []
    if date:
        clauses.append("b.appt_date = ?")
        params.append(date)
    if status:
        clauses.append("b.status = ?")
        params.append(status)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY b.appt_date, b.slot"
    rows = [row_to_dict(r) for r in c.execute(q, params)]
    c.close()
    return rows


@app.get("/api/bookings/{booking_id}")
def get_booking(booking_id: int):
    c = conn()
    b = c.execute(
        "SELECT b.*, d.name AS doctor_name, s.name AS service_name FROM bookings b "
        "JOIN doctors d ON d.id = b.doctor_id JOIN services s ON s.id = b.service_id "
        "WHERE b.id = ?", (booking_id,)).fetchone()
    c.close()
    if not b:
        raise HTTPException(404, "booking not found")
    booking = row_to_dict(b)
    booking["raast_payload"] = raast_payload(booking)
    return booking


def _transition(booking_id: int, target: str, **extra):
    c = conn()
    b = c.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not b:
        c.close()
        raise HTTPException(404, "booking not found")
    if target not in TRANSITIONS.get(b["status"], set()):
        c.close()
        raise HTTPException(400, f"cannot move booking from '{b['status']}' to '{target}'")
    sets = ", ".join(f"{k} = ?" for k in extra) + ", " if extra else ""
    c.execute(f"UPDATE bookings SET {sets}status = ?, updated_at = ? WHERE id = ?",
              (*extra.values(), target, _now(), booking_id))
    c.commit()
    booking = row_to_dict(c.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone())
    c.close()
    return booking


@app.post("/api/bookings/{booking_id}/confirm-payment")
async def confirm_payment(booking_id: int, req: Request):
    body = await req.json() if await req.body() else {}
    booking = _transition(booking_id, "confirmed",
                          payment_method=body.get("payment_method", "Raast (DEMO)"),
                          payment_ref=body.get("payment_ref") or f"DEMO-PAY-{booking_id}")
    c = conn()
    svc = c.execute("SELECT name FROM services WHERE id = ?", (booking["service_id"],)).fetchone()
    receipt_no = _receipt_no(booking_id)
    c.execute(
        "INSERT INTO receipts (receipt_no, booking_id, patient_name, service_name,"
        " amount_pkr, method, issued_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (receipt_no, booking_id, booking["patient_name"], svc["name"],
         booking["fee_pkr"], booking["payment_method"], _now()))
    c.commit()
    receipt = row_to_dict(c.execute("SELECT * FROM receipts WHERE receipt_no = ?", (receipt_no,)).fetchone())
    c.close()
    return {"booking": booking, "receipt": receipt}


@app.post("/api/bookings/{booking_id}/release")
def release_booking(booking_id: int):
    return {"booking": _transition(booking_id, "released")}


@app.post("/api/bookings/{booking_id}/complete")
def complete_booking(booking_id: int):
    return {"booking": _transition(booking_id, "completed")}


@app.post("/api/bookings/{booking_id}/no-show")
def no_show_booking(booking_id: int):
    return {"booking": _transition(booking_id, "no-show")}


@app.get("/api/bookings/{booking_id}/qr.png")
def booking_qr(booking_id: int):
    booking = get_booking(booking_id)
    img = qrcode.make(raast_payload(booking))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


# --------------------------------------------------------------- receipts
@app.get("/api/receipts/{booking_id}")
def get_receipt(booking_id: int):
    c = conn()
    r = c.execute("SELECT * FROM receipts WHERE booking_id = ?", (booking_id,)).fetchone()
    c.close()
    if not r:
        raise HTTPException(404, "no receipt yet — payment not confirmed")
    return row_to_dict(r)


@app.get("/receipt/{booking_id}", response_class=HTMLResponse)
def receipt_page(booking_id: int):
    c = conn()
    r = c.execute("SELECT * FROM receipts WHERE booking_id = ?", (booking_id,)).fetchone()
    b = c.execute(
        "SELECT b.*, d.name AS doctor_name FROM bookings b JOIN doctors d ON d.id = b.doctor_id"
        " WHERE b.id = ?", (booking_id,)).fetchone()
    c.close()
    if not r or not b:
        raise HTTPException(404, "Receipt not found — payment not confirmed yet.")
    r, b = row_to_dict(r), row_to_dict(b)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Receipt {r['receipt_no']} — SHIFA</title>
<style>body{{font-family:system-ui,sans-serif;max-width:560px;margin:40px auto;padding:0 16px}}
h1{{color:#0b6e4f}} table{{width:100%;border-collapse:collapse}} td{{padding:8px;border-bottom:1px solid #ddd}}
td:first-child{{color:#555}} .demo{{background:#fff3cd;padding:10px;border-radius:8px}}
@media print{{.noprint{{display:none}}}}</style></head><body>
<h1>SHIFA شفا — Digital Receipt (DEMO)</h1>
<p class="demo">DEMO receipt — no real payment was processed.</p>
<table>
<tr><td>Receipt No</td><td><b>{r['receipt_no']}</b></td></tr>
<tr><td>Patient</td><td>{r['patient_name']}</td></tr>
<tr><td>Doctor</td><td>{b['doctor_name']}</td></tr>
<tr><td>Service</td><td>{r['service_name']}</td></tr>
<tr><td>Date / Slot</td><td>{b['appt_date']} — {b['slot']}</td></tr>
<tr><td>Fee</td><td><b>Rs {r['amount_pkr']:,}</b></td></tr>
<tr><td>Method</td><td>{r['method']}</td></tr>
<tr><td>Issued</td><td>{r['issued_at']}</td></tr>
<tr><td>Booking ref</td><td>{b['ref']}</td></tr>
</table>
<p class="noprint"><button onclick="window.print()">Print receipt</button></p>
</body></html>"""


# -------------------------------------------------------------- reminders
@app.post("/api/reminders/generate")
async def generate_reminders(req: Request):
    body = await req.json() if await req.body() else {}
    target_date = body.get("date") or (date.today() + timedelta(days=1)).isoformat()
    c = conn()
    rows = c.execute(
        "SELECT b.*, d.name AS doctor_name, s.name AS service_name FROM bookings b "
        "JOIN doctors d ON d.id = b.doctor_id JOIN services s ON s.id = b.service_id "
        "WHERE b.appt_date = ? AND b.status = 'confirmed'", (target_date,)).fetchall()
    made = 0
    for r in rows:
        exists = c.execute("SELECT id FROM reminders WHERE booking_id = ? AND status = 'queued'",
                           (r["id"],)).fetchone()
        if exists:
            continue
        msg = reminder_message(r["patient_name"], r["doctor_name"], r["service_name"],
                               r["appt_date"], r["slot"], r["fee_pkr"])
        c.execute("INSERT INTO reminders (booking_id, message, send_at, status)"
                  " VALUES (?, ?, ?, 'queued')", (r["id"], msg, _now()))
        made += 1
    c.commit()
    c.close()
    return {"date": target_date, "reminders_queued": made}


@app.get("/api/reminders")
def list_reminders(status: str | None = None):
    c = conn()
    q = ("SELECT r.*, b.patient_name, b.patient_phone, b.appt_date, b.slot FROM reminders r "
         "JOIN bookings b ON b.id = r.booking_id")
    params = []
    if status:
        q += " WHERE r.status = ?"
        params.append(status)
    q += " ORDER BY r.id DESC"
    rows = [row_to_dict(r) for r in c.execute(q, params)]
    c.close()
    return rows


@app.post("/api/reminders/{reminder_id}/send")
def send_reminder(reminder_id: int):
    c = conn()
    r = c.execute(
        "SELECT r.*, b.patient_phone FROM reminders r JOIN bookings b ON b.id = r.booking_id "
        "WHERE r.id = ?", (reminder_id,)).fetchone()
    if not r:
        c.close()
        raise HTTPException(404, "reminder not found")
    if r["status"] == "sent":
        c.close()
        raise HTTPException(400, "reminder already sent")
    result = send_whatsapp(r["patient_phone"], r["message"])
    c.execute("UPDATE reminders SET status = 'sent', sent_via = ? WHERE id = ?",
              (result["via"], reminder_id))
    c.commit()
    c.close()
    return {"reminder_id": reminder_id, **result}


# ------------------------------------------------------- pharmacy invoices
@app.get("/api/ocr-status")
def ocr_status():
    return {"tesseract_installed": ocr_available(),
            "note": ("Tesseract OCR is available." if ocr_available()
                     else "Tesseract OCR is NOT installed on this machine — "
                          "paste/type the bill text instead; photos cannot be read.")}


@app.post("/api/invoices/parse")
async def parse_invoice(text: str | None = Form(None), file: UploadFile | None = File(None)):
    supplier = None
    ocr_used = False
    if file is not None and file.filename:
        data = await file.read()
        ctype = (file.content_type or "").lower()
        if ctype.startswith("text") or file.filename.lower().endswith((".txt", ".csv")):
            raw_text = data.decode("utf-8", errors="replace")
        elif ctype.startswith("image/") or file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
            ocr = ocr_image_bytes(data)
            if not ocr["ok"]:
                raise HTTPException(422, ocr["error"])
            raw_text, ocr_used = ocr["text"], True
        else:
            raise HTTPException(400, "unsupported file type — upload a .txt/.csv bill or a photo (photo needs Tesseract)")
    elif text:
        raw_text = text
    else:
        raise HTTPException(400, "provide bill text or upload a file")
    parsed = parse_bill_text(raw_text)
    return {**parsed, "ocr_used": ocr_used,
            "supplier": supplier,
            "note": "Review parsed items before syncing to inventory."}


@app.post("/api/invoices/sync")
async def sync_invoice(req: Request):
    body = await req.json()
    items = body.get("items") or []
    if not items:
        raise HTTPException(400, "no items to sync")
    c = conn()
    synced = 0
    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        qty = int(it.get("qty") or 0)
        price = float(it.get("unit_price_pkr") or 0)
        existing = c.execute("SELECT id, qty FROM inventory WHERE name = ?", (name,)).fetchone()
        if existing:
            c.execute("UPDATE inventory SET qty = qty + ?, unit_price_pkr = ?, updated_at = date('now')"
                      " WHERE id = ?", (qty, price, existing["id"]))
        else:
            c.execute("INSERT INTO inventory (name, qty, unit_price_pkr, updated_at)"
                      " VALUES (?, ?, ?, date('now'))", (name, qty, price))
        synced += 1
    total = round(sum(float(i.get("line_total_pkr") or (int(i.get("qty") or 0) * float(i.get("unit_price_pkr") or 0)))
                      for i in items), 2)
    c.execute("INSERT INTO invoices (raw_text, total_pkr, parsed_items, ocr_used, created_at)"
              " VALUES (?, ?, ?, ?, ?)",
              (body.get("raw_text", ""), total, synced, 1 if body.get("ocr_used") else 0, _now()))
    c.commit()
    c.close()
    return {"synced_items": synced, "total_pkr": total}


@app.get("/api/inventory")
def list_inventory(low_stock_only: bool = False):
    c = conn()
    q = "SELECT *, (qty <= low_stock_threshold) AS low_stock FROM inventory ORDER BY name"
    rows = [row_to_dict(r) for r in c.execute(q)]
    c.close()
    if low_stock_only:
        rows = [r for r in rows if r["low_stock"]]
    return rows


@app.post("/api/inventory/{item_id}/adjust")
async def adjust_inventory(item_id: int, req: Request):
    body = await req.json()
    delta = int(body.get("delta") or 0)
    c = conn()
    item = c.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
    if not item:
        c.close()
        raise HTTPException(404, "item not found")
    new_qty = max(0, item["qty"] + delta)
    c.execute("UPDATE inventory SET qty = ?, updated_at = date('now') WHERE id = ?",
              (new_qty, item_id))
    c.commit()
    updated = row_to_dict(c.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone())
    c.close()
    return updated


# -------------------------------------------------------------- dashboard
@app.get("/api/dashboard")
def dashboard(date: str | None = None):
    d = date or dbmod.today_str()
    c = conn()
    counts = {}
    for st in ("tentative", "confirmed", "completed", "no-show", "released"):
        counts[st] = c.execute(
            "SELECT COUNT(*) FROM bookings WHERE appt_date = ? AND status = ?", (d, st)).fetchone()[0]
    collections = c.execute(
        "SELECT COALESCE(SUM(fee_pkr), 0) FROM bookings WHERE appt_date = ? AND status IN ('confirmed', 'completed')",
        (d,)).fetchone()[0]
    low_stock = c.execute(
        "SELECT COUNT(*) FROM inventory WHERE qty <= low_stock_threshold").fetchone()[0]
    appts = [row_to_dict(r) for r in c.execute(
        "SELECT b.*, d.name AS doctor_name, s.name AS service_name FROM bookings b "
        "JOIN doctors d ON d.id = b.doctor_id JOIN services s ON s.id = b.service_id "
        "WHERE b.appt_date = ? ORDER BY b.slot", (d,))]
    c.close()
    return {"date": d, "counts": counts, "collections_pkr": collections,
            "no_show_count": counts["no-show"], "low_stock_items": low_stock,
            "appointments": appts}
