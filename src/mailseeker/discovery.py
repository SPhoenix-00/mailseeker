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
    stop_at_first: bool = True,
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
    Try each candidate email in order; return accepted result(s).
    If stop_at_first is True, return as soon as one is accepted; otherwise try all.
    delay is seconds to wait between attempts (0 = no delay).
    """
    candidates = email_candidates(first, last, domain)
    if verbose:
        print(f"Generated {len(candidates)} candidate(s) for {first} {last} @ {domain}", file=sys.stderr)
    results: list[CheckResult] = []
    for i, email in enumerate(candidates):
        if delay and i > 0:
            time.sleep(delay)
        if verbose:
            print(f"Trying {i + 1}/{len(candidates)}: {email}", file=sys.stderr)
        result = check_email(
            email,
            timeout=timeout,
            mail_from=mail_from,
            retries=retries,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            verbose=verbose,
            proxy_url=proxy_url,
        )
        if result.success:
            results.append(result)
            if stop_at_first:
                break
    return results
