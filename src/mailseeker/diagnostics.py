"""Network diagnostics for SMTP connectivity issues."""

import socket
import sys
from typing import Callable, Optional

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
) -> tuple[bool, Optional[str]]:
    """Return (success, error_detail) for a TCP connection to host:port."""
    try:
        with create_connection(host, port, timeout=timeout, proxy_url=proxy_url):
            return True, None
    except Exception as exc:
        return False, str(exc)


def _check_port_bool(
    host: str,
    port: int,
    timeout: float = 3.0,
    proxy_url: Optional[str] = None,
) -> bool:
    """Legacy bool-only wrapper for check_port."""
    ok, _ = check_port(host, port, timeout=timeout, proxy_url=proxy_url)
    return ok


def diagnose_network_block(
    target_mx: str,
    proxy_url: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Run a series of connectivity checks to determine why SMTP might be failing.
    Returns a human-readable diagnosis string.
    When *log* is provided, each step is reported in real time.
    """
    if log is None:
        log = lambda msg: None  # noqa: E731

    via = f" (via proxy {proxy_url})" if proxy_url else ""

    # 0. If a proxy is configured, verify the proxy itself is reachable first.
    if proxy_url:
        log(f"[1/4] Checking proxy reachability...")
        reachable, detail = _check_proxy_reachable(proxy_url, timeout=3.0)
        if reachable:
            log(f"  OK  Proxy is reachable")
        else:
            log(f"  FAIL  {detail}")
            return (
                f"Diagnosis: SOCKS5 proxy is not reachable.\n"
                f"  - {detail}\n"
                f"  - Verify the proxy is running and the address is correct.\n"
                f"  - Mullvad's SOCKS5 proxy is typically at 10.64.0.1:1080 (not 127.0.0.1)."
            )

    inet_timeout = 5.0 if proxy_url else 2.0
    step = 2 if proxy_url else 1
    total = 4 if proxy_url else 3

    # 1. Check basic internet connectivity.
    log(f"[{step}/{total}] Checking internet connectivity{via}...")
    dns_ok, dns_err = check_port("8.8.8.8", 53, timeout=inet_timeout, proxy_url=proxy_url)
    log(f"  {'OK' if dns_ok else 'FAIL'}  8.8.8.8:53 (Google DNS){'' if dns_ok else f' — {dns_err}'}")

    http_ok, http_err = None, None
    if not dns_ok:
        http_ok, http_err = check_port("google.com", 80, timeout=inet_timeout, proxy_url=proxy_url)
        log(f"  {'OK' if http_ok else 'FAIL'}  google.com:80 (HTTP){'' if http_ok else f' — {http_err}'}")

    if not dns_ok and not http_ok:
        if proxy_url:
            return (
                "Diagnosis: Proxy is reachable but cannot connect to the internet through it.\n"
                "  - The SOCKS5 handshake may be failing (auth required? wrong protocol?).\n"
                "  - Verify the proxy works: curl --proxy socks5h://host:port http://example.com"
            )
        return "Diagnosis: No internet connection detected. Please check your network."

    step += 1
    check_timeout = 5.0 if proxy_url else 3.0

    # 2. Check target MX on port 587.
    log(f"[{step}/{total}] Checking target MX {target_mx}...")
    t25_ok, t25_err = check_port(target_mx, 25, timeout=check_timeout, proxy_url=proxy_url)
    log(f"  {'OK' if t25_ok else 'FAIL'}  {target_mx}:25{'' if t25_ok else f' — {t25_err}'}")
    t587_ok, t587_err = check_port(target_mx, 587, timeout=check_timeout, proxy_url=proxy_url)
    log(f"  {'OK' if t587_ok else 'FAIL'}  {target_mx}:587{'' if t587_ok else f' — {t587_err}'}")

    step += 1

    # 3. Check control MXs on port 25.
    control_mxs = [
        "gmail-smtp-in.l.google.com",
        "mta5.am0.yahoodns.net",
        "example-com.mail.protection.outlook.com",
    ]
    control_mxs = [mx for mx in control_mxs if mx != target_mx]

    log(f"[{step}/{total}] Checking control MX servers on port 25...")
    blocked_count = 0
    reachable_control = None

    for mx in control_mxs:
        ok, err = check_port(mx, 25, timeout=check_timeout, proxy_url=proxy_url)
        log(f"  {'OK' if ok else 'FAIL'}  {mx}:25{'' if ok else f' — {err}'}")
        if ok:
            reachable_control = mx
            break
        blocked_count += 1

    # Interpretation
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

    if t25_ok:
        return f"Diagnosis: All checks passed. {target_mx}:25 is reachable."

    if t587_ok:
        return (
            f"Diagnosis: {target_mx} is reachable on port 587 but timing out on port 25.\n"
            "  - The destination server may be firewalled or blocking your IP explicitly.\n"
            "  - Your general Port 25 connectivity seems OK (reached other MXs)."
        )

    return (
        f"Diagnosis: Unable to reach {target_mx} on port 25 or 587.\n"
        "  - The server may be down, or you are being blocked specifically."
    )
