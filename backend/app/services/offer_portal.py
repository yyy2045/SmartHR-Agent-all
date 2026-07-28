import hashlib
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis import Redis


def create_portal_token() -> str:
    return secrets.token_urlsafe(32)


def hash_portal_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def phone_last_four(phone: str | None) -> str | None:
    if phone is None:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits[-4:] if len(digits) >= 4 else None


def portal_link_is_expired(expires_at: datetime) -> bool:
    normalized = (
        expires_at.replace(tzinfo=UTC)
        if expires_at.tzinfo is None
        else expires_at.astimezone(UTC)
    )
    return normalized <= datetime.now(UTC)


@dataclass(frozen=True)
class PortalVerificationIdentity:
    link_id: uuid.UUID
    verified_at: datetime


@dataclass(frozen=True)
class PortalFailureResult:
    locked: bool
    retry_after_seconds: int | None


class OfferPortalVerificationStore:
    session_prefix = "offer_portal:session:"
    failure_prefix = "offer_portal:failure:"
    lock_prefix = "offer_portal:lock:"

    def __init__(
        self,
        redis_client: Redis,
        verification_ttl_seconds: int,
        max_attempts: int,
        lock_seconds: int,
    ) -> None:
        self.redis_client = redis_client
        self.verification_ttl_seconds = verification_ttl_seconds
        self.max_attempts = max_attempts
        self.lock_seconds = lock_seconds

    @classmethod
    def _session_key(cls, token: str) -> str:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"{cls.session_prefix}{digest}"

    @classmethod
    def _failure_key(cls, link_id: uuid.UUID) -> str:
        return f"{cls.failure_prefix}{link_id}"

    @classmethod
    def _lock_key(cls, link_id: uuid.UUID) -> str:
        return f"{cls.lock_prefix}{link_id}"

    def create_verification(self, link_id: uuid.UUID) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        verified_at = datetime.now(UTC)
        value = json.dumps(
            {"link_id": str(link_id), "verified_at": verified_at.isoformat()},
            separators=(",", ":"),
        )
        self.redis_client.setex(
            self._session_key(token),
            self.verification_ttl_seconds,
            value,
        )
        return token, verified_at + timedelta(seconds=self.verification_ttl_seconds)

    def get_verification(self, token: str) -> PortalVerificationIdentity | None:
        key = self._session_key(token)
        value = self.redis_client.get(key)
        if not value:
            return None
        try:
            raw = value.decode() if isinstance(value, bytes) else value
            payload = json.loads(raw)
            return PortalVerificationIdentity(
                link_id=uuid.UUID(payload["link_id"]),
                verified_at=datetime.fromisoformat(payload["verified_at"]),
            )
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.redis_client.delete(key)
            return None

    def delete_verification(self, token: str) -> None:
        self.redis_client.delete(self._session_key(token))

    def lock_remaining_seconds(self, link_id: uuid.UUID) -> int | None:
        ttl = self.redis_client.ttl(self._lock_key(link_id))
        return int(ttl) if ttl is not None and ttl > 0 else None

    def record_failure(self, link_id: uuid.UUID) -> PortalFailureResult:
        failure_key = self._failure_key(link_id)
        count = int(self.redis_client.incr(failure_key))
        if count == 1:
            self.redis_client.expire(failure_key, self.lock_seconds)
        if count < self.max_attempts:
            return PortalFailureResult(locked=False, retry_after_seconds=None)

        self.redis_client.setex(self._lock_key(link_id), self.lock_seconds, "1")
        self.redis_client.delete(failure_key)
        return PortalFailureResult(locked=True, retry_after_seconds=self.lock_seconds)

    def clear_failures(self, link_id: uuid.UUID) -> None:
        self.redis_client.delete(self._failure_key(link_id))
