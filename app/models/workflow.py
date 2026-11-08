"""Workflow persistence only. Transitions and side effects belong to future services."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import AttemptStatus, CaseStatus, Channel, IntegrationEventType
from app.models.core import (
    Employee,
    Hours,
    SourceMixin,
    Task,
    UTCDateTime,
    official_enum,
)

case_absences = Table(
    "case_absences",
    Base.metadata,
    Column("case_id", ForeignKey("cases.case_id"), primary_key=True),
    Column("absence_id", ForeignKey("absences.absence_id"), primary_key=True),
)
case_tasks = Table(
    "case_tasks",
    Base.metadata,
    Column("case_id", ForeignKey("cases.case_id"), primary_key=True),
    Column("task_id", ForeignKey("tasks.task_id"), primary_key=True),
)


class Absence(SourceMixin, Base):
    __tablename__ = "absences"
    __table_args__ = (
        UniqueConstraint("source_system", "external_id"),
        CheckConstraint("ends_at > starts_at", name="ck_absence_interval"),
        Index("ix_absences_employee_interval", "employee_id", "starts_at", "ends_at"),
    )
    absence_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.employee_id"))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime())
    confirmed: Mapped[bool] = mapped_column(Boolean(create_constraint=True))
    employee: Mapped[Employee] = relationship()
    cases: Mapped[list["Case"]] = relationship(
        secondary=case_absences, back_populates="absences"
    )


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint("plan_version >= 0", name="ck_case_version"),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= created_at", name="ck_case_closed"
        ),
    )
    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[CaseStatus] = mapped_column(
        official_enum(CaseStatus), default=CaseStatus.OPEN
    )
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    absences: Mapped[list[Absence]] = relationship(
        secondary=case_absences, back_populates="cases"
    )
    tasks: Mapped[list[Task]] = relationship(secondary=case_tasks)
    plans: Mapped[list["CoveragePlan"]] = relationship(
        back_populates="case", passive_deletes="all"
    )


class PolicyVersion(Base):
    """Immutable versions; decisions reference the exact version, never a mutable total."""

    __tablename__ = "policy_versions"
    __table_args__ = (
        CheckConstraint("policy_version > 0", name="ck_policy_version"),
        CheckConstraint(
            "max_utilization_pct > 0 AND max_utilization_pct <= 100",
            name="ck_policy_utilization",
        ),
        CheckConstraint("response_timeout_minutes > 0", name="ck_policy_timeout"),
        CheckConstraint(
            "reminder_before_expiry_minutes >= 0 AND reminder_before_expiry_minutes < response_timeout_minutes",
            name="ck_policy_reminder",
        ),
    )
    policy_version: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    max_utilization_pct: Mapped[Decimal] = mapped_column(
        Hours(), default=90, server_default="90"
    )
    critical_requires_bp: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True), default=True, server_default=text("1")
    )
    cross_team_requires_bp: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True), default=True, server_default=text("1")
    )
    response_timeout_minutes: Mapped[int] = mapped_column(
        Integer, default=15, server_default="15"
    )
    allow_automatic_same_team: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True), default=True, server_default=text("1")
    )
    reminder_before_expiry_minutes: Mapped[int] = mapped_column(
        Integer, default=5, server_default="5"
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class CoveragePlan(Base):
    __tablename__ = "coverage_plans"
    __table_args__ = (
        UniqueConstraint("case_id", "plan_version"),
        UniqueConstraint("plan_id", "case_id", "plan_version"),
        CheckConstraint("plan_version > 0", name="ck_plan_version"),
    )
    plan_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"))
    plan_version: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[int] = mapped_column(
        ForeignKey("policy_versions.policy_version")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    case: Mapped[Case] = relationship(back_populates="plans")
    policy: Mapped[PolicyVersion] = relationship()


class CoverageAttempt(Base):
    __tablename__ = "coverage_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "case_id", "plan_version"],
            [
                "coverage_plans.plan_id",
                "coverage_plans.case_id",
                "coverage_plans.plan_version",
            ],
        ),
        ForeignKeyConstraint(
            ["case_id", "task_id"], ["case_tasks.case_id", "case_tasks.task_id"]
        ),
        UniqueConstraint("attempt_id", "case_id"),
        CheckConstraint(
            "candidate_employee_id IS NOT NULL OR status = 'escalated'",
            name="ck_attempt_candidate",
        ),
        CheckConstraint(
            "response_deadline_at IS NULL OR response_deadline_at > created_at",
            name="ck_attempt_deadline",
        ),
        CheckConstraint(
            "responded_at IS NULL OR responded_at >= created_at",
            name="ck_attempt_response",
        ),
        CheckConstraint(
            "status NOT IN ('reserved','notified') OR response_deadline_at IS NOT NULL",
            name="ck_pending_deadline",
        ),
        CheckConstraint(
            "approval_decision IS NULL OR approval_decision IN ('approve','reject')",
            name="ck_approval_decision",
        ),
        CheckConstraint(
            "(approval_decision IS NULL AND approval_actor_id IS NULL AND approval_reason IS NULL AND approval_decided_at IS NULL) OR (approval_decision IS NOT NULL AND approval_actor_id IS NOT NULL AND approval_decided_at IS NOT NULL)",
            name="ck_approval_record",
        ),
        CheckConstraint(
            "approval_decided_at IS NULL OR approval_decided_at >= created_at",
            name="ck_approval_time",
        ),
        Index(
            "uq_active_attempt_task",
            "task_id",
            unique=True,
            sqlite_where=text(
                "status IN ('proposed','pending_approval','reserved','notified')"
            ),
        ),
    )
    attempt_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String)
    plan_id: Mapped[str] = mapped_column(String)
    plan_version: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    candidate_employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.employee_id")
    )
    policy_version: Mapped[int] = mapped_column(
        ForeignKey("policy_versions.policy_version")
    )
    status: Mapped[AttemptStatus] = mapped_column(official_enum(AttemptStatus))
    response_deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision_actor_id: Mapped[str | None] = mapped_column(String)
    # Approval is separate from employee response; values are official approve/reject.
    approval_decision: Mapped[str | None] = mapped_column(String)
    approval_actor_id: Mapped[str | None] = mapped_column(String)
    approval_reason: Mapped[str | None] = mapped_column(Text)
    approval_decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    plan: Mapped[CoveragePlan] = relationship(
        foreign_keys=[plan_id, case_id, plan_version], overlaps="affected_task"
    )
    affected_task: Mapped[Task] = relationship(foreign_keys=[task_id])
    candidate: Mapped[Employee | None] = relationship()
    policy: Mapped[PolicyVersion] = relationship()
    reservation: Mapped["Reservation | None"] = relationship(
        back_populates="attempt", passive_deletes="all"
    )

    @property
    def reserved_hours(self) -> Decimal:
        row = self.reservation
        return (
            row.reserved_hours
            if row is not None and row.released_at is None
            else Decimal(0)
        )


class Reservation(Base):
    """Candidate/task/shift derive from the attempt; no duplicated foreign identities."""

    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("reserved_hours >= 0", name="ck_reservation_hours"),
        CheckConstraint(
            "released_at IS NULL OR released_at >= created_at",
            name="ck_reservation_release",
        ),
    )
    reservation_id: Mapped[str] = mapped_column(String, primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("coverage_attempts.attempt_id"), unique=True
    )
    reserved_hours: Mapped[Decimal] = mapped_column(Hours())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    attempt: Mapped[CoverageAttempt] = relationship(back_populates="reservation")


class ProcessedEvent(Base):
    """Inbox storage, not an idempotent event processor. Never store request headers."""

    __tablename__ = "processed_events"
    __table_args__ = (
        CheckConstraint(
            "(processed_at IS NULL AND result IS NULL AND response_status IS NULL) OR (processed_at IS NOT NULL AND result IS NOT NULL AND response_status IS NOT NULL AND response_status BETWEEN 100 AND 599)",
            name="ck_event_result",
        ),
        CheckConstraint(
            "processed_at IS NULL OR processed_at >= received_at",
            name="ck_event_processed",
        ),
    )
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[IntegrationEventType] = mapped_column(
        official_enum(IntegrationEventType)
    )
    attempt_id: Mapped[str] = mapped_column(ForeignKey("coverage_attempts.attempt_id"))
    channel: Mapped[Channel] = mapped_column(official_enum(Channel))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    reason: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime())
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    result: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    response_status: Mapped[int | None] = mapped_column(Integer)
    attempt: Mapped[CoverageAttempt] = relationship()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "case_id"],
            ["coverage_attempts.attempt_id", "coverage_attempts.case_id"],
        ),
        CheckConstraint(
            "attempt_id IS NULL OR case_id IS NOT NULL", name="ck_audit_case"
        ),
        CheckConstraint(
            "policy_version IS NOT NULL OR action IN ('absence.confirmed', 'case.opened', 'impact.detected', 'impact.no_registered_tasks')",
            name="ck_audit_policy_context",
        ),
    )
    audit_event_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.case_id"))
    attempt_id: Mapped[str | None] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    policy_version: Mapped[int | None] = mapped_column(
        ForeignKey("policy_versions.policy_version")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON(none_as_null=True))


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        CheckConstraint("event_type = 'offer.created'", name="ck_outbound_event"),
    )
    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(String, unique=True)
    event_type: Mapped[str] = mapped_column(
        String, default="offer.created", server_default="offer.created"
    )
    attempt_id: Mapped[str] = mapped_column(ForeignKey("coverage_attempts.attempt_id"))
    channel: Mapped[Channel] = mapped_column(official_enum(Channel))
    channel_user_id: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    simulated: Mapped[bool] = mapped_column(Boolean(create_constraint=True))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    attempt: Mapped[CoverageAttempt] = relationship()
    deliveries: Mapped[list["MessageDelivery"]] = relationship(
        back_populates="message_record", passive_deletes="all"
    )


class MessageDelivery(Base):
    """One row per transport try. Sending/delivery timestamps are not acceptance."""

    __tablename__ = "message_deliveries"
    __table_args__ = (
        UniqueConstraint("message_id", "delivery_number"),
        CheckConstraint("delivery_number > 0", name="ck_delivery_number"),
        CheckConstraint(
            "sent_at IS NULL OR sent_at >= started_at", name="ck_delivery_sent"
        ),
        CheckConstraint(
            "failed_at IS NULL OR failed_at >= started_at", name="ck_delivery_failed"
        ),
        CheckConstraint(
            "sent_at IS NULL OR failed_at IS NULL", name="ck_delivery_outcome"
        ),
        CheckConstraint(
            "delivered_at IS NULL OR (sent_at IS NOT NULL AND delivered_at >= sent_at)",
            name="ck_delivery_received",
        ),
    )
    delivery_id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("outbound_messages.message_id"))
    delivery_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_code: Mapped[str | None] = mapped_column(String)
    provider_message_id: Mapped[str | None] = mapped_column(String)
    message_record: Mapped[OutboundMessage] = relationship(back_populates="deliveries")
