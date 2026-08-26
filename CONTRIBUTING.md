# Contributing to PoetryEduAgent

Thank you for helping improve PoetryEduAgent. Contributions are welcome in both English and Chinese.

## Before you start

- Use Discussions for setup questions, teaching ideas, and design conversations.
- Use Issues for reproducible bugs and concrete feature requests.
- Search existing Issues and Discussions before opening a new one.
- Never publish API keys, private model paths, student data, or other sensitive information.

## Development setup

```bash
git clone https://github.com/7ianostalgia/PoetryEduAgent.git
cd PoetryEduAgent
bash scripts/setup_dev.sh
cp .env.example .env
python scripts/initialize_database.py
```

Run the development service:

```bash
bash scripts/start_dev.sh
```

Run the automated checks:

```bash
.venv/bin/pytest
```

## Pull requests

1. Create a focused branch from `main`.
2. Keep each pull request limited to one clear concern.
3. Explain the motivation, implementation, and verification.
4. Add or update tests when behavior changes.
5. Update documentation when configuration, APIs, or workflows change.
6. Use co-authored commits when work was completed collaboratively.

For interface changes, include a screenshot. For model or GPU changes, describe the environment and provide reproducible evidence without exposing private infrastructure.

## Review principles

Changes should preserve the project's core guarantees:

- educational content and generated images remain independently reviewable;
- correction attempts are bounded and observable;
- model output is validated before it reaches the final result;
- development mode remains reproducible without GPU models;
- private data, model weights, and credentials remain outside the repository.
