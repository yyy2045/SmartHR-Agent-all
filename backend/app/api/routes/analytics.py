import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.schemas.analytics import (
    ANALYTICS_TIMEZONE,
    AnalyticsCurrentDistributionResponse,
    AnalyticsFunnelResponse,
    AnalyticsOverviewResponse,
    AnalyticsQuery,
    AnalyticsTrendResponse,
)
from app.services.analytics import (
    build_analytics_context,
    collect_current_distribution,
    collect_funnel,
    collect_overview,
    collect_trend,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _analytics_query(
    start_date: date | None,
    end_date: date | None,
    job_id: uuid.UUID | None,
) -> AnalyticsQuery:
    today = datetime.now(ZoneInfo(ANALYTICS_TIMEZONE)).date()
    resolved_end = end_date or today
    resolved_start = start_date or resolved_end - timedelta(days=29)
    try:
        return AnalyticsQuery(
            start_date=resolved_start,
            end_date=resolved_end,
            job_id=job_id,
        )
    except ValidationError as exc:
        message = exc.errors(include_url=False)[0]["msg"].removeprefix("Value error, ")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=message,
        ) from exc


def _context(
    db: Session,
    current_user: CurrentUser,
    start_date: date | None,
    end_date: date | None,
    job_id: uuid.UUID | None,
):
    query = _analytics_query(start_date, end_date, job_id)
    return build_analytics_context(
        db,
        current_user,
        query,
        as_of=datetime.now(UTC),
    )


@router.get("/overview", response_model=AnalyticsOverviewResponse)
def get_analytics_overview(
    current_user: CurrentUser,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    job_id: uuid.UUID | None = None,
) -> AnalyticsOverviewResponse:
    return collect_overview(
        db,
        _context(db, current_user, start_date, end_date, job_id),
    )


@router.get("/funnel", response_model=AnalyticsFunnelResponse)
def get_analytics_funnel(
    current_user: CurrentUser,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    job_id: uuid.UUID | None = None,
) -> AnalyticsFunnelResponse:
    return collect_funnel(
        db,
        _context(db, current_user, start_date, end_date, job_id),
    )


@router.get(
    "/current-distribution",
    response_model=AnalyticsCurrentDistributionResponse,
)
def get_analytics_current_distribution(
    current_user: CurrentUser,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    job_id: uuid.UUID | None = None,
) -> AnalyticsCurrentDistributionResponse:
    return collect_current_distribution(
        db,
        _context(db, current_user, start_date, end_date, job_id),
    )


@router.get("/trend", response_model=AnalyticsTrendResponse)
def get_analytics_trend(
    current_user: CurrentUser,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    job_id: uuid.UUID | None = None,
    interval: Annotated[str | None, Query(pattern="^(day|week)$")] = None,
) -> AnalyticsTrendResponse:
    context = _context(db, current_user, start_date, end_date, job_id)
    inclusive_days = (context.query.end_date - context.query.start_date).days + 1
    resolved_interval = interval or ("day" if inclusive_days <= 30 else "week")
    if resolved_interval == "day" and inclusive_days > 30:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="超过 30 天的趋势必须按周聚合",
        )
    return collect_trend(db, context, interval=resolved_interval)
