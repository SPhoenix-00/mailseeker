# Mailseeker

CLI tool to check an email address for validity (using the recipient mail server’s response) or to discover a likely address from first name, last name, and domain.

## Features

- **Validate**: Check one email address; prints whether the server accepted it and the exact SMTP code and message (e.g. `550 User unknown`).
- **Discover**: Given first name, last name, and domain, try common address patterns (e.g. `first.last`, `firstlast`, `flast`) in order and report which one(s) the server accepts.

No email is sent; the tool only performs SMTP RCPT TO checks.

## Requirements

- Python 3.9+
- [dnspython](https://www.dnspython.org/) (for MX lookups)
- Optional: **PySocks** for `--proxy` (e.g. Mullvad): `pip install -e ".[proxy]"`

## Install

```bash
pip install -e .
# or
pip install -r requirements.txt
pip install -e .
```

For development (tests):

```bash
pip install -e ".[dev]"
```

## Usage

**Validate one address** (prints acceptance and server response):

```bash
mailseeker validate user@example.com
```

**Discover** an address from first name, last name, and domain (tries patterns in order, stops at first accepted by default):

```bash
mailseeker discover --first Jane --last Doe --domain example.com
```

Options for `discover`:

- `--all` – Try all candidate patterns and list every accepted address (default is to stop at the first).
- `--delay SECONDS` – Pause between attempts (e.g. `1` or `2`) to reduce the risk of rate limiting.
- `--timeout SECONDS` – SMTP connect/response timeout (default: 10).
- `--mail-from ADDR` – Envelope sender for the probe (default: empty).

**Proxy (bypass port 25 blocks)**:

- `--proxy URL` – Route all SMTP and diagnostic traffic through a SOCKS5 proxy. Example: `--proxy socks5h://127.0.0.1:1080`. You can also set `MAILSEEKER_PROXY` in the environment. Requires: `pip install -e ".[proxy]"`.
- **Proxy-only (no VPN app)**: To send only Mailseeker’s traffic through a host that has port 25 open, use a **local SOCKS5 proxy** that doesn’t require a full VPN. For example, create an SSH tunnel to a server that allows outbound port 25:  
  `ssh -D 1080 -f -N user@your-server`  
  Then run: `mailseeker diagnose --proxy socks5h://127.0.0.1:1080`. Only that SSH session and Mailseeker’s proxy traffic use the server; the rest of your system stays on your normal connection.
- **Mullvad VPN**: Mullvad’s SOCKS5 proxy is only available when the Mullvad app is connected; they do not offer a proxy-only product. If you use Mullvad, you must connect in the app, then use the in-app proxy (e.g. `127.0.0.1:1080`) with `--proxy socks5h://127.0.0.1:1080`.

Run as a module:

```bash
python -m mailseeker validate user@example.com
python -m mailseeker discover --first Jane --last Doe --domain example.com
```

## Tests

```bash
# From repo root, with src on PYTHONPATH
pip install -e ".[dev]"
pytest tests -v
```

## Notes

- **Rate limiting**: Some mail servers throttle or block repeated RCPT TO checks. Use `--delay` in discovery mode and avoid aggressive probing.
- **Greylisting**: Servers may return temporary (4xx) responses; the tool reports the exact code and message.
- **No MX records**: If the domain has no MX records, the tool reports a clear error.

## Cursor setup

- **Rules**: `.cursor/rules/` – project conventions and file-specific patterns for the AI.
- **Agent context**: `AGENTS.md` – high-level goals, stack, and how to run the project. Keep it updated.
