"""Fast V09 demo helper contract tests: safe reuse and one targeted delivery."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts.demo_refusal import run


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeHttp:
    def __init__(self, *, status):
        self.calls = []
        self.status = status

    def request(self, method, url, json=None):
        self.calls.append((method, url, json))
        if url == "/api/v1/absences":
            return FakeResponse({"case_id": "case-v09"})
        if url == "/api/v1/cases/case-v09":
            return FakeResponse({"tasks": [{"task_id": "task-v09"}], "proposals": [{
                "attempt_id": "att-v09", "task_id": "task-v09",
                "status": self.status,
                "response_deadline_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            }]})
        raise AssertionError(f"Unexpected request {method} {url}")


class FakeSession:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def scalar(self, statement):
        # Shift initially, then outbound message
        if "shifts" in str(statement).lower():
            return SimpleNamespace(
                starts_at=datetime(2026, 11, 8, 11, tzinfo=UTC),
                ends_at=datetime(2026, 11, 8, 19, tzinfo=UTC),
            )
        return "msg-v09"

    def get(self, model, attempt_id):
        from app.enums import AttemptStatus
        return SimpleNamespace(
            attempt_id=attempt_id,
            case_id="case-v09",
            status=AttemptStatus.RESERVED,
        )


def test_reserved_demo_sends_exactly_one_selected_message(monkeypatch):
    monkeypatch.setenv("N8N_DISPATCH_URL", "https://demo.example/webhook")
    monkeypatch.setenv("N8N_DISPATCH_TOKEN", "dummy-test-only")
    client = FakeHttp(status="reserved")
    sent = []
    def fake_sender(factory, message_id):
        sent.append(message_id)
        return {"status": "sent", "duplicate": False}
    result = run(client=client, factory=lambda: FakeSession("reserved"), sender=fake_sender)
    assert result["attempt_id"] == "att-v09"
    assert sent == ["msg-v09"]
    assert [(m, u) for m, u, _ in client.calls] == [
        ("POST", "/api/v1/absences"), ("GET", "/api/v1/cases/case-v09"),
    ]


def test_duplicate_run_never_replans_or_resends_notified_offer(monkeypatch):
    monkeypatch.setenv("N8N_DISPATCH_URL", "https://demo.example/webhook")
    monkeypatch.setenv("N8N_DISPATCH_TOKEN", "dummy-test-only")
    client = FakeHttp(status="notified")
    sent = []
    result = run(client=client, factory=lambda: FakeSession("notified"),
                 sender=lambda *args: sent.append(args))
    assert result["dispatch"] == {"status": "already_notified", "duplicate": True}
    assert not sent
    assert not any(uri.endswith("/plan") for _, uri, _ in client.calls)
