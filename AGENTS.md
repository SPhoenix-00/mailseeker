# Mailseeker – Agent Context

This project is **Mailseeker**. Use this file to understand goals and constraints when helping in this repo.

## Project

- **Name**: Mailseeker
- **Purpose**: Email validation and discovery. (1) Validate an address by connecting to the recipient’s mail server and reporting its exact SMTP response. (2) Discover a likely address from first name, last name, and domain by trying common patterns (e.g. first.last, firstlast) in order.
- **Stack**: Python 3.9+, dnspython (MX lookup), stdlib smtplib/argparse. Package layout: `src/mailseeker/` with `smtp_check`, `discovery`, `cli`; entrypoint `mailseeker` or `python -m mailseeker`.

## Conventions

- See `.cursor/rules/` for Cursor rules (coding standards, file-specific patterns).
- Prefer changes that match existing style and structure.

## Getting Started

- **Install**: `pip install -e .` (or `pip install -r requirements.txt` then `pip install -e .`). Dev: `pip install -e ".[dev]"`.
- **Run**: `mailseeker validate <email>` or `mailseeker discover --first X --last Y --domain Z`. Or `python -m mailseeker` with same subcommands.
- **Tests**: `pytest tests -v` (from repo root; ensure `src` is on PYTHONPATH, e.g. via editable install).
- **Config**: No env vars required. Optional CLI flags: `--timeout`, `--mail-from`, `--delay` (discover), `--all` (discover), `--proxy URL` (SOCKS5, e.g. Mullvad; env: `MAILSEEKER_PROXY`). Proxy support needs optional dep: `pip install -e ".[proxy]"`.

Update this file as the project evolves so the AI has accurate context.
