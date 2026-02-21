"""Generate email candidates from first/last name and domain; try each until accepted."""

import sys
import time
from typing import Optional

from .smtp_check import CheckResult, check_email


def _normalize(s: str) -> str:
    """Lowercase, strip, and optionally flatten accents for local part."""
    s = s.strip().lower()
    # Simple accent flatten: replace common accented chars (optional, keep minimal)
    for old, new in (
        ("é", "e"),
        ("è", "e"),
        ("ê", "e"),
        ("ë", "e"),
        ("à", "a"),
        ("á", "a"),
        ("â", "a"),
        ("ä", "a"),
        ("ù", "u"),
        ("ú", "u"),
        ("û", "u"),
        ("ü", "u"),
        ("î", "i"),
        ("ï", "i"),
        ("ô", "o"),
        ("ö", "o"),
        ("ç", "c"),
        ("ñ", "n"),
    ):
        s = s.replace(old, new)
    return s


def _local_part(first: str, last: str, pattern: str) -> str:
    """
    Build local part from pattern. Pattern uses placeholders:
    first, last, f (first initial), l (last initial).
    """
    f = _normalize(first)
    l = _normalize(last)
    fi = f[0] if f else ""
    li = l[0] if l else ""
    out = (
        pattern.replace("{first}", f)
        .replace("{last}", l)
        .replace("{f}", fi)
        .replace("{l}", li)
    )
    return out


def email_candidates(first: str, last: str, domain: str) -> list[str]:
    """
    Build list of email address candidates from first name, last name, and domain.
    Order: most likely to least likely. Domain is normalized (lowercase, strip).
    """
    domain = domain.strip().lower()
    if not domain:
        return []

    patterns = [
        "{first}.{last}",
        "{first}{last}",
        "{first}_{last}",
        "{first}-{last}",
        "{first}.{l}",
        "{f}.{last}",
        "{first}{l}",
        "{f}{last}",
        "{first}",
        "{last}",
        "{last}.{first}",
        "{last}{first}",
        "{f}{l}",
        "{f}.{l}",
        "{last}.{f}",
        "{l}.{first}",
        "{l}{first}",
    ]

    seen: set[str] = set()
    candidates: list[str] = []
    for p in patterns:
        local = _local_part(first, last, p)
        if not local:
            continue
        # Skip if same as previous (e.g. first only vs last only when same)
        email = f"{local}@{domain}"
        if email not in seen:
            seen.add(email)
            candidates.append(email)
    return candidates


def discover(
    first: str,
    last: str,
    domain: str,
    *,
    stop_at_first: bool = False,
    delay: float = 0,
    timeout: float = 10.0,
    mail_from: str = "",
    retries: int = 0,
    retry_delay: float = 0.0,
    retry_backoff: float = 1.0,
    verbose: bool = False,
    proxy_url: Optional[str] = None,
) -> list[CheckResult]:
    """
    Try each candidate email in order; return all results (accepted and rejected).
    If stop_at_first is True, stop trying after the first accepted address (still returns all tried so far).
    delay is seconds to wait between attempts (0 = no delay).
    When verbose is True, progress is shown as one line per candidate; SMTP details are not shown per candidate.
    """
    candidates = email_candidates(first, last, domain)
    total = len(candidates)
    results: list[CheckResult] = []
    for i, email in enumerate(candidates):
        if delay and i > 0:
            time.sleep(delay)
        result = check_email(
            email,
            timeout=timeout,
            mail_from=mail_from,
            retries=retries,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            verbose=False,  # keep discover output compact; no per-candidate SMTP dump
            proxy_url=proxy_url,
        )
        results.append(result)
        if verbose:
            status = "\u2713" if result.success else "\u2717"  # ✓ / ✗
            short_msg = (result.message or "")[:48]
            if len((result.message or "")) > 48:
                short_msg += "..."
            print(f"  {i + 1:>{len(str(total))}}/{total}  {email:<40}  {status}  {result.code}  {short_msg}", file=sys.stderr)
        if result.success and stop_at_first:
            break
    return results
