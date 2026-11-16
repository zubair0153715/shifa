const $ = (s) => document.querySelector(s);
const todayISO = () => new Date().toISOString().slice(0, 10);
const tomorrowISO = () => { const d = new Date(); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10); };
const api = (p, o) => fetch(p, o).then(async (r) => {
  const t = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(t.detail || r.statusText);
  return t;
});
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// tabs
document.querySelectorAll("nav button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("nav button").forEach((x) => x.classList.remove("active"));
  document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  $("#tab-" + b.dataset.tab).classList.add("active");
});

// ---------- dashboard ----------
async function loadDashboard() {
  const d = await api("/api/dashboard");
  $("#dash-cards").innerHTML = `
    <div class="card"><b>${d.counts.confirmed}</b>Confirmed today</div>
    <div class="card"><b>${d.counts.tentative}</b>Tentative</div>
    <div class="card"><b>${d.no_show_count}</b>No-shows</div>
    <div class="card"><b>Rs ${d.collections_pkr.toLocaleString()}</b>Collections today</div>
    <div class="card"><b>${d.low_stock_items}</b>Low-stock items</div>`;
  $("#dash-appts").innerHTML = d.appointments.length ? `<table><tr><th>Slot</th><th>Patient</th><th>Doctor</th><th>Service</th><th>Status</th></tr>${
    d.appointments.map((a) => `<tr><td>${a.slot}</td><td>${esc(a.patient_name)}</td><td>${esc(a.doctor_name)}</td><td>${esc(a.service_name)}</td><td><span class="badge ${a.status}">${a.status}</span></td></tr>`).join("")}</table>` : "<p>No appointments today yet.</p>";
}

// ---------- booking ----------
let doctors = [];
async function loadDoctors() {
  doctors = await api("/api/doctors");
  $("#doctor-select").innerHTML = doctors.map((d) => `<option value="${d.id}">${esc(d.name)} — ${esc(d.speciality)}</option>`).join("");
  refreshServices();
  $("#appt-date").value = todayISO();
  loadSlots();
}
function refreshServices() {
  const doc = doctors.find((d) => d.id == $("#doctor-select").value);
  $("#service-select").innerHTML = (doc?.services || []).map((s) => `<option value="${s.id}">${esc(s.name)} — Rs ${s.fee_pkr}</option>`).join("");
}
async function loadSlots() {
  const docId = $("#doctor-select").value, date = $("#appt-date").value;
  if (!docId || !date) return;
  const slots = await api(`/api/slots?doctor_id=${docId}&date=${date}`);
  $("#slot-select").innerHTML = slots.map((s) => `<option value="${s.time}" ${s.status !== "free" ? "disabled" : ""}>${s.time} ${s.status !== "free" ? "(" + s.status + ")" : ""}</option>`).join("");
}
$("#doctor-select").onchange = () => { refreshServices(); loadSlots(); };
$("#appt-date").onchange = loadSlots;

$("#book-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = Object.fromEntries(fd.entries());
  body.doctor_id = +body.doctor_id; body.service_id = +body.service_id;
  try {
    const b = await api("/api/bookings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    $("#booking-result").innerHTML = `<div class="qr-box">
      <h3>Booking ${esc(b.ref)} — <span class="badge tentative">TENTATIVE</span></h3>
      <p>Fee: <b>Rs ${b.fee_pkr}</b> — ${esc(b.service_id ? "" : "")}Pay via Raast QR below. The slot locks only when payment is marked confirmed.</p>
      <img src="/api/bookings/${b.id}/qr.png" alt="DEMO Raast QR">
      <p><code>${esc(b.raast_payload)}</code></p>
      <p>Demo merchant ID: <b>${esc(b.raast_demo_merchant_id)}</b> (DEMO — a real Raast merchant QR needs the clinic's bank-issued merchant ID.)</p>
      <button onclick="confirmPay(${b.id})">Mark payment confirmed (DEMO)</button>
      <button class="danger" onclick="releaseBooking(${b.id})">Release slot</button>
      <div id="pay-result"></div></div>`;
    loadSlots(); loadDashboard();
  } catch (err) { $("#booking-result").innerHTML = `<p style="color:#a33">Error: ${esc(err.message)}</p>`; }
};
async function confirmPay(id) {
  const r = await api(`/api/bookings/${id}/confirm-payment`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
  $("#pay-result").innerHTML = `<p>✅ Payment confirmed (DEMO). Slot LOCKED. Receipt <b>${r.receipt.receipt_no}</b> —
    <a href="/receipt/${id}" target="_blank">view / print receipt</a></p>`;
  loadSlots(); loadDashboard(); loadAppts();
}
async function releaseBooking(id) {
  await api(`/api/bookings/${id}/release`, { method: "POST" });
  $("#booking-result").innerHTML = "<p>Slot released — it is free again.</p>";
  loadSlots(); loadDashboard(); loadAppts();
}
async function markNoShow(id) { await api(`/api/bookings/${id}/no-show`, { method: "POST" }); loadAppts(); loadDashboard(); }
async function markComplete(id) { await api(`/api/bookings/${id}/complete`, { method: "POST" }); loadAppts(); loadDashboard(); }

// ---------- appointments ----------
async function loadAppts() {
  const date = $("#appts-date").value || todayISO();
  const list = await api(`/api/bookings?date=${date}`);
  $("#appts-list").innerHTML = list.length ? `<table><tr><th>Ref</th><th>Slot</th><th>Patient</th><th>Doctor</th><th>Service</th><th>Fee</th><th>Status</th><th>Actions</th></tr>${
    list.map((a) => `<tr><td>${a.ref}</td><td>${a.slot}</td><td>${esc(a.patient_name)}</td><td>${esc(a.doctor_name)}</td><td>${esc(a.service_name)}</td><td>Rs ${a.fee_pkr}</td><td><span class="badge ${a.status}">${a.status}</span></td><td>${
      a.status === "tentative" ? `<button onclick="confirmPay(${a.id})">Confirm pay</button><button class="danger" onclick="releaseBooking(${a.id})">Release</button>` : ""}${
      a.status === "confirmed" ? `<button onclick="markComplete(${a.id})">Complete</button><button class="danger" onclick="markNoShow(${a.id})">No-show</button> <a href="/receipt/${a.id}" target="_blank">Receipt</a>` : ""}${
      a.status === "completed" ? `<a href="/receipt/${a.id}" target="_blank">Receipt</a>` : ""}</td></tr>`).join("")}</table>` : "<p>No appointments on this date.</p>";
}
$("#appts-refresh").onclick = loadAppts;

// ---------- reminders ----------
async function loadReminders() {
  const list = await api("/api/reminders");
  $("#rem-list").innerHTML = list.length ? list.map((r) => `<div class="msg"><b>#${r.id}</b> — ${esc(r.patient_name)} (${esc(r.patient_phone)}) — ${r.appt_date} ${r.slot} — <span class="badge ${r.status === "sent" ? "confirmed" : "tentative"}">${r.status}</span>${r.sent_via ? " via " + esc(r.sent_via) : ""}<br>${esc(r.message)}<br>${r.status === "queued" ? `<button onclick="sendReminder(${r.id})">Send (simulator)</button>` : ""}</div>`).join("") : "<p>No reminders queued yet.</p>";
}
async function sendReminder(id) {
  const r = await api(`/api/reminders/${id}/send`, { method: "POST" });
  alert(`Reminder #${id}: ${r.via === "simulator" ? "SIMULATED send — no real WhatsApp message was sent." : r.note}`);
  loadReminders();
}
$("#rem-generate").onclick = async () => {
  const date = $("#rem-date").value || tomorrowISO();
  const r = await api("/api/reminders/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date }) });
  alert(`Queued ${r.reminders_queued} reminder(s) for ${r.date}.`);
  loadReminders();
};
$("#rem-refresh").onclick = loadReminders;

// ---------- pharmacy ----------
async function loadOcrStatus() {
  const s = await api("/api/ocr-status");
  $("#ocr-status").textContent = s.tesseract_installed
    ? "OCR: Tesseract is installed — bill photos can be read."
    : "OCR: Tesseract is NOT installed on this machine — paste/type the bill text instead; photos cannot be read.";
}
let lastParsed = null;
$("#invoice-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    const r = await api("/api/invoices/parse", { method: "POST", body: fd });
    lastParsed = r;
    $("#invoice-result").innerHTML = r.items.length ? `<h3>Parsed ${r.items.length} item(s) — total Rs ${r.total_pkr.toLocaleString()}</h3>
      <table><tr><th>Item</th><th>Qty</th><th>Unit price</th><th>Line total</th></tr>${
      r.items.map((i) => `<tr><td>${esc(i.name)}</td><td>${i.qty}</td><td>Rs ${i.unit_price_pkr}</td><td>Rs ${i.line_total_pkr}</td></tr>`).join("")}</table>
      ${r.unparsed_lines.length ? `<p>Could not parse ${r.unparsed_lines.length} line(s): ${esc(r.unparsed_lines.join(" | "))}</p>` : ""}
      <button onclick="syncInvoice()">Sync ${r.items.length} item(s) to inventory</button>` : `<p>No items parsed. ${r.unparsed_lines.length ? "Unparsed: " + esc(r.unparsed_lines.join(" | ")) : ""}</p>`;
  } catch (err) { $("#invoice-result").innerHTML = `<p style="color:#a33">Error: ${esc(err.message)}</p>`; }
};
async function syncInvoice() {
  const r = await api("/api/invoices/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items: lastParsed.items, ocr_used: lastParsed.ocr_used }) });
  $("#invoice-result").innerHTML += `<p>✅ Synced ${r.synced_items} item(s) to inventory (total Rs ${r.total_pkr.toLocaleString()}).</p>`;
  loadInventory();
}
async function loadInventory() {
  const low = $("#low-only").checked;
  const list = await api(`/api/inventory${low ? "?low_stock_only=true" : ""}`);
  $("#inv-list").innerHTML = list.length ? `<table><tr><th>Medicine</th><th>Stock</th><th>Unit price</th><th>Status</th><th>Adjust</th></tr>${
    list.map((i) => `<tr><td>${esc(i.name)}</td><td>${i.qty} ${esc(i.unit)}</td><td>Rs ${i.unit_price_pkr}</td><td>${i.low_stock ? '<span class="badge low">LOW STOCK</span>' : "OK"}</td><td><button onclick="adjustInv(${i.id},1)">+1</button><button onclick="adjustInv(${i.id},-1)">−1</button></td></tr>`).join("")}</table>` : "<p>No items.</p>";
}
async function adjustInv(id, delta) { await api(`/api/inventory/${id}/adjust`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ delta }) }); loadInventory(); }
$("#inv-refresh").onclick = loadInventory;
$("#low-only").onchange = loadInventory;

// ---------- init ----------
$("#appts-date").value = todayISO();
$("#rem-date").value = tomorrowISO();
loadDashboard(); loadDoctors(); loadAppts(); loadReminders(); loadOcrStatus(); loadInventory();
