"""Synchronize onboarding and candidate process stages.

Revision ID: 20260729_0029
Revises: 20260729_0028
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0029"
down_revision: str | None = "20260729_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS_STAGES = (
    "'unprocessed', 'pending', 'shortlisted', 'to_contact', "
    "'contacted', 'to_interview', 'completed', 'rejected', "
    "'offer_pending_response', 'offer_rejected', "
    "'onboarding_pending_confirmation'"
)
_NEW_STAGES = (
    f"{_PREVIOUS_STAGES}, 'onboarding_pending_start', "
    "'onboarding_completed', 'onboarding_abandoned'"
)
_TARGET_STAGE = {
    "pending_confirmation": "onboarding_pending_confirmation",
    "candidate_proposed_date": "onboarding_pending_confirmation",
    "pending_start": "onboarding_pending_start",
    "onboarded": "onboarding_completed",
    "abandoned": "onboarding_abandoned",
}


def _replace_stage_constraints(stage_values: str) -> None:
    op.drop_constraint(
        "ck_candidate_process_events_to_stage",
        "candidate_process_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_candidate_process_events_from_stage",
        "candidate_process_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_candidate_processes_stage",
        "candidate_processes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_candidate_processes_stage",
        "candidate_processes",
        f"current_stage IN ({stage_values})",
    )
    op.create_check_constraint(
        "ck_candidate_process_events_from_stage",
        "candidate_process_events",
        f"from_stage IN ({stage_values})",
    )
    op.create_check_constraint(
        "ck_candidate_process_events_to_stage",
        "candidate_process_events",
        f"to_stage IN ({stage_values})",
    )


def _backfill_current_stages() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT o.application_id, o.status, o.updated_at, "
            "p.id AS process_id, p.current_stage "
            "FROM onboardings o "
            "LEFT JOIN candidate_processes p ON p.application_id = o.application_id"
        )
    ).mappings()
    for row in rows:
        target_stage = _TARGET_STAGE[row["status"]]
        process_id = row["process_id"]
        previous_stage = row["current_stage"] or "completed"
        if process_id is None:
            process_id = uuid.uuid4()
            connection.execute(
                sa.text(
                    "INSERT INTO candidate_processes "
                    "(id, application_id, current_stage, stage_entered_at, updated_by_id) "
                    "VALUES (:id, :application_id, :stage, :entered_at, NULL)"
                ),
                {
                    "id": process_id,
                    "application_id": row["application_id"],
                    "stage": target_stage,
                    "entered_at": row["updated_at"],
                },
            )
            sequence_number = 1
        elif previous_stage != target_stage:
            sequence_number = connection.scalar(
                sa.text(
                    "SELECT COALESCE(MAX(sequence_number), 0) + 1 "
                    "FROM candidate_process_events WHERE process_id = :process_id"
                ),
                {"process_id": process_id},
            )
            connection.execute(
                sa.text(
                    "UPDATE candidate_processes "
                    "SET current_stage = :stage, stage_entered_at = :entered_at, "
                    "updated_by_id = NULL, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = :process_id"
                ),
                {
                    "stage": target_stage,
                    "entered_at": row["updated_at"],
                    "process_id": process_id,
                },
            )
        else:
            continue

        connection.execute(
            sa.text(
                "INSERT INTO candidate_process_events "
                "(id, process_id, sequence_number, from_stage, to_stage, reason, operator_id) "
                "VALUES (:id, :process_id, :sequence_number, :from_stage, :to_stage, "
                ":reason, NULL)"
            ),
            {
                "id": uuid.uuid4(),
                "process_id": process_id,
                "sequence_number": sequence_number,
                "from_stage": previous_stage,
                "to_stage": target_stage,
                "reason": "F21 入职状态阶段回填",
            },
        )


def upgrade() -> None:
    _replace_stage_constraints(_NEW_STAGES)
    _backfill_current_stages()


def downgrade() -> None:
    connection = op.get_bind()
    stage_case = (
        "CASE "
        "WHEN {column} = 'onboarding_pending_start' "
        "THEN 'onboarding_pending_confirmation' "
        "ELSE 'completed' END"
    )
    connection.execute(
        sa.text(
            "UPDATE candidate_process_events SET from_stage = "
            + stage_case.format(column="from_stage")
            + " WHERE from_stage IN ('onboarding_pending_start', "
            "'onboarding_completed', 'onboarding_abandoned')"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE candidate_process_events SET to_stage = "
            + stage_case.format(column="to_stage")
            + " WHERE to_stage IN ('onboarding_pending_start', "
            "'onboarding_completed', 'onboarding_abandoned')"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE candidate_processes SET current_stage = "
            + stage_case.format(column="current_stage")
            + " WHERE current_stage IN ('onboarding_pending_start', "
            "'onboarding_completed', 'onboarding_abandoned')"
        )
    )
    _replace_stage_constraints(_PREVIOUS_STAGES)
