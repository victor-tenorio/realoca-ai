from enum import StrEnum

class Availability(StrEnum):
    AVAILABLE = "available"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"

class Channel(StrEnum):
    TEAMS = "teams"
    SLACK = "slack"

class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"

class CaseStatus(StrEnum):
    OPEN = "open"
    PLANNING = "planning"
    PENDING_APPROVAL = "pending_approval"
    AWAITING_RESPONSES = "awaiting_responses"
    COVERAGE_CONFIRMED = "coverage_confirmed"
    CLOSED_WITH_GAPS = "closed_with_gaps"
    COMPLETED = "completed"

class AttemptStatus(StrEnum):
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    RESERVED = "reserved"
    NOTIFIED = "notified"
    ACCEPTED = "accepted"
    REFUSED = "refused"
    EXPIRED = "expired"
    REJECTED_BY_BP = "rejected_by_bp"
    ESCALATED = "escalated"


class IntegrationEventType(StrEnum):
    DELIVERED = "offer.delivered"
    DELIVERY_FAILED = "offer.delivery_failed"
    ACCEPTED = "offer.accepted"
    REFUSED = "offer.refused"
    EXPIRED = "offer.expired"


ACTIVE_ATTEMPT_STATUSES = (
    AttemptStatus.PROPOSED, AttemptStatus.PENDING_APPROVAL,
    AttemptStatus.RESERVED, AttemptStatus.NOTIFIED,
)
