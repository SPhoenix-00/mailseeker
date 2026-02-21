"""MX resolution and SMTP RCPT TO check; returns server response (code + message)."""

import sys
import smtplib
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .diagnostics import diagnose_network_block
from .proxy import create_connection


_LOG_INDENT = "  "


def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(f"{_LOG_INDENT}{msg}", file=sys.stderr)


def _classify_network_error(err: BaseException) -> str:
    """Return a short, stable category for common network failures."""
    text = str(err).lower()
    if isinstance(err, TimeoutError) or "timed out" in text or "winerror 10060" in text:
        return "Network timeout"
    if isinstance(err, ConnectionRefusedError) or "refused" in text or "winerror 10061" in text:
        return "Connection refused"
    if isinstance(err, ConnectionResetError) or "reset" in text or "winerror 10054" in text:
        return "Connection reset"
    if "unreachable" in text or "winerror 10051" in text or "winerror 10065" in text:
        return "Network unreachable"
    return "Network error"

try:
    import dns.resolver
except ImportError:
    dns = None  # type: ignore[assignment]


class ResultCategory(str, Enum):
    """High-level result: Accepted, Rejected, or Unverifiable."""

    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    UNVERIFIABLE = "Unverifiable"


class AcceptedStatus(str, Enum):
    """When category is Accepted: Valid (normal) or Limited (mailbox overloaded)."""

    VALID = "Valid"
    LIMITED = "Limited"


@dataclass
class CheckResult:
    """Result of an SMTP recipient check."""

    success: bool
    code: int
    message: str
    email: str


# SMTP codes that mean "accepted, valid"
_ACCEPTED_VALID_CODES = (250, 251, 252)
# SMTP codes that mean "accepted but limited" (mailbox full / overloaded / storage)
_ACCEPTED_LIMITED_CODES = (450, 451, 452, 552)
# SMTP codes that mean "rejected" (address does not exist or not allowed)
_REJECTED_CODES = (550, 551, 553, 554)

# Common SMTP response code interpretations (short human-readable).
CODE_INTERPRETATIONS = {
    550: "User unknown or mailbox unavailable",
    551: "User not local; please try forwarding path",
    552: "Mailbox full or storage allocation exceeded",
    553: "Mailbox name invalid or not allowed",
    554: "Transaction failed / policy rejection",
}


def classify_result(
    result: CheckResult,
    *,
    unverifiable_reason: Optional[str] = None,
) -> tuple[ResultCategory, Optional[AcceptedStatus], Optional[str]]:
    """
    Classify a check result into category (Accepted / Rejected / Unverifiable),
    optional accepted status (Valid / Limited), and optional reason (for Unverifiable).

    Unverifiable covers: no SMTP response (timeout, connection error), catch-all,
    or server issues (e.g. anti-spam blocking verification).
    """
    if unverifiable_reason:
        return (ResultCategory.UNVERIFIABLE, None, unverifiable_reason)
    code = result.code
    if code in _ACCEPTED_VALID_CODES:
        return (ResultCategory.ACCEPTED, AcceptedStatus.VALID, None)
    if code in _ACCEPTED_LIMITED_CODES:
        return (ResultCategory.ACCEPTED, AcceptedStatus.LIMITED, None)
    if code in _REJECTED_CODES:
        return (ResultCategory.REJECTED, None, None)
    if code == 0:
        # No SMTP response: timeout, connection error, no MX, etc.
        reason = result.message or "Mail server did not respond"
        return (ResultCategory.UNVERIFIABLE, None, reason)
    # Other 4xx: transient (e.g. anti-spam)
    if 400 <= code < 500:
        return (
            ResultCategory.UNVERIFIABLE,
            None,
            result.message or f"Server returned {code} (transient)",
        )
    # Other 5xx: permanent failure → Rejected
    return (ResultCategory.REJECTED, None, None)


def get_mx_hosts(
    domain: str, timeout: float = 10.0, *, verbose: bool = False
) -> list[tuple[int, str]]:
    """
    Resolve MX records for the domain. Returns list of (preference, hostname)
    sorted by preference (lowest first). Raises if no MX records.
    """
    if dns is None:
        raise RuntimeError("dnspython is required for MX lookup; install with: pip install dnspython")

    _log(verbose, f"Resolving MX records for {domain}...")
    try:
        answers = dns.resolver.resolve(domain, "MX")
    except dns.resolver.NXDOMAIN:
        raise ValueError(f"Domain does not exist: {domain}")
    except dns.resolver.NoAnswer:
        raise ValueError(f"No MX records for domain: {domain}")

    records = [(r.preference, str(r.exchange).rstrip(".")) for r in answers]
    records.sort(key=lambda x: x[0])
    if verbose:
        _log(verbose, f"Found {len(records)} MX host(s):")
        for pref, host in records:
            _log(verbose, f"  {pref:>5} {host}")
    return records


def check_email(
    email: str,
    *,
    timeout: float = 10.0,
    mail_from: str = "",
    retries: int = 0,
    retry_delay: float = 0.0,
    retry_backoff: float = 1.0,
    verbose: bool = False,
    proxy_url: Optional[str] = None,
) -> CheckResult:
    """
    Check whether the recipient mail server accepts the given address.
    Connects to the domain's MX, sends MAIL FROM and RCPT TO, and returns
    the server's response (success, code, message). No email is sent.
    """
    _log(verbose, f"Checking {email}")
    email = email.strip().lower()
    if not email or "@" not in email:
        _log(verbose, "  Invalid email format.")
        return CheckResult(
            success=False,
            code=0,
            message="Invalid email format",
            email=email,
        )

    _, domain = email.rsplit("@", 1)
    if not domain:
        _log(verbose, "  Invalid email domain.")
        return CheckResult(
            success=False,
            code=0,
            message="Invalid email domain",
            email=email,
        )

    try:
        mx_hosts = get_mx_hosts(domain, timeout=timeout, verbose=verbose)
    except ValueError as e:
        _log(verbose, f"  Error: {e}")
        return CheckResult(
            success=False,
            code=0,
            message=str(e),
            email=email,
        )

    if not mx_hosts:
        _log(verbose, "  No MX records for domain.")
        return CheckResult(
            success=False,
            code=0,
            message="No MX records for domain",
            email=email,
        )

    if retries < 0:
        retries = 0
    if retry_delay < 0:
        retry_delay = 0.0
    if retry_backoff < 1.0:
        retry_backoff = 1.0

    network_errors: list[str] = []
    attempts_per_host = retries + 1

    for _, mx_host in mx_hosts:
        for attempt in range(attempts_per_host):
            attempt_num = attempt + 1
            _log(
                verbose,
                f"Connecting to {mx_host}:25 (attempt {attempt_num}/{attempts_per_host})...",
            )
            try:
                with smtplib.SMTP(timeout=timeout) as smtp:
                    if proxy_url:
                        sock = create_connection(mx_host, 25, timeout=timeout, proxy_url=proxy_url)
                        smtp.sock = sock
                        smtp.file = sock.makefile("rb")
                        smtp._get_greeting()
                    else:
                        smtp.connect(mx_host, 25)
                    _log(verbose, "  EHLO...")
                    smtp.ehlo()
                    _log(verbose, f"  MAIL FROM: <{mail_from or '<>'}>")
                    smtp.mail(mail_from or "<>")
                    _log(verbose, f"  RCPT TO:   <{email}>")
                    code, message = smtp.rcpt(email)
                    # Normalize: smtplib may return code as int and message as bytes or str
                    code = int(code)
                    if isinstance(message, bytes):
                        message = message.decode("utf-8", errors="replace")
                    _log(verbose, f"  Reply:     {code} {message.strip()}")
                    return CheckResult(
                        success=200 <= code < 300,
                        code=code,
                        message=message.strip(),
                        email=email,
                    )
            except smtplib.SMTPConnectError as e:
                category = _classify_network_error(e)
                msg = f"{category} on {mx_host}: {e}"
                _log(verbose, f"  {msg}")
                network_errors.append(msg)
            except smtplib.SMTPRecipientsRefused as e:
                recipients = e.recipients
                if email in recipients:
                    code, message = recipients[email]
                    code = int(code)
                    if isinstance(message, bytes):
                        message = message.decode("utf-8", errors="replace")
                    return CheckResult(
                        success=False,
                        code=code,
                        message=message.strip(),
                        email=email,
                    )
                return CheckResult(
                    success=False,
                    code=0,
                    message=str(e),
                    email=email,
                )
            except OSError as e:
                category = _classify_network_error(e)
                msg = f"{category} on {mx_host}: {e}"
                _log(verbose, f"  {msg}")
                network_errors.append(msg)

            if attempt < retries and retry_delay > 0:
                sleep_for = retry_delay * (retry_backoff**attempt)
                _log(verbose, f"  Retrying in {sleep_for:.2f}s...")
                time.sleep(sleep_for)

    if network_errors:
        # If we had network errors on all attempts, run a diagnosis on the last host
        # to help the user understand if it's a local block or remote issue.
        # We use the last attempted mx_host.
        if mx_host:
            _log(verbose, "  All attempts failed. Running network diagnosis...")
            diagnosis = diagnose_network_block(mx_host, proxy_url=proxy_url)
            _log(verbose, f"  {diagnosis}")
            return CheckResult(
                success=False,
                code=0,
                message=f"{'; '.join(network_errors)} | {diagnosis}",
                email=email,
            )

        return CheckResult(
            success=False,
            code=0,
            message="; ".join(network_errors),
            email=email,
        )

    return CheckResult(
        success=False,
        code=0,
        message="Unable to connect to any MX host",
        email=email,
    )


def interpret_code(code: int) -> str | None:
    """Return a short human-readable interpretation for a known SMTP code, or None."""
    return CODE_INTERPRETATIONS.get(code)
