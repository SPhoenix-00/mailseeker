"""Tests for SMTP check (with mocked DNS and SMTP)."""

from unittest.mock import MagicMock, patch

import pytest

from mailseeker.smtp_check import (
    AcceptedStatus,
    CheckResult,
    ResultCategory,
    check_email,
    classify_result,
    get_mx_hosts,
    interpret_code,
)


@pytest.mark.skipif(
    __import__("mailseeker.smtp_check", fromlist=["dns"]).dns is None,
    reason="dnspython not installed",
)
@patch("mailseeker.smtp_check.dns.resolver.resolve")
def test_get_mx_hosts_no_answer_raises(mock_resolve):
    import dns.resolver
    mock_resolve.side_effect = dns.resolver.NoAnswer()
    with pytest.raises(ValueError, match="No MX records"):
        get_mx_hosts("example.com")


def test_interpret_code():
    assert interpret_code(550) == "User unknown or mailbox unavailable"
    assert interpret_code(999) is None


def test_classify_result():
    """Result categories: Accepted (Valid/Limited), Rejected, Unverifiable."""
    cat, status, reason = classify_result(
        CheckResult(success=True, code=250, message="OK", email="x@y.com")
    )
    assert cat is ResultCategory.ACCEPTED
    assert status is AcceptedStatus.VALID
    assert reason is None

    cat, status, reason = classify_result(
        CheckResult(success=False, code=552, message="Mailbox full", email="x@y.com")
    )
    assert cat is ResultCategory.ACCEPTED
    assert status is AcceptedStatus.LIMITED
    assert reason is None

    cat, status, reason = classify_result(
        CheckResult(success=False, code=550, message="User unknown", email="x@y.com")
    )
    assert cat is ResultCategory.REJECTED
    assert status is None
    assert reason is None

    cat, status, reason = classify_result(
        CheckResult(success=False, code=0, message="Network timeout", email="x@y.com")
    )
    assert cat is ResultCategory.UNVERIFIABLE
    assert status is None
    assert "timeout" in (reason or "")

    cat, status, reason = classify_result(
        CheckResult(success=True, code=250, message="OK", email="x@y.com"),
        unverifiable_reason="Domain configured as catch-all",
    )
    assert cat is ResultCategory.UNVERIFIABLE
    assert status is None
    assert reason == "Domain configured as catch-all"


def test_check_email_invalid_format():
    r = check_email("")
    assert r.success is False
    assert r.code == 0
    assert "Invalid" in r.message

    r = check_email("no-at-sign")
    assert r.success is False
    assert r.code == 0


def test_check_email_invalid_domain():
    r = check_email("user@")
    assert r.success is False
    assert r.code == 0


@pytest.mark.skipif(
    __import__("mailseeker.smtp_check", fromlist=["dns"]).dns is None,
    reason="dnspython not installed",
)
@patch("mailseeker.smtp_check.dns.resolver.resolve")
def test_get_mx_hosts_sorted_by_preference(mock_resolve):
    class R:
        def __init__(self, pref, exchange):
            self.preference = pref
            self.exchange = exchange

    mock_resolve.return_value = [R(10, "b.example.com."), R(5, "a.example.com.")]
    hosts = get_mx_hosts("example.com")
    assert hosts == [(5, "a.example.com"), (10, "b.example.com")]


@patch("mailseeker.smtp_check.get_mx_hosts")
@patch("mailseeker.smtp_check.smtplib.SMTP")
def test_check_email_accepts(mock_smtp_class, mock_mx):
    mock_mx.return_value = [(5, "mail.example.com")]
    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)
    mock_smtp.rcpt.return_value = (250, "OK")
    mock_smtp_class.return_value = mock_smtp

    r = check_email("user@example.com")
    assert r.success is True
    assert r.code == 250
    assert "OK" in r.message
    mock_smtp.mail.assert_called_once()
    mock_smtp.rcpt.assert_called_once_with("user@example.com")


@patch("mailseeker.smtp_check.get_mx_hosts")
@patch("mailseeker.smtp_check.smtplib.SMTP")
def test_check_email_rejected(mock_smtp_class, mock_mx):
    import smtplib
    mock_mx.return_value = [(5, "mail.example.com")]
    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)
    mock_smtp.rcpt.side_effect = smtplib.SMTPRecipientsRefused(
        {"user@example.com": (550, b"User unknown")}
    )
    mock_smtp_class.return_value = mock_smtp

    r = check_email("user@example.com")
    assert r.success is False
    assert r.code == 550
    assert "User unknown" in r.message


@patch("mailseeker.smtp_check.get_mx_hosts")
@patch("mailseeker.smtp_check.smtplib.SMTP")
def test_check_email_fails_over_to_next_mx(mock_smtp_class, mock_mx):
    mock_mx.return_value = [(5, "mx1.example.com"), (10, "mx2.example.com")]

    smtp1 = MagicMock()
    smtp1.__enter__ = MagicMock(return_value=smtp1)
    smtp1.__exit__ = MagicMock(return_value=False)
    smtp1.connect.side_effect = TimeoutError("timed out")

    smtp2 = MagicMock()
    smtp2.__enter__ = MagicMock(return_value=smtp2)
    smtp2.__exit__ = MagicMock(return_value=False)
    smtp2.rcpt.return_value = (250, "OK")

    mock_smtp_class.side_effect = [smtp1, smtp2]

    r = check_email("user@example.com", retries=0)
    assert r.success is True
    assert r.code == 250
    smtp1.connect.assert_called_once_with("mx1.example.com", 25)
    smtp2.connect.assert_called_once_with("mx2.example.com", 25)


@patch("mailseeker.smtp_check.time.sleep")
@patch("mailseeker.smtp_check.get_mx_hosts")
@patch("mailseeker.smtp_check.smtplib.SMTP")
def test_check_email_retries_with_delay_and_backoff(mock_smtp_class, mock_mx, mock_sleep):
    mock_mx.return_value = [(5, "mx.example.com")]

    smtp1 = MagicMock()
    smtp1.__enter__ = MagicMock(return_value=smtp1)
    smtp1.__exit__ = MagicMock(return_value=False)
    smtp1.connect.side_effect = ConnectionRefusedError("refused")

    smtp2 = MagicMock()
    smtp2.__enter__ = MagicMock(return_value=smtp2)
    smtp2.__exit__ = MagicMock(return_value=False)
    smtp2.rcpt.return_value = (250, "OK")

    mock_smtp_class.side_effect = [smtp1, smtp2]

    r = check_email(
        "user@example.com",
        retries=1,
        retry_delay=0.5,
        retry_backoff=2.0,
    )
    assert r.success is True
    mock_sleep.assert_called_once_with(0.5)


@patch("mailseeker.smtp_check.diagnose_network_block")
@patch("mailseeker.smtp_check.get_mx_hosts")
@patch("mailseeker.smtp_check.smtplib.SMTP")
def test_check_email_runs_diagnosis_on_full_network_fail(mock_smtp_class, mock_mx, mock_diagnose):
    mock_mx.return_value = [(5, "mx1.example.com")]
    mock_diagnose.return_value = "Diagnosis: Blocked"

    smtp1 = MagicMock()
    smtp1.__enter__ = MagicMock(return_value=smtp1)
    smtp1.__exit__ = MagicMock(return_value=False)
    # Simulate timeout on all attempts (retries default to 1, so 2 attempts)
    smtp1.connect.side_effect = TimeoutError("timed out")
    
    mock_smtp_class.return_value = smtp1

    r = check_email("user@example.com")
    
    assert r.success is False
    assert "Network timeout" in r.message
    assert "Diagnosis: Blocked" in r.message
    mock_diagnose.assert_called_once_with("mx1.example.com", proxy_url=None)
