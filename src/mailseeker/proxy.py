"""Optional SOCKS5 proxy support for SMTP and diagnostics (e.g. Mullvad)."""

import socket
from typing import Optional


def parse_proxy_url(proxy_url: str) -> tuple[bool, str, int]:
    """Parse a socks5[h]:// URL into (rdns, host, port)."""
    url = proxy_url.strip()
    if url.startswith("socks5h://"):
        rdns = True
        url = url[10:]
    elif url.startswith("socks5://"):
        rdns = False
        url = url[9:]
    else:
        raise ValueError(
            "Unsupported proxy URL scheme. Use socks5:// or socks5h:// "
            "(e.g. socks5h://127.0.0.1:1080)"
        )

    url = url.split("/")[0]
    if ":" not in url:
        raise ValueError(
            f"Proxy URL must include host and port "
            f"(e.g. socks5://127.0.0.1:1080): {proxy_url}"
        )

    host, _, port_str = url.rpartition(":")
    try:
        port = int(port_str)
    except ValueError:
        raise ValueError(f"Invalid proxy port in URL: {proxy_url}") from None

    return rdns, host, port


def create_connection(
    host: str,
    port: int,
    timeout: float = 10.0,
    proxy_url: Optional[str] = None,
) -> socket.socket:
    """
    Create a TCP connection to (host, port). If proxy_url is set (e.g. socks5://127.0.0.1:1080),
    route the connection through that SOCKS5 proxy (requires PySocks).
    Use socks5h:// to resolve hostnames on the proxy side (recommended for privacy).
    """
    if not proxy_url or not proxy_url.strip():
        return socket.create_connection((host, port), timeout=timeout)

    rdns, proxy_host, proxy_port = parse_proxy_url(proxy_url)

    try:
        import socks
    except ImportError:
        raise RuntimeError(
            "Proxy support requires PySocks. Install with: "
            "pip install mailseeker[proxy] or pip install PySocks"
        ) from None

    sock = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.set_proxy(socks.SOCKS5, proxy_host, proxy_port, rdns=rdns)
    try:
        sock.connect((host, port))
    except Exception:
        sock.close()
        raise
    return sock
