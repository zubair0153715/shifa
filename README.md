# SHIFA (شفا) — Clinic & Pharmacy AI

A working cashless clinic + pharmacy app for Islamabad clinics and pharmacies:
online appointment booking with Raast QR payment, digital receipts, automated
WhatsApp-style reminders, a supplier-bill reader that syncs stock into
inventory, and a clinic dashboard.

**Demo / study aid — NOT medical advice. No real payments are processed.**

## Context (verified)

- Dawn reported on 13 November 2026
  ([dawn.com/news/2044285](https://www.dawn.com/news/2044285)) that Islamabad
  will become Pakistan's first fully cashless city by **31 December 2026**.
- After **30 November 2026**, no cash payment will be accepted in any ICT
  administration / CDA department.
- The target is all Islamabad merchants cashless by 31 December 2026.
- The Interior Ministry statement cited in the article says **26,000 merchants
  are already connected** to the digital payments system. That number comes
  from the minister's statement as reported by Dawn — it is **not**
  independently verified here.

## What it does

1. **Clinic appointment booking** — patient picks a DEMO doctor/service, date
   and time slot. The pre-visit fee is shown as a Raast QR (DEMO merchant ID
   `DEMO-RAAST-0000`). The slot **locks only when payment is marked
   confirmed**; until then it stays **tentative** and can be released. That is
   the no-show protection — the state machine is enforced:
   `tentative → confirmed | released`, `confirmed → completed | no-show`,
   and illegal transitions are rejected.
2. **Digital receipt** — generated on payment confirmation, with receipt
   number, patient, service, fee, method and timestamp; printable view at
   `/receipt/{booking_id}`.
3. **Automated WhatsApp-style reminders** — a queue/page renders the reminder
   in Roman Urdu and sends via a built-in **simulator**. Real WhatsApp Cloud
   API sending sits behind `WHATSAPP_TOKEN` and is **OFF by default**; it
   needs the owner's own Meta Cloud API setup.
4. **Pharmacy invoice reader** — paste bill text (or upload `.txt`/`.csv`),
   or a bill photo **only if Tesseract OCR is installed** (checked at runtime
   with `which tesseract`). On this machine Tesseract is **not installed**, so
   photos are not read — the app says so plainly and asks for pasted text.
   Parsed items sync into inventory with stock levels, low-stock flags and a
   stock list.
5. **Clinic dashboard** — today's appointments by status, collections total,
   no-show count, low-stock count.

## How to run locally

```bash
git clone https://github.com/zubair0153715/shifa.git
cd shifa
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh        # or: uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Open **http://127.0.0.1:8001**. All demo data (doctors, services, medicines)
is clearly labelled DEMO; no real patient data is included.

Optional: install Tesseract for photo OCR — `sudo apt install tesseract-ocr`
(Ubuntu/Debian). Without it, paste the bill text instead.

Optional (owner only): real WhatsApp sending needs the clinic owner's Meta
Cloud API setup — set `WHATSAPP_TOKEN` and `WHATSAPP_SEND_ENABLED=1`. It is
off by default and nothing is sent from the demo.

## Tests

```bash
python -m pytest tests/ -q
```

Covers the slot-lock state machine, receipt generation, invoice parsing +
inventory sync, reminders, and API endpoints.

## Honest limits

- **Raast QR is DEMO.** Merchant ID `DEMO-RAAST-0000` is a placeholder. A
  real Raast merchant QR needs the clinic's real bank-issued merchant ID —
  never fake one. A payment is "confirmed" only when marked confirmed in
  this app.
- **WhatsApp sending is simulated.** Real sending needs the owner's Meta
  Cloud API setup and is OFF by default.
- **OCR availability:** Tesseract is not installed on this machine, so bill
  photos cannot be read here; pasted/typed bill text works.
- **Demo data only.** Doctors, services and medicines are DEMO seed data.
  This is a demo/study aid, **not medical advice** and not a certified
  medical or billing system.
- SQLite storage, single-clinic demo scope; no deployment is included.

## Sales pitch (one page)

**Who pays:** small clinics and pharmacies in Islamabad that must go cashless
by 31 December 2026 and are losing money to no-shows, missed reminders and
manual stock counts.

**The problem:** patients book by phone and don't turn up; the clinic only
finds out at the empty slot. Supplier bills pile up on paper and nobody knows
what is actually in stock until a patient asks for it. Cash handling slows
every visit down.

**What SHIFA does:** patients book online and pre-pay the consultation fee by
Raast QR — the slot locks only on confirmed payment, so no-shows drop.
Confirmed patients get automatic Roman-Urdu WhatsApp reminders. Every payment
produces a printable digital receipt. Supplier bills are read and synced into
inventory with low-stock alerts. The dashboard shows today's appointments,
collections and no-shows at a glance.

**Pricing (the owner's asking prices): PKR 8,000–15,000/month per
clinic/pharmacy**, depending on size and features. Setup includes the clinic's
own Raast merchant QR (from their bank) and, if wanted, their own WhatsApp
Cloud API connection.

**Why now:** Islamabad's cashless deadline is 31 December 2026 — clinics that
wait will be scrambling. SHIFA is ready to run today.
