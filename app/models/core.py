from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Numeric, String, Table, Column, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.types import TypeDecorator
from app.db import Base
from app.enums import Channel, Priority, TaskStatus

class UTCDateTime(TypeDecorator):
    """Store naive UTC on SQLite; always return aware UTC and reject naive input."""
    impl = DateTime
    cache_ok = True
    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value else None

def official_enum(enum):
    return Enum(enum, native_enum=False, create_constraint=True, validate_strings=True,
                values_callable=lambda values: [item.value for item in values])

class Hours(TypeDecorator):
    """Accept exact finite hours with at most six decimal places; never round input."""
    impl = Numeric(12, 6)
    cache_ok = True
    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = Decimal(str(value))
        if not value.is_finite() or abs(value) >= Decimal("1000000") or value != value.quantize(Decimal("0.000001")):
            raise ValueError("hours must be finite, below 1000000 and have at most six decimals")
        return value

class SourceMixin:
    source_system: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

employee_skills = Table("employee_skills", Base.metadata,
    Column("employee_id", ForeignKey("employees.employee_id"), primary_key=True),
    Column("skill_id", ForeignKey("skills.skill_id"), primary_key=True))
task_skills = Table("task_skills", Base.metadata,
    Column("task_id", ForeignKey("tasks.task_id"), primary_key=True),
    Column("skill_id", ForeignKey("skills.skill_id"), primary_key=True))

class Team(SourceMixin, Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("source_system", "external_id"),)
    team_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    employees: Mapped[list["Employee"]] = relationship(back_populates="team")
    tasks: Mapped[list["Task"]] = relationship(back_populates="team")

class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (CheckConstraint("skill_id = lower(trim(skill_id)) AND length(skill_id) > 0"),)
    skill_id: Mapped[str] = mapped_column(String, primary_key=True)
    @validates("skill_id")
    def normalize(self, key, value):
        value = value.strip().lower()
        if not value:
            raise ValueError("empty skill identifier")
        return value

class Employee(SourceMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("source_system", "external_id"),)
    employee_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    job_title: Mapped[str | None] = mapped_column(String)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.team_id"))
    skills_known: Mapped[bool] = mapped_column(Boolean(create_constraint=True), nullable=False)
    preferred_channel: Mapped[Channel | None] = mapped_column(official_enum(Channel))
    channel_user_id: Mapped[str | None] = mapped_column(String)
    team: Mapped[Team | None] = relationship(back_populates="employees")
    skills: Mapped[list[Skill]] = relationship(secondary=employee_skills)
    tasks: Mapped[list["Task"]] = relationship(back_populates="assignee")
    shifts: Mapped[list["EmployeeShift"]] = relationship(back_populates="employee")

class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (CheckConstraint("ends_at > starts_at"), UniqueConstraint("reference_date"))
    shift_id: Mapped[str] = mapped_column(String, primary_key=True)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

class EmployeeShift(Base):
    __tablename__ = "employee_shifts"
    __table_args__ = (CheckConstraint("shift_hours IS NULL OR shift_hours >= 0"),)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.employee_id"), primary_key=True)
    shift_id: Mapped[str] = mapped_column(ForeignKey("shifts.shift_id"), primary_key=True)
    shift_hours: Mapped[Decimal | None] = mapped_column(Hours())
    employee: Mapped[Employee] = relationship(back_populates="shifts")
    shift: Mapped[Shift] = relationship()

class Task(SourceMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("source_system", "external_id"),
        CheckConstraint("estimated_hours IS NULL OR estimated_hours > 0"))
    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.team_id"))
    assignee_employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.employee_id"))
    shift_id: Mapped[str] = mapped_column(ForeignKey("shifts.shift_id"), nullable=False)
    priority: Mapped[Priority | None] = mapped_column(official_enum(Priority))
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    estimated_hours: Mapped[Decimal | None] = mapped_column(Hours())
    status: Mapped[TaskStatus] = mapped_column(official_enum(TaskStatus), nullable=False)
    transfer_allowed: Mapped[bool | None] = mapped_column(Boolean(create_constraint=True))
    required_skills_known: Mapped[bool] = mapped_column(Boolean(create_constraint=True), nullable=False)
    team: Mapped[Team | None] = relationship(back_populates="tasks")
    assignee: Mapped[Employee | None] = relationship(back_populates="tasks")
    shift: Mapped[Shift] = relationship()
    required_skills: Mapped[list[Skill]] = relationship(secondary=task_skills)
    assignments: Mapped[list["TaskAssignment"]] = relationship(back_populates="task")

class TaskAssignment(Base):
    """Future history storage. Initial imported ownership is not a transfer."""
    __tablename__ = "task_assignments"
    assignment_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), nullable=False)
    from_employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.employee_id"))
    to_employee_id: Mapped[str] = mapped_column(ForeignKey("employees.employee_id"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    task: Mapped[Task] = relationship(back_populates="assignments")

class DemoSeedRun(Base):
    """Internal completion marker, committed atomically with all fixture rows."""
    __tablename__ = "demo_seed_runs"
    seed_id: Mapped[str] = mapped_column(String, primary_key=True)
    shift_id: Mapped[str] = mapped_column(ForeignKey("shifts.shift_id"), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
