import hashlib
import secrets
import uuid

from redis import Redis


class SessionStore:
    key_prefix = "auth:session:"

    def __init__(self, redis_client: Redis, ttl_seconds: int) -> None:
        self.redis_client = redis_client
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(token: str) -> str:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"{SessionStore.key_prefix}{token_hash}"

    def create(self, user_id: uuid.UUID) -> str:
        token = secrets.token_urlsafe(32)
        self.redis_client.setex(self._key(token), self.ttl_seconds, str(user_id))
        return token

    def get_user_id(self, token: str) -> uuid.UUID | None:
        value = self.redis_client.get(self._key(token))
        if not value:
            return None

        try:
            return uuid.UUID(value.decode() if isinstance(value, bytes) else value)
        except (TypeError, ValueError):
            self.delete(token)
            return None

    def delete(self, token: str) -> None:
        self.redis_client.delete(self._key(token))
