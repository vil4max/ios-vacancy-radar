## Contributing

Thanks for your interest in contributing.

### What to contribute

- Fix broken collectors / parsing edge cases
- Add new company sources or feeds (Python)
- CI improvements and reliability hardening

### Development

This repository is designed to run on **GitHub Actions**.

For local checks:

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest -q
python3 -c "from collector.companies import collect_all; from storage.seen import load_seen; from integrations.notify import format_vacancies_message"
```

### Pull requests

- Keep changes focused and small
- Prefer incremental commits with clear messages (Conventional Commits)
- Do not commit secrets or personal credentials

### Dependency and security checks

GitHub Actions installs `requirements.lock` (runtime) or
`requirements-dev.lock` (runtime and development) with hashes and binary-only
packages. The locks retain the versions verified by CI run `34733216423`.
`pyaes==1.6.1`, required by Telethon, is the only source-distribution exception;
its archive is pinned by SHA-256. No other package may execute source build code.

After an approved dependency change, regenerate both locks for Python 3.12 and
Linux with `uv pip compile --generate-hashes --only-binary :all: --no-binary pyaes`.
Use `requirements.txt` for the runtime lock and both requirements input files for
the development lock. Review version and hash changes, then run CI before use.
Install in a disposable Python 3.12 environment with
`python3 -m pip install --require-hashes --only-binary :all: --no-binary pyaes -r requirements-dev.lock`.

SonarQube Cloud uses automatic analysis and `.sonarcloud.properties`. The
`sonar-project.properties` file is only used by a separately configured scanner.
Do not disable rules or exclude workflow/source files to pass the quality gate.

### Reporting issues

Please include:

- Expected vs actual behavior
- Reproduction steps / logs
- Example URLs or minimal samples (without secrets)
