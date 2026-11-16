"""SHIFA (شفا) — Clinic & Pharmacy AI (demo/study aid).

SQLite storage via the stdlib sqlite3 module. No paid services, nothing
outbound. Every demo value is labelled DEMO.
"""
import os
import sqlite3
from datetime import date

DB_PATH = os.environ.get("SHIFA_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shifa.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    speciality TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    name TEXT NOT NULL,
    fee_pkr INTEGER NOT NULL,
    duration_min INTEGER NOT NULL DEFAULT 30
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref TEXT UNIQUE NOT NULL,
    patient_name TEXT NOT NULL,
    patient_phone TEXT NOT NULL,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    appt_date TEXT NOT NULL,
    slot TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'tentative',
    fee_pkr INTEGER NOT NULL,
    payment_method TEXT,
    payment_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_no TEXT UNIQUE NOT NULL,
    booking_id INTEGER NOT NULL REFERENCES bookings(id),
    patient_name TEXT NOT NULL,
    service_name TEXT NOT NULL,
    amount_pkr INTEGER NOT NULL,
    method TEXT NOT NULL,
    issued_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL REFERENCES bookings(id),
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    message TEXT NOT NULL,
    send_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    sent_via TEXT
);
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    unit TEXT NOT NULL DEFAULT 'pack',
    qty INTEGER NOT NULL DEFAULT 0,
    unit_price_pkr REAL NOT NULL DEFAULT 0,
    low_stock_threshold INTEGER NOT NULL DEFAULT 20,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier TEXT,
    raw_text TEXT,
    total_pkr REAL NOT NULL DEFAULT 0,
    parsed_items INTEGER NOT NULL DEFAULT 0,
    ocr_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

# DEMO seed data only — no real people, no real patient data.
DEMO_DOCTORS = [
    ("Dr. Ayesha Khan (DEMO)", "General Physician"),
    ("Dr. Bilal Ahmed (DEMO)", "Dentist"),
    ("Dr. Sara Malik (DEMO)", "Dermatologist"),
]

DEMO_SERVICES = {
    # doctor index (1-based) -> [(service, fee_pkr)]
    1: [("General Consultation", 1500), ("Follow-up Visit", 800), ("Diabetes Review", 2000)],
    2: [("Dental Check-up", 2000), ("Tooth Filling", 4500), ("Scaling & Polish", 3500)],
    3: [("Skin Consultation", 2500), ("Acne Treatment Session", 4000)],
}

DEMO_MEDICINES = [
    ("Paracetamol 500mg Tablets", "strip", 120, 45.0, 20),
    ("Amoxicillin 500mg Capsules", "strip", 60, 180.0, 20),
    ("Omeprazole 20mg Capsules", "strip", 15, 220.0, 20),
    ("Metformin 500mg Tablets", "strip", 90, 60.0, 20),
    ("Cetirizine 10mg Tablets", "strip", 8, 35.0, 20),
]


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    conn = get_conn(db_path)
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] == 0:
        for name, spec in DEMO_DOCTORS:
            conn.execute("INSERT INTO doctors (name, speciality) VALUES (?, ?)", (name, spec))
        for doc_idx, services in DEMO_SERVICES.items():
            for name, fee in services:
                conn.execute(
                    "INSERT INTO services (doctor_id, name, fee_pkr) VALUES (?, ?, ?)",
                    (doc_idx, name, fee),
                )
        for name, unit, qty, price, thresh in DEMO_MEDICINES:
            conn.execute(
                "INSERT INTO inventory (name, unit, qty, unit_price_pkr, low_stock_threshold, updated_at)"
                " VALUES (?, ?, ?, ?, ?, date('now'))",
                (name, unit, qty, price, thresh),
            )
        conn.commit()
    return conn


def today_str() -> str:
    return date.today().isoformat()
