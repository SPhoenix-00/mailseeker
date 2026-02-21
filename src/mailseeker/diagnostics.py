"""Network diagnostics for SMTP connectivity issues."""

import socket
from typing import Optional

from .proxy import create_connection, parse_proxy_url


def _check_proxy_reachable(proxy_url: str, timeout: float = 3.0) -> tuple[bool, str]:
    """Raw TCP connect to the proxy host:port (no SOCKS5 handshake).

    Returns (reachable, detail_message).
    """
    try:
        _, proxy_host, proxy_port = parse_proxy_url(proxy_url)
    except ValueError as exc:
        return False, f"Invalid proxy URL: {exc}"

    try:
        with socket.create_connection((proxy_host, proxy_port), timeout=timeout):
            return True, "Proxy is listening"
    except OSError as exc:
        return False, f"Cannot reach proxy at {proxy_host}:{proxy_port} ({exc})"


def check_port(
    host: str,
    port: int,
    timeout: float = 3.0,
    proxy_url: Optional[str] = None,
) -> bool:
    """Return True if TCP connection to host:port succeeds (optionally via proxy)."""
    try:
        with create_connection(host, port, timeout=timeout, proxy_url=proxy_url):
            return True
    except Exception:
        return False


def diagnose_network_block(
    target_mx: str,
    proxy_url: Optional[str] = None,
) -> str:
    """
    Run a series of connectivity checks to determine why SMTP might be failing.
    Returns a human-readable diagnosis string.
    """
    # 0. If a proxy is configured, verify the proxy itself is reachable first.
    if proxy_url:
        reachable, detail = _check_proxy_reachable(proxy_url, timeout=3.0)
        if not reachable:
            return (
                f"Diagnosis: SOCKS5 proxy is not reachable.\n"
                f"  - {detail}\n"
                f"  - Verify the proxy is running and the address is correct.\n"
                f"  - Mullvad's SOCKS5 proxy is typically at 10.64.0.1:1080 (not 127.0.0.1)."
            )

    inet_timeout = 5.0 if proxy_url else 2.0

    # 1. Check basic internet connectivity (via Google DNS or similar stable host).
    if not check_port("8.8.8.8", 53, timeout=inet_timeout, proxy_url=proxy_url) and not check_port(
        "google.com", 80, timeout=inet_timeout, proxy_url=proxy_url
    ):
        if proxy_url:
            return (
                "Diagnosis: Proxy is reachable but cannot connect to the internet through it.\n"
                "  - The SOCKS5 handshake may be failing (auth required? wrong protocol?).\n"
                "  - Verify the proxy works: curl --proxy socks5h://host:port http://example.com"
            )
        return "Diagnosis: No internet connection detected. Please check your network."

    # 2. Check if the target MX is reachable on port 587 (submission).
    check_timeout = 5.0 if proxy_url else 3.0
    target_587_open = check_port(target_mx, 587, timeout=check_timeout, proxy_url=proxy_url)

    # 3. Check if *any* major MX is reachable on port 25.
    control_mxs = [
        "gmail-smtp-in.l.google.com",
        "mta5.am0.yahoodns.net",
        "example-com.mail.protection.outlook.com",
    ]
    control_mxs = [mx for mx in control_mxs if mx != target_mx]

    blocked_count = 0
    reachable_control = None

    for mx in control_mxs:
        if check_port(mx, 25, timeout=check_timeout, proxy_url=proxy_url):
            reachable_control = mx
            break
        blocked_count += 1

    if blocked_count == len(control_mxs):
        if proxy_url:
            return (
                "Diagnosis: Outbound Port 25 is blocked even through your proxy/VPN.\n"
                "  - Your proxy provider (e.g. Mullvad) likely blocks port 25 to prevent spam.\n"
                "  - Workaround: Use an SSH tunnel (ssh -D 1080 user@server) to a VPS that allows port 25,\n"
                "    then pass --proxy socks5h://127.0.0.1:1080."
            )
        return (
            "Diagnosis: Outbound Port 25 appears to be blocked by your ISP or Cloud Provider.\n"
            "  - This is common on residential networks and cloud VPS (AWS, GCP, Azure, etc).\n"
            "  - Workaround: Use a VPN, a proxy, or request your provider to unblock Port 25.\n"
            "  - Note: Port 587/465 cannot be used for MX validation (server-to-server) traffic."
        )

    if target_587_open:
        return (
            f"Diagnosis: {target_mx} is reachable on port 587 but timing out on port 25.\n"
            "  - The destination server may be firewalled or blocking your IP explicitly.\n"
            "  - Your general Port 25 connectivity seems OK (reached other MXs)."
        )

    return (
        f"Diagnosis: Unable to reach {target_mx} on port 25 or 587.\n"
        "  - The server may be down, or you are being blocked specifically."
    )
