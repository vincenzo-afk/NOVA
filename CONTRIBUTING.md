# Contributing to NOVA

Thank you for helping improve NOVA. The project spans language-model routing, local memory, voice, vision, desktop automation, Android control, scheduling, and safety-sensitive tools, so changes should remain focused and should preserve graceful fallback behavior.

## Development setup

Create a virtual environment, install the repository dependencies, copy `.env.example` to `.env`, and run the installer checks when your change needs system integrations:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python3 setup.py
```

Do not commit `.env`, credentials, device identifiers, local conversation state, logs, exports, vector stores, or vendor checkouts.

## Validation

Run the existing test suite and syntax check before opening a pull request:

```bash
NOVA_ENV=test python -m pytest tests -q
python -m compileall -q .
```

When changing optional services such as Ollama, OmniParser, Telegram, ADB, Playwright, or voice providers, describe the local prerequisites and the validation performed in the pull request.

## Pull requests

Use a branch from `main` and keep each pull request focused on one behavioral or documentation change. The description should explain the intent, affected modules, configuration changes, test commands and results, platform assumptions, and any security or privacy impact. Include screenshots or logs only after removing credentials and personal data.

Prefer concise imperative commit subjects using the Conventional Commits style, for example `fix: guard empty goal state` or `docs: clarify Docker configuration`. Do not rewrite shared history in a pull request unless the repository owner explicitly requests it.

## Design expectations

New automation must pass through the existing validation and safety layers. New external integrations should be optional, configured through environment variables, and covered by mocked tests where practical. Changes to the README should use commands and feature descriptions that can be verified against the source tree.
