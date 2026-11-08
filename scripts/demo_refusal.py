"""Single-command V09 demo: create ONE new synthetic case and send ONE refusal offer.

Never resends the old expired offers or resets the database. Requires a locally
running FastAPI server plus N8N_DISPATCH_URL and N8N_DISPATCH_TOKEN in the
current PowerShell environment. This script is only for a fictitious hackathon
demo, not production.
"""
import argparse
import json
import os
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.config import DEMO_REFERENCE_DATE
from app.db import SessionLocal
from app.enums import AttemptStatus
from app.models import CoverageAttempt, OutboundMessage, Shift
from app.services.dispatch import send_queued_offer

EMPLOYEE = "demo-operacoes-01"
EXTERNAL_ID = "v09-demo-refusal-final-20261108"
SOURCE = "hackathon_v09_test"


def request(client, method: str, uri: str, *, payload=None):
    response = client.request(method, uri, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {uri} returned HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def run(base: str = "http://127.0.0.1:8001", *, client=None, factory=SessionLocal, sender=send_queued_offer):
    if not os.getenv("N8N_DISPATCH_URL") or not os.getenv("N8N_DISPATCH_TOKEN"):
        raise RuntimeError("Configure N8N_DISPATCH_URL e N8N_DISPATCH_TOKEN neste PowerShell antes de executar.")
    own_client = client is None
    client = client or httpx.Client(base_url=base.rstrip("/"), timeout=20)
    try:
        # Derive the shift from the demo database: no guesses about date or hour.
        with factory() as session:
            shift = session.scalar(select(Shift).where(Shift.reference_date == DEMO_REFERENCE_DATE))
            if shift is None:
                raise RuntimeError("Turno demo nao encontrado no banco local.")
            starts_at, ends_at = shift.starts_at.isoformat(), shift.ends_at.isoformat()

        case_data = request(client, "POST", "/api/v1/absences", payload={
            "employee_id": EMPLOYEE,
            "starts_at": starts_at, "ends_at": ends_at,
            "confirmed": True, "source_system": SOURCE,
            "external_id": EXTERNAL_ID,
        })
        case_id = case_data["case_id"]
        state = request(client, "GET", f"/api/v1/cases/{case_id}")
        if not state.get("tasks"):
            raise RuntimeError("Caso novo sem tarefas afetadas; nenhuma oferta enviada.")
        if not state.get("proposals"):
            request(client, "POST", f"/api/v1/cases/{case_id}/plan")
            state = request(client, "GET", f"/api/v1/cases/{case_id}")

        # Only the first active, unexpired proposal from THIS case.
        candidates = [
            x for x in state.get("proposals", [])
            if x["status"] in {"reserved", "notified"}
            and x.get("response_deadline_at")
            and datetime.fromisoformat(x["response_deadline_at"]) > datetime.now(UTC) + timedelta(seconds=10)
        ]
        if not candidates:
            raise RuntimeError("Nenhuma oferta nova valida para recusar (pode estar expirada ou aguardando BP).")
        candidates.sort(key=lambda x: (x["status"] != "notified", x["task_id"]))
        selected = candidates[0]
        if selected["status"] == "reserved":
            with factory() as session:
                attempt = session.get(CoverageAttempt, selected["attempt_id"])
                if attempt is None or attempt.case_id != case_id or attempt.status != AttemptStatus.RESERVED:
                    raise RuntimeError("Banco local nao corresponde a proposta lida da API.")
                msg_id = session.scalar(select(OutboundMessage.message_id).where(
                    OutboundMessage.attempt_id == attempt.attempt_id
                ).limit(1))
                if not msg_id:
                    raise RuntimeError("Oferta nao foi enfileirada no banco.")
            sent = sender(factory, msg_id)
        else:
            sent = {"status": "already_notified", "duplicate": True}

        out = {
            "case_id": case_id,
            "attempt_id": selected["attempt_id"],
            "task_id": selected["task_id"],
            "response_deadline_at": selected["response_deadline_at"],
            "dispatch": sent,
            "next": "No Slack #novo-canal, RECUSAR apenas a mensagem com este attempt_id.",
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return out
    finally:
        if own_client:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    run(args.base)


if __name__ == "__main__":
    main()
