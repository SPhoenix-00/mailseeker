"""Tests for proxy module (create_connection with optional SOCKS5)."""

from unittest.mock import MagicMock, patch

import pytest

from mailseeker.proxy import create_connection, parse_proxy_url


# --- parse_proxy_url ---

def test_parse_proxy_url_socks5h():
    rdns, host, port = parse_proxy_url("socks5h://127.0.0.1:1080")
    assert rdns is True
    assert host == "127.0.0.1"
    assert port == 1080


def test_parse_proxy_url_socks5():
    rdns, host, port = parse_proxy_url("socks5://10.64.0.1:9050")
    assert rdns is False
    assert host == "10.64.0.1"
    assert port == 9050


def test_parse_proxy_url_unsupported_scheme():
    with pytest.raises(ValueError, match="socks5"):
        parse_proxy_url("http://127.0.0.1:8080")


def test_parse_proxy_url_missing_port():
    with pytest.raises(ValueError, match="host and port"):
        parse_proxy_url("socks5://127.0.0.1")


def test_parse_proxy_url_bad_port():
    with pytest.raises(ValueError, match="Invalid proxy port"):
        parse_proxy_url("socks5://127.0.0.1:abc")


# --- create_connection (no proxy) ---

def test_create_connection_no_proxy_uses_stdlib():
    """Without proxy_url, create_connection uses socket.create_connection (no PySocks)."""
    fake_sock = MagicMock()
    with patch("mailseeker.proxy.socket") as m_socket:
        m_socket.create_connection.return_value = fake_sock
        result = create_connection("mx.example.com", 25, timeout=5.0, proxy_url=None)
        m_socket.create_connection.assert_called_once_with(("mx.example.com", 25), timeout=5.0)
        assert result is fake_sock


def test_create_connection_empty_proxy_uses_direct():
    """Empty or whitespace proxy_url is treated as no proxy."""
    fake_sock = MagicMock()
    with patch("mailseeker.proxy.socket") as m_socket:
        m_socket.create_connection.return_value = fake_sock
        create_connection("mx.example.com", 25, timeout=1.0, proxy_url="")
        create_connection("mx.example.com", 25, timeout=1.0, proxy_url="   ")
        assert m_socket.create_connection.call_count == 2


# --- create_connection (with proxy) ---

def test_create_connection_passes_rdns_true():
    """socks5h:// sets rdns=True on set_proxy."""
    mock_socks = MagicMock()
    mock_sock_instance = MagicMock()
    mock_socks.socksocket.return_value = mock_sock_instance
    mock_socks.SOCKS5 = 2

    with patch.dict("sys.modules", {"socks": mock_socks}):
        result = create_connection("mx.example.com", 25, timeout=5.0, proxy_url="socks5h://127.0.0.1:1080")

    mock_sock_instance.set_proxy.assert_called_once_with(2, "127.0.0.1", 1080, rdns=True)
    mock_sock_instance.connect.assert_called_once_with(("mx.example.com", 25))
    assert result is mock_sock_instance


def test_create_connection_passes_rdns_false():
    """socks5:// sets rdns=False on set_proxy."""
    mock_socks = MagicMock()
    mock_sock_instance = MagicMock()
    mock_socks.socksocket.return_value = mock_sock_instance
    mock_socks.SOCKS5 = 2

    with patch.dict("sys.modules", {"socks": mock_socks}):
        result = create_connection("mx.example.com", 25, timeout=5.0, proxy_url="socks5://127.0.0.1:1080")

    mock_sock_instance.set_proxy.assert_called_once_with(2, "127.0.0.1", 1080, rdns=False)


def test_create_connection_closes_socket_on_connect_failure():
    """Socket is closed if connect() raises."""
    mock_socks = MagicMock()
    mock_sock_instance = MagicMock()
    mock_socks.socksocket.return_value = mock_sock_instance
    mock_socks.SOCKS5 = 2
    mock_sock_instance.connect.side_effect = OSError("connection refused")

    with patch.dict("sys.modules", {"socks": mock_socks}):
        with pytest.raises(OSError):
            create_connection("mx.example.com", 25, timeout=5.0, proxy_url="socks5h://127.0.0.1:1080")

    mock_sock_instance.close.assert_called_once()


def test_create_connection_unsupported_scheme_raises():
    """Unsupported proxy scheme raises ValueError."""
    with pytest.raises(ValueError) as exc_info:
        create_connection("example.com", 25, timeout=1.0, proxy_url="http://127.0.0.1:8080")
    assert "socks5" in str(exc_info.value).lower()
