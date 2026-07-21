import uuid

import fakeredis

from app.services.session_store import SessionStore


def test_session_store_uses_hashed_redis_key() -> None:
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    store = SessionStore(redis_client=redis_client, ttl_seconds=3600)
    user_id = uuid.uuid4()

    token = store.create(user_id)
    keys = redis_client.keys("auth:session:*")

    assert len(keys) == 1
    assert token not in keys[0]
    assert store.get_user_id(token) == user_id

    store.delete(token)
    assert store.get_user_id(token) is None
