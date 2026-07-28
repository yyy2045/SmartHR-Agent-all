from functools import lru_cache

from redis import Redis

from app.config import settings
from app.services.offer_portal import OfferPortalVerificationStore
from app.services.session_store import SessionStore


@lru_cache
def get_redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


@lru_cache
def get_session_store() -> SessionStore:
    return SessionStore(
        redis_client=get_redis_client(),
        ttl_seconds=settings.app_session_expire_minutes * 60,
    )


@lru_cache
def get_offer_portal_store() -> OfferPortalVerificationStore:
    return OfferPortalVerificationStore(
        redis_client=get_redis_client(),
        verification_ttl_seconds=(
            settings.offer_portal_verification_session_minutes * 60
        ),
        max_attempts=settings.offer_portal_max_attempts,
        lock_seconds=settings.offer_portal_lock_minutes * 60,
    )
