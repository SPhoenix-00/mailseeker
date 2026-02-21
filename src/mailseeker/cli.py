"""CLI entrypoint: validate and discover subcommands."""

import argparse
import os
import sys

from .discovery import discover
from .smtp_check import check_email, interpret_code
from .diagnostics import diagnose_network_block


def _proxy_from_args(args: argparse.Namespace) -> str | None:
    """Proxy URL from --proxy or MAILSEEKER_PROXY env (e.g. socks5h://127.0.0.1:1080 for Mullvad)."""
    return getattr(args, "proxy", None) or os.environ.get("MAILSEEKER_PROXY") or None


def _cmd_diagnose(args: argparse.Namespace) -> int:
    proxy = _proxy_from_args(args)
    print(f"Running network diagnosis for target: {args.target}")
    if proxy:
        print(f"Proxy: {proxy}")
    print()
    diagnosis = diagnose_network_block(args.target, proxy_url=proxy, log=print)
    print()
    print(diagnosis)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    result = check_email(
        args.email,
        timeout=args.timeout,
        mail_from=args.mail_from or "",
        retries=args.retries,
        retry_delay=args.retry_delay,
        retry_backoff=args.retry_backoff,
        verbose=args.verbose,
        proxy_url=_proxy_from_args(args),
    )
    print(f"Email: {result.email}")
    print(f"Accepted: {result.success}")
    print(f"Code: {result.code}")
    print(f"Message: {result.message}")
    if result.code and not result.success:
        interp = interpret_code(result.code)
        if interp:
            print(f"Interpretation: {interp}")
    return 0 if result.success else 1


def _cmd_discover(args: argparse.Namespace) -> int:
    results = discover(
        args.first,
        args.last,
        args.domain,
        stop_at_first=args.stop_first,
        delay=args.delay,
        timeout=args.timeout,
        mail_from=args.mail_from or "",
        retries=args.retries,
        retry_delay=args.retry_delay,
        retry_backoff=args.retry_backoff,
        verbose=args.verbose,
        proxy_url=_proxy_from_args(args),
    )
    if not results:
        print("No accepted address found.", file=sys.stderr)
        return 1
    for r in results:
        print(f"{r.email}  ({r.code} {r.message})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mailseeker",
        description="Check email validity or discover address from first/last name and domain.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="SMTP connect/response timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--mail-from",
        type=str,
        default="",
        help="Envelope MAIL FROM address (default: empty)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=True,
        help="Print progress to stderr (default: on)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        dest="verbose",
        action="store_false",
        help="Suppress progress output",
    )
    parser.add_argument(
        "--proxy",
        type=str,
        default=None,
        metavar="URL",
        help="Route SMTP/diagnostics via SOCKS5 proxy (e.g. socks5h://127.0.0.1:1080). "
        "Also set via MAILSEEKER_PROXY. Use an SSH tunnel (ssh -D 1080 user@server) or similar for proxy-only; bypasses port 25 blocks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    p_validate = subparsers.add_parser("validate", help="Check one email address")
    p_validate.add_argument("email", help="Email address to check")
    p_validate.add_argument("--timeout", type=float, default=10.0, help="SMTP timeout in seconds (default: 10)")
    p_validate.add_argument("--mail-from", type=str, default="", help="Envelope MAIL FROM (default: empty)")
    p_validate.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retries per MX host after failure (default: 1, enabled automatically)",
    )
    p_validate.add_argument(
        "--retry-delay",
        type=float,
        default=0.5,
        help="Base delay between retries in seconds (default: 0.5)",
    )
    p_validate.add_argument(
        "--retry-backoff",
        type=float,
        default=2.0,
        help="Backoff multiplier for retry delay (default: 2.0)",
    )
    p_validate.add_argument("-v", "--verbose", action="store_true", default=True, help="Print progress (default: on)")
    p_validate.add_argument("-q", "--quiet", dest="verbose", action="store_false", help="Suppress progress output")
    p_validate.add_argument("--proxy", type=str, default=None, metavar="URL", help="SOCKS5 proxy URL (e.g. socks5h://127.0.0.1:1080)")
    p_validate.set_defaults(func=_cmd_validate)

    # discover
    p_discover = subparsers.add_parser(
        "discover",
        help="Find likely email from first name, last name, and domain",
    )
    p_discover.add_argument("--first", required=True, help="First name")
    p_discover.add_argument("--last", required=True, help="Last name")
    p_discover.add_argument("--domain", required=True, help="Domain (e.g. example.com)")
    p_discover.add_argument(
        "--stop-first",
        action="store_true",
        default=True,
        help="Stop at first accepted address (default)",
    )
    p_discover.add_argument(
        "--all",
        dest="stop_first",
        action="store_false",
        help="Try all candidates and list every accepted address",
    )
    p_discover.add_argument(
        "--delay",
        type=float,
        default=0,
        metavar="SECONDS",
        help="Delay between attempts in seconds (default: 0)",
    )
    p_discover.add_argument("--timeout", type=float, default=10.0, help="SMTP timeout in seconds (default: 10)")
    p_discover.add_argument("--mail-from", type=str, default="", help="Envelope MAIL FROM (default: empty)")
    p_discover.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retries per MX host after failure (default: 1, enabled automatically)",
    )
    p_discover.add_argument(
        "--retry-delay",
        type=float,
        default=0.5,
        help="Base delay between retries in seconds (default: 0.5)",
    )
    p_discover.add_argument(
        "--retry-backoff",
        type=float,
        default=2.0,
        help="Backoff multiplier for retry delay (default: 2.0)",
    )
    p_discover.add_argument("-v", "--verbose", action="store_true", default=True, help="Print progress (default: on)")
    p_discover.add_argument("-q", "--quiet", dest="verbose", action="store_false", help="Suppress progress output")
    p_discover.add_argument("--proxy", type=str, default=None, metavar="URL", help="SOCKS5 proxy URL (e.g. socks5h://127.0.0.1:1080)")
    p_discover.set_defaults(func=_cmd_discover)

    # diagnose
    p_diagnose = subparsers.add_parser(
        "diagnose", help="Run standalone network diagnostics"
    )
    p_diagnose.add_argument(
        "target",
        nargs="?",
        default="gmail-smtp-in.l.google.com",
        help="Target MX host to check (default: Gmail MX)",
    )
    p_diagnose.add_argument("--proxy", type=str, default=None, metavar="URL", help="SOCKS5 proxy URL (e.g. socks5h://127.0.0.1:1080)")
    p_diagnose.set_defaults(func=_cmd_diagnose)

    args = parser.parse_args()
    exit_code = args.func(args)
    sys.exit(exit_code)
