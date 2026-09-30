## Security Policy

### Supported Versions

This project is maintained on a best-effort basis. Security fixes are typically released to the `main` branch.

### Reporting a Vulnerability

Please **do not** open public GitHub issues for security reports.

Instead, report privately:

- Email: create a private report to the repository owner (preferred)
- If you cannot reach the maintainer, open an issue with **no sensitive details** and request a private contact channel.

Include:

- A clear description of the issue and impact
- Steps to reproduce (PoC if possible)
- Affected components and versions/commit SHA
- Any suggested mitigation

### Secrets

This repo uses GitHub Actions secrets for runtime credentials:

- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
