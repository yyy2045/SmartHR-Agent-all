from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import CandidateProcess, CandidateProcessEvent, JobApplication, User


def change_candidate_process_stage(
    db: Session,
    application: JobApplication,
    *,
    target_stage: str,
    reason: str,
    operator: User | None,
) -> CandidateProcess | None:
    process = application.process
    previous_stage = process.current_stage if process is not None else "completed"
    if previous_stage == target_stage:
        return process

    now = datetime.now(UTC)
    if process is None:
        process = CandidateProcess(
            application_id=application.id,
            current_stage=target_stage,
            stage_entered_at=now,
            updated_by_id=operator.id if operator is not None else None,
        )
        db.add(process)
        db.flush()
        sequence_number = 1
    else:
        sequence_number = len(process.events) + 1
        process.current_stage = target_stage
        process.stage_entered_at = now
        process.updated_by_id = operator.id if operator is not None else None
    db.add(
        CandidateProcessEvent(
            process_id=process.id,
            sequence_number=sequence_number,
            from_stage=previous_stage,
            to_stage=target_stage,
            reason=reason,
            operator_id=operator.id if operator is not None else None,
        )
    )
    return process
