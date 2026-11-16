"""WhatsApp-style reminder messages (Roman Urdu).

Real WhatsApp Cloud API sending is OFF by default. It requires the clinic
owner's own Meta Cloud API setup (WHATSAPP_TOKEN) plus an explicit opt-in
flag (WHATSAPP_SEND_ENABLED=1). Without both, sends go through the built-in
simulator only — nothing leaves this machine.
"""
import os

WHATSAPP_ENABLED = os.environ.get("WHATSAPP_SEND_ENABLED", "") == "1"
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")


def reminder_message(patient_name: str, doctor_name: str, service_name: str,
                     appt_date: str, slot: str, fee_pkr: int) -> str:
    return (
        f"Assalam-o-Alaikum {patient_name}! SHIFA Clinic ki taraf se yaad-dihani: "
        f"aap ki appointment {doctor_name} ke saath {appt_date} ko {slot} baje hai "
        f"({service_name}, fee Rs {fee_pkr}). "
        f"Barah-e-karam waqt par tashreef layein. "
        f"Appointment cancel ya change karne ke liye clinic se rabta karein. — SHIFA (DEMO)"
    )


def send_whatsapp(to_phone: str, message: str) -> dict:
    """Send via simulator by default. Real API only with owner setup + opt-in.

    Returns a dict describing exactly what happened — never claims a real
    send when only the simulator ran.
    """
    if WHATSAPP_ENABLED and WHATSAPP_TOKEN:
        # Owner's Meta Cloud API step (their token, their WhatsApp Business
        # number). Kept behind the flag so a demo deploy can never send.
        return {
            "sent": False,
            "via": "whatsapp_cloud_api",
            "note": "Real-send hook is configured but disabled in this build: "
                    "no outbound calls are made from the demo. Enable only after "
                    "the owner's Meta Cloud API setup is verified.",
        }
    return {
        "sent": True,
        "via": "simulator",
        "to": to_phone,
        "note": "SIMULATED send — no real WhatsApp message was sent. "
                "Real sending needs the owner's Meta Cloud API setup "
                "(WHATSAPP_TOKEN) and is OFF by default.",
    }
