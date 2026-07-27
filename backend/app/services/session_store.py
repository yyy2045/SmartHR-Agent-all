import hashlib
import secrets
import uuid
from dataclasses import dataclass

from redis import Redis


@dataclass(frozen=True)
class SessionIdentity:
    user_id: uuid.UUID
    session_version: int


class SessionStore:
    key_prefix = "auth:session:"

    def __init__(self, redis_client: Redis, ttl_seconds: int) -> None:
        self.redis_client = redis_client
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(token: str) -> str:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"{SessionStore.key_prefix}{token_hash}"

    def create(self, user_id: uuid.UUID, session_version: int = 1) -> str:
        token = secrets.token_urlsafe(32)
        self.redis_client.setex(
            self._key(token), self.ttl_seconds, f"{user_id}:{session_version}"
        )
        return token

    def get_identity(self, token: str) -> SessionIdentity | None:
        value = self.redis_client.get(self._key(token))
        if not value:
            return None

        try:
            raw_value = value.decode() if isinstance(value, bytes) else value
            user_id, raw_version = raw_value.split(":", maxsplit=1)
            version = int(raw_version)
            if version < 1:
                raise ValueError
            return SessionIdentity(user_id=uuid.UUID(user_id), session_version=version)
        except (AttributeError, TypeError, ValueError):
            self.delete(token)
            return None

    def get_user_id(self, token: str) -> uuid.UUID | None:
        identity = self.get_identity(token)
        return identity.user_id if identity else None

    def delete(self, token: str) -> None:
        self.redis_client.delete(self._key(token))
