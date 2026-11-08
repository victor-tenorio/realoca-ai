"""Guard confirmed absence overlaps and support audit without policy decisions."""

import sqlalchemy as sa
from alembic import op

revision = "b07c91d42e36"
down_revision = "65aad520e5e0"
branch_labels = None
depends_on = None

POLICY_CONTEXT = (
    "policy_version IS NOT NULL OR action IN "
    "('absence.confirmed', 'case.opened', 'impact.detected', 'impact.no_registered_tasks')"
)


def drop_audit_guards():
    for action in ("update", "delete", "replace"):
        op.execute(f"DROP TRIGGER IF EXISTS guard_audit_events_{action}")


def restore_audit_guards():
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER guard_audit_events_{action.lower()} BEFORE {action} ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
        )
    op.execute("""CREATE TRIGGER guard_audit_events_replace BEFORE INSERT ON audit_events
        WHEN EXISTS (SELECT 1 FROM audit_events WHERE audit_event_id=NEW.audit_event_id)
        BEGIN SELECT RAISE(ABORT, 'audit_events identity already exists'); END""")


def upgrade():
    drop_audit_guards()
    with op.batch_alter_table("audit_events", recreate="always") as batch:
        batch.alter_column("policy_version", existing_type=sa.Integer(), nullable=True)
        batch.create_check_constraint("ck_audit_policy_context", POLICY_CONTEXT)
    restore_audit_guards()
    op.create_index(
        "ix_absences_employee_interval",
        "absences",
        ["employee_id", "starts_at", "ends_at"],
    )
    for action in ("INSERT", "UPDATE"):
        op.execute(f"""CREATE TRIGGER guard_absence_overlap_{action.lower()} BEFORE {action} ON absences
            WHEN NEW.confirmed=1 AND EXISTS (
                SELECT 1 FROM absences a WHERE a.confirmed=1 AND a.employee_id=NEW.employee_id
                AND a.absence_id != NEW.absence_id
                AND a.starts_at < NEW.ends_at AND a.ends_at > NEW.starts_at)
            BEGIN SELECT RAISE(ABORT, 'absence_overlap'); END""")


def downgrade():
    # Do not destroy immutable history or invent a policy version to fit old DDL.
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM audit_events WHERE policy_version IS NULL")
    ):
        raise RuntimeError(
            "Downgrade blocked: non-policy audit history cannot fit the previous revision"
        )
    for action in ("insert", "update"):
        op.execute(f"DROP TRIGGER guard_absence_overlap_{action}")
    op.drop_index("ix_absences_employee_interval", table_name="absences")
    drop_audit_guards()
    with op.batch_alter_table("audit_events", recreate="always") as batch:
        batch.drop_constraint("ck_audit_policy_context", type_="check")
        batch.alter_column("policy_version", existing_type=sa.Integer(), nullable=False)
    restore_audit_guards()
