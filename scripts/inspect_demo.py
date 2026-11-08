"""Read-only preflight for Realoca AI demo. GET only; no secrets or mutations.

Usage: python scripts/inspect_demo.py --base http://127.0.0.1:8001
"""
import argparse
from datetime import datetime, timezone
import json
from urllib.parse import quote, urlparse
from urllib.request import urlopen


def validate_base(url):
    parsed = urlparse(url)
    if not (parsed.scheme == "https" or
            (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"))):
        raise ValueError("Use HTTPS or local HTTP")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL cannot include credentials, query or fragment")
    return url.rstrip("/")


def get_json(url):
    with urlopen(url, timeout=7) as response:
        if response.status != 200:
            raise RuntimeError("HTTP " + str(response.status))
        return json.load(response)


def inspect(base, *, getter=get_json, now=None, max_cases=10):
    base = validate_base(base)
    now = now or datetime.now(timezone.utc)
    cases = getter(base + "/api/v1/cases").get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("Unexpected /api/v1/cases response")
    result = {"total_cases": len(cases), "shown_cases": [], "ready_offers": 0}
    for item in cases[:max_cases]:
        case_id = item["case_id"]
        detail = getter(base + "/api/v1/cases/" + quote(case_id, safe=""))
        offers = []
        for offer in detail.get("proposals", []):
            deadline = offer.get("response_deadline_at")
            try:
                parsed = datetime.fromisoformat(deadline.replace("Z", "+00:00")) if deadline else None
                valid = bool(parsed and parsed.tzinfo and parsed > now)
            except ValueError:
                valid = False
            ready = offer.get("status") == "notified" and valid
            result["ready_offers"] += int(ready)
            offers.append({
                "attempt_id": offer.get("attempt_id"),
                "status": offer.get("status"),
                "approval_decision": offer.get("approval_decision"),
                "response_deadline_at": deadline,
                "ready_for_slack_response": ready,
            })
        result["shown_cases"].append({
            "case_id": case_id,
            "status": detail.get("status"),
            "pending_approvals": len(detail.get("pending_approvals", [])),
            "offers": offers,
        })
    result["truncated"] = len(cases) > max_cases
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--max-cases", type=int, default=10)
    args = parser.parse_args()
    try:
        report = inspect(args.base, max_cases=max(1, min(args.max_cases, 100)))
    except Exception as exc:
        parser.exit(1, "Nao foi possivel consultar a API: " + str(exc) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
