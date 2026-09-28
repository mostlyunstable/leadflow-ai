"""
Contract Tests for EmailProvider Protocol.
Verifies:
1. Providers strictly implement the EmailProvider protocol.
2. Returns standardized SendResult with correct success, retryability, and message IDs.
3. Handles transient network errors and rate limits with retryable=True.
4. Handles client/permanent errors with retryable=False.
"""

import pytest
from modules.email_sender.provider_interface import (
    EmailProvider, MockEmailProvider, OutboundMessage, SendResult
)


def test_mock_provider_implements_protocol():
    provider: EmailProvider = MockEmailProvider()
    assert provider.provider_name == "mock"
    assert provider.verify_account() is True

    msg = OutboundMessage(
        to_email="test@target.com",
        from_email="sender@domain.com",
        subject="Test Subject",
        body_text="Test Body",
        idempotency_key="key-contract-1",
    )
    result = provider.send(msg)

    assert isinstance(result, SendResult)
    assert result.success is True
    assert result.provider_message_id is not None
    assert result.provider_thread_id is not None
    assert result.retryable is False


def test_mock_provider_failure_modes():
    # Transient retryable failure
    retryable_provider = MockEmailProvider(should_fail=True, retryable_error=True)
    msg = OutboundMessage(
        to_email="fail@target.com",
        from_email="sender@domain.com",
        subject="Test",
        body_text="Test",
        idempotency_key="key-contract-2",
    )
    res = retryable_provider.send(msg)
    assert res.success is False
    assert res.retryable is True

    # Permanent non-retryable failure
    perm_provider = MockEmailProvider(should_fail=True, retryable_error=False)
    res_perm = perm_provider.send(msg)
    assert res_perm.success is False
    assert res_perm.retryable is False
