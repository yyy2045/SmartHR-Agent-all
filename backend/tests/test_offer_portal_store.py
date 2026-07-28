import uuid

import fakeredis

from app.services.offer_portal import (
    OfferPortalVerificationStore,
    create_portal_token,
    hash_portal_token,
    phone_last_four,
    phone_verification_digest,
)


def test_portal_token_and_verification_session_are_hashed_in_storage() -> None:
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    store = OfferPortalVerificationStore(
        redis_client=redis_client,
        verification_ttl_seconds=900,
        max_attempts=5,
        lock_seconds=900,
    )
    link_id = uuid.uuid4()

    portal_token = create_portal_token()
    verification_token, expires_at = store.create_verification(link_id)
    keys = [str(item) for item in redis_client.keys("offer_portal:*")]

    assert len(portal_token) >= 32
    assert len(hash_portal_token(portal_token)) == 64
    assert portal_token not in keys
    assert verification_token not in keys
    assert expires_at > store.get_verification(verification_token).verified_at
    assert store.get_verification(verification_token).link_id == link_id


def test_portal_verification_failures_lock_at_configured_limit() -> None:
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    store = OfferPortalVerificationStore(
        redis_client=redis_client,
        verification_ttl_seconds=900,
        max_attempts=5,
        lock_seconds=900,
    )
    link_id = uuid.uuid4()

    for _ in range(4):
        result = store.record_failure(link_id)
        assert result.locked is False
    result = store.record_failure(link_id)

    assert result.locked is True
    assert result.retry_after_seconds == 900
    assert store.lock_remaining_seconds(link_id) > 0


def test_phone_last_four_uses_normalized_digits() -> None:
    assert phone_last_four("+86 138-0000-1234") == "1234"
    assert phone_last_four("123") is None
    assert phone_last_four(None) is None


def test_phone_verification_digest_is_bound_to_link_and_secret() -> None:
    link_id = uuid.uuid4()
    digest = phone_verification_digest(
        "1234",
        link_id=link_id,
        secret_key="first-test-secret",
    )

    assert len(digest) == 64
    assert "1234" not in digest
    assert digest == phone_verification_digest(
        "1234",
        link_id=link_id,
        secret_key="first-test-secret",
    )
    assert digest != phone_verification_digest(
        "1234",
        link_id=uuid.uuid4(),
        secret_key="first-test-secret",
    )
    assert digest != phone_verification_digest(
        "1234",
        link_id=link_id,
        secret_key="second-test-secret",
    )
