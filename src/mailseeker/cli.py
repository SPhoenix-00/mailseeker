"""CLI entrypoint: validate and discover subcommands."""

import argparse
import os
import sys

from .discovery import discover, email_candidates
from .smtp_check import (
    AcceptedStatus,
    CheckResult,
    ResultCategory,
    check_email,
    classify_result,
    interpret_code,
)
from .diagnostics import diagnose_network_block

# Output formatting
_WIDTH = 60
_HR = "\u2500" * _WIDTH  # horizontal rule

# Catch-all: if server accepts this many candidates (or more) and all accepted, treat as inconclusive
_CATCH_ALL_MIN_CANDIDATES = 3


def _section(title: str) -> None:
    print(file=sys.stderr)
    print(f"  {title}", file=sys.stderr)
    print(f"  {_HR}", file=sys.stderr)


def _line(key: str, value: str, key_width: int = 12) -> None:
    print(f"  {key:<{key_width}}  {value}", file=sys.stderr)


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
    email = (args.email or "").strip().lower()
    if args.verbose:
        print(file=sys.stderr)
        print(f"  Validate  {email}", file=sys.stderr)
        print(f"  {_HR}", file=sys.stderr)
        print(file=sys.stderr)
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
    category, status, unverifiable_reason = classify_result(result)
    if args.verbose:
        _section("Result")
        _line("Email", result.email)
        _line("Category", category.value)
        if status is not None:
            _line("Status", status.value)
        if result.code:
            _line("Code", str(result.code))
            _line("Message", result.message or "—")
        if category is ResultCategory.REJECTED and result.code:
            interp = interpret_code(result.code)
            if interp:
                _line("Interpretation", interp)
        if category is ResultCategory.UNVERIFIABLE and unverifiable_reason:
            _line("Reason", unverifiable_reason)
        _section("Conclusion")
        if category is ResultCategory.ACCEPTED:
            if status is AcceptedStatus.LIMITED:
                print(
                    "  Accepted (Limited): address is valid but mailbox is temporarily"
                    " overloaded (storage or rate limit).",
                    file=sys.stderr,
                )
            else:
                print(
                    f"  Accepted (Valid): the address is valid (server replied {result.code}).",
                    file=sys.stderr,
                )
        elif category is ResultCategory.REJECTED:
            print(
                "  Rejected: the address does not exist or no mail server for the domain.",
                file=sys.stderr,
            )
        else:
            print(
                f"  Unverifiable: {unverifiable_reason or result.message}",
                file=sys.stderr,
            )
        print(file=sys.stderr)
    else:
        print(f"Email: {result.email}")
        print(f"Category: {category.value}")
        if status is not None:
            print(f"Status: {status.value}")
        print(f"Code: {result.code}")
        print(f"Message: {result.message}")
        if category is ResultCategory.REJECTED and result.code:
            interp = interpret_code(result.code)
            if interp:
                print(f"Interpretation: {interp}")
        if category is ResultCategory.UNVERIFIABLE and unverifiable_reason:
            print(f"Reason: {unverifiable_reason}")
    return 0 if category is ResultCategory.ACCEPTED else 1


def _cmd_discover(args: argparse.Namespace) -> int:
    candidates = email_candidates(args.first, args.last, args.domain)
    if args.verbose:
        print(file=sys.stderr)
        print(f"  Discover  {args.first} {args.last}  @  {args.domain}", file=sys.stderr)
        print(f"  {_HR}", file=sys.stderr)
        _line("Candidates", f"{len(candidates)} pattern(s)")
        print(file=sys.stderr)
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
    # Classify each result; catch-all overrides accepted → Unverifiable
    n_tried = len(results)
    n_total = len(candidates)
    possible_catch_all = (
        n_tried >= _CATCH_ALL_MIN_CANDIDATES
        and all(r.success for r in results)
        and n_tried > 0
    )
    accepted_valid: list[CheckResult] = []
    accepted_limited: list[CheckResult] = []
    rejected: list[CheckResult] = []
    unverifiable: list[tuple[CheckResult, str]] = []  # (result, reason)

    for r in results:
        if possible_catch_all and r.success:
            unverifiable.append((
                r,
                "Domain configured as catch-all; accepts all addresses (confidentiality risk).",
            ))
            continue
        cat, status, reason = classify_result(r)
        if cat is ResultCategory.ACCEPTED:
            if status is AcceptedStatus.LIMITED:
                accepted_limited.append(r)
            else:
                accepted_valid.append(r)
        elif cat is ResultCategory.REJECTED:
            rejected.append(r)
        else:
            unverifiable.append((r, reason or "Mail server did not respond"))

    n_acc_valid = len(accepted_valid)
    n_acc_limited = len(accepted_limited)
    n_rej = len(rejected)
    n_unv = len(unverifiable)
    accepted_any = accepted_valid or accepted_limited

    if args.verbose:
        _section("Accepted (Valid)")
        if accepted_valid:
            for i, r in enumerate(accepted_valid, 1):
                print(f"  #{i}  {r.email}  ({r.code} {r.message})", file=sys.stderr)
        else:
            print("  None.", file=sys.stderr)
        _section("Accepted (Limited)")
        if accepted_limited:
            print(
                "  Mailbox temporarily overloaded (storage or rate limit); address valid.",
                file=sys.stderr,
            )
            for i, r in enumerate(accepted_limited, 1):
                print(f"  #{i}  {r.email}  ({r.code} {r.message})", file=sys.stderr)
        else:
            print("  None.", file=sys.stderr)
        _section("Rejected")
        if rejected:
            for i, r in enumerate(rejected, 1):
                print(f"  #{i}  {r.email}  ({r.code} {r.message})", file=sys.stderr)
        else:
            print("  None.", file=sys.stderr)
        _section("Unverifiable")
        if unverifiable:
            if possible_catch_all:
                print(
                    "  Domain is catch-all; cannot determine which addresses exist.",
                    file=sys.stderr,
                )
            for i, (r, reason) in enumerate(unverifiable[:5], 1):
                print(f"  #{i}  {r.email}  — {reason}", file=sys.stderr)
            if len(unverifiable) > 5:
                print(f"  ... and {len(unverifiable) - 5} more.", file=sys.stderr)
        else:
            print("  None.", file=sys.stderr)
        _section("Conclusion")
        parts = []
        if n_acc_valid:
            parts.append(f"{n_acc_valid} accepted (Valid)")
        if n_acc_limited:
            parts.append(f"{n_acc_limited} accepted (Limited)")
        if n_rej:
            parts.append(f"{n_rej} rejected")
        if n_unv:
            parts.append(f"{n_unv} unverifiable")
        tried_label = f"{n_tried}/{n_total}" if n_tried < n_total else str(n_total)
        print(f"  {tried_label} tried: {', '.join(parts) or 'no outcome'}.", file=sys.stderr)
        if accepted_any:
            best = accepted_any[0].email
            if possible_catch_all:
                print(
                    "  Best guess (Unverifiable — domain may be catch-all): " + best,
                    file=sys.stderr,
                )
            else:
                print(f"  Best guess: {best}", file=sys.stderr)
        elif possible_catch_all and unverifiable:
            best = unverifiable[0][0].email
            print(
                "  Best guess (Unverifiable — domain may be catch-all): " + best,
                file=sys.stderr,
            )
        print(file=sys.stderr)
    else:
        if possible_catch_all:
            print(
                "Unverifiable: domain configured as catch-all; result inconclusive.",
                file=sys.stderr,
            )
            if unverifiable:
                r = unverifiable[0][0]
                print(f"{r.email}  (Unverifiable)")
        else:
            for r in accepted_valid:
                print(f"{r.email}  Accepted (Valid)  ({r.code} {r.message})")
            for r in accepted_limited:
                print(f"{r.email}  Accepted (Limited)  ({r.code} {r.message})")
    if not accepted_any and not (possible_catch_all and unverifiable):
        if not args.verbose:
            print("No accepted address found.", file=sys.stderr)
        return 1
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
        default=False,
        help="Stop at first accepted address",
    )
    p_discover.add_argument(
        "--all",
        dest="stop_first",
        action="store_false",
        help="Try all candidates and list every accepted (default)",
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
