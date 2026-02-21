"""Tests for discovery pattern generation."""

from unittest.mock import patch

import pytest

from mailseeker.discovery import discover, email_candidates
from mailseeker.smtp_check import CheckResult


def test_email_candidates_order_and_content():
    candidates = email_candidates("Jane", "Doe", "example.com")
    assert candidates[0] == "jane.doe@example.com"
    assert "janedoe@example.com" in candidates
    assert "jane_doe@example.com" in candidates
    assert "jane-doe@example.com" in candidates
    assert "jane.d@example.com" in candidates
    assert "j.doe@example.com" in candidates
    assert "janed@example.com" in candidates
    assert "jdoe@example.com" in candidates
    assert "jane@example.com" in candidates
    assert "doe@example.com" in candidates
    assert "doe.jane@example.com" in candidates


def test_email_candidates_normalized_lowercase():
    candidates = email_candidates("John", "Smith", "COMPANY.ORG")
    assert all("@" in e and e.endswith("@company.org") for e in candidates)
    assert "john.smith@company.org" in candidates


def test_email_candidates_no_duplicates():
    candidates = email_candidates("A", "A", "x.com")
    assert len(candidates) == len(set(candidates))


def test_email_candidates_empty_domain_returns_empty():
    assert email_candidates("Jane", "Doe", "") == []
    assert email_candidates("Jane", "Doe", "   ") == []


def test_email_candidates_strips_whitespace():
    candidates = email_candidates("  Jane  ", "  Doe  ", "  example.com  ")
    assert "jane.doe@example.com" in candidates


@patch("mailseeker.discovery.check_email")
def test_discover_passes_retry_settings(mock_check):
    mock_check.return_value = CheckResult(
        success=True,
        code=250,
        message="OK",
        email="jane.doe@example.com",
    )

    discover(
        "Jane",
        "Doe",
        "example.com",
        stop_at_first=True,
        delay=0,
        timeout=5.0,
        mail_from="sender@example.com",
        retries=2,
        retry_delay=0.25,
        retry_backoff=1.5,
        verbose=False,
    )

    _, kwargs = mock_check.call_args
    assert kwargs["retries"] == 2
    assert kwargs["retry_delay"] == 0.25
    assert kwargs["retry_backoff"] == 1.5


@patch("mailseeker.discovery.check_email")
def test_discover_returns_all_results_when_trying_all(mock_check):
    """When stop_at_first=False, discover returns a result for every candidate tried."""
    candidates = email_candidates("A", "B", "x.com")
    # First succeeds, rest rejected
    def side_effect(email, **kwargs):
        return CheckResult(
            success=(email == candidates[0]),
            code=250 if email == candidates[0] else 550,
            message="OK" if email == candidates[0] else "User unknown",
            email=email,
        )
    mock_check.side_effect = side_effect

    results = discover("A", "B", "x.com", stop_at_first=False, verbose=False)

    assert len(results) == len(candidates)
    assert results[0].success is True
    assert all(not r.success for r in results[1:])
