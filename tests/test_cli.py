"""Tests for CLI argument parsing."""

import io
from unittest.mock import patch

from mailseeker.cli import _cmd_discover, _cmd_validate, _cmd_diagnose
from mailseeker.smtp_check import CheckResult


def test_validate_cmd_exits_nonzero_on_rejection():
    with patch("mailseeker.cli.check_email") as mock_check:
        mock_check.return_value = CheckResult(
            success=False, code=550, message="User unknown", email="x@y.com"
        )
        args = type(
            "A",
            (),
            {
                "email": "x@y.com",
                "timeout": 10.0,
                "mail_from": "",
                "retries": 1,
                "retry_delay": 0.1,
                "retry_backoff": 2.0,
                "verbose": False,
            },
        )()
        assert _cmd_validate(args) == 1


def test_validate_cmd_returns_zero_on_accept():
    with patch("mailseeker.cli.check_email") as mock_check:
        mock_check.return_value = CheckResult(
            success=True, code=250, message="OK", email="x@y.com"
        )
        args = type(
            "A",
            (),
            {
                "email": "x@y.com",
                "timeout": 10.0,
                "mail_from": "",
                "retries": 1,
                "retry_delay": 0.1,
                "retry_backoff": 2.0,
                "verbose": False,
            },
        )()
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            assert _cmd_validate(args) == 0
        out = stdout.getvalue()
        assert "Category: Accepted" in out
        assert "Status: Valid" in out


def test_discover_cmd_returns_zero_when_found():
    with patch("mailseeker.cli.discover") as mock_discover:
        mock_discover.return_value = [
            CheckResult(
                success=True,
                code=250,
                message="OK",
                email="jane.doe@example.com",
            )
        ]
        args = type(
            "A",
            (),
            {
                "first": "Jane",
                "last": "Doe",
                "domain": "example.com",
                "stop_first": True,
                "delay": 0,
                "timeout": 10.0,
                "mail_from": "",
                "retries": 1,
                "retry_delay": 0.1,
                "retry_backoff": 2.0,
                "verbose": False,
            },
        )()
        assert _cmd_discover(args) == 0


def test_discover_cmd_returns_one_when_none_found():
    with patch("mailseeker.cli.discover") as mock_discover:
        mock_discover.return_value = []
        args = type(
            "A",
            (),
            {
                "first": "Jane",
                "last": "Doe",
                "domain": "example.com",
                "stop_first": True,
                "delay": 0,
                "timeout": 10.0,
                "mail_from": "",
                "retries": 1,
                "retry_delay": 0.1,
                "retry_backoff": 2.0,
                "verbose": False,
            },
        )()
        assert _cmd_discover(args) == 1


def test_discover_cmd_shows_catch_all_when_all_accepted():
    """When server accepts all candidates (catch-all), we show Unverifiable."""
    all_accepted = [
        CheckResult(success=True, code=250, message="OK", email=f"user{i}@example.com")
        for i in range(5)
    ]
    with patch("mailseeker.cli.discover") as mock_discover:
        mock_discover.return_value = all_accepted
        args = type(
            "A",
            (),
            {
                "first": "Jane",
                "last": "Doe",
                "domain": "example.com",
                "stop_first": False,
                "delay": 0,
                "timeout": 10.0,
                "mail_from": "",
                "retries": 0,
                "retry_delay": 0.0,
                "retry_backoff": 1.0,
                "verbose": True,
            },
        )()
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            assert _cmd_discover(args) == 0
        out = stderr.getvalue()
        assert "catch-all" in out
        assert "Unverifiable" in out
        assert "Best guess (Unverifiable" in out
        # Accepted (Valid) should be empty (no "#1" under that section)
        assert "Accepted (Valid)" in out
        assert "Accepted (Limited)" in out
        assert "Rejected" in out


def test_diagnose_cmd_runs():
    from unittest.mock import ANY
    with patch("mailseeker.cli.diagnose_network_block") as mock_diag:
        mock_diag.return_value = "Everything OK"
        args = type("A", (), {"target": "mx.example.com"})()
        _cmd_diagnose(args)
        mock_diag.assert_called_once_with("mx.example.com", proxy_url=None, log=ANY)


def test_diagnose_cmd_passes_proxy():
    from unittest.mock import ANY
    with patch("mailseeker.cli.diagnose_network_block") as mock_diag:
        mock_diag.return_value = "OK"
        args = type("A", (), {"target": "gmail-smtp-in.l.google.com", "proxy": "socks5h://127.0.0.1:1080"})()
        _cmd_diagnose(args)
        mock_diag.assert_called_once_with("gmail-smtp-in.l.google.com", proxy_url="socks5h://127.0.0.1:1080", log=ANY)
