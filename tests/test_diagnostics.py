"""Tests for network diagnostics."""

from unittest.mock import patch
from mailseeker.diagnostics import diagnose_network_block, _check_proxy_reachable


@patch("mailseeker.diagnostics.check_port")
def test_diagnose_internet_down(mock_check_port):
    mock_check_port.return_value = (False, "timed out")

    msg = diagnose_network_block("mx.example.com")
    assert "No internet connection detected" in msg


@patch("mailseeker.diagnostics.check_port")
def test_diagnose_port_25_blocked(mock_check_port):
    def side_effect(host, port, timeout=3.0, proxy_url=None):
        if host in ("8.8.8.8", "google.com"):
            return (True, None)
        if port == 25:
            return (False, "timed out")
        return (False, "timed out")

    mock_check_port.side_effect = side_effect

    msg = diagnose_network_block("mx.example.com")
    assert "Outbound Port 25 appears to be blocked" in msg
    assert "Use a VPN, a proxy" in msg


@patch("mailseeker.diagnostics.check_port")
def test_diagnose_host_specific_block(mock_check_port):
    def side_effect(host, port, timeout=3.0, proxy_url=None):
        if host == "mx.example.com" and port == 25:
            return (False, "timed out")
        return (True, None)

    mock_check_port.side_effect = side_effect

    msg = diagnose_network_block("mx.example.com")
    assert "reachable on port 587 but timing out on port 25" in msg


# --- Proxy-specific diagnostics ---

@patch("mailseeker.diagnostics.socket.create_connection")
def test_diagnose_proxy_unreachable(mock_create_conn):
    """When the proxy itself isn't reachable, report that clearly."""
    mock_create_conn.side_effect = OSError("Connection refused")

    msg = diagnose_network_block(
        "mx.example.com", proxy_url="socks5h://127.0.0.1:1080"
    )
    assert "proxy is not reachable" in msg.lower()
    assert "127.0.0.1:1080" in msg


@patch("mailseeker.diagnostics.check_port")
@patch("mailseeker.diagnostics._check_proxy_reachable", return_value=(True, "ok"))
def test_diagnose_proxy_reachable_but_no_internet(mock_proxy_check, mock_check_port):
    """Proxy is reachable but SOCKS5 connections through it fail."""
    mock_check_port.return_value = (False, "timed out")

    msg = diagnose_network_block(
        "mx.example.com", proxy_url="socks5h://127.0.0.1:1080"
    )
    assert "proxy is reachable but cannot connect" in msg.lower()


@patch("mailseeker.diagnostics.check_port")
@patch("mailseeker.diagnostics._check_proxy_reachable", return_value=(True, "ok"))
def test_diagnose_proxy_port25_blocked(mock_proxy_check, mock_check_port):
    """Proxy is reachable but port 25 blocked — message mentions the proxy provider."""
    def side_effect(host, port, timeout=3.0, proxy_url=None):
        if host in ("8.8.8.8", "google.com"):
            return (True, None)
        if port == 25:
            return (False, "timed out")
        return (False, "timed out")

    mock_check_port.side_effect = side_effect

    msg = diagnose_network_block(
        "mx.example.com", proxy_url="socks5h://127.0.0.1:1080"
    )
    assert "blocked even through your proxy" in msg.lower()
    assert "ssh" in msg.lower()


@patch("mailseeker.diagnostics.socket.create_connection")
def test_check_proxy_reachable_success(mock_conn):
    mock_conn.return_value.__enter__ = lambda s: s
    mock_conn.return_value.__exit__ = lambda s, *a: None
    ok, detail = _check_proxy_reachable("socks5h://127.0.0.1:1080")
    assert ok is True


@patch("mailseeker.diagnostics.socket.create_connection")
def test_check_proxy_reachable_failure(mock_conn):
    mock_conn.side_effect = OSError("refused")
    ok, detail = _check_proxy_reachable("socks5h://127.0.0.1:1080")
    assert ok is False
    assert "127.0.0.1:1080" in detail
