import uuid

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Job, User


def job_scope_clause(user: User):
    if user.has_role("administrator"):
        return Job.id.is_not(None)
    return or_(Job.owner_id == user.id, Job.hiring_manager_id == user.id)


def get_visible_job(db: Session, job_id: uuid.UUID, user: User) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, job_scope_clause(user)))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    return job


def ensure_job_writable(job: Job, user: User) -> None:
    if user.has_role("administrator") or job.owner_id == user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="当前角色只能查看该职位",
    )
