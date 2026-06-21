# Contributing

Thank you for your interest in contributing! Here's how to get involved.

## Reporting bugs

Open an issue using the **Bug report** template and include:
- Steps to reproduce
- Expected vs actual behaviour
- Relevant log output from `docker compose logs`

## Suggesting features

Open an issue using the **Feature request** template and describe the use case.

## Submitting a pull request

1. Fork the repository and create a branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes. Keep commits focused — one logical change per commit.
3. Test locally using Docker Compose and the curl/Postman steps in the README.
4. Open a pull request against `main` with a clear description of what changed and why.

## Code style

- Python 3.12+
- Follow the patterns already in the codebase (dataclasses for data, errors returned as values not exceptions inside the processor, no global state)
- Comments should explain *why*, not *what*
- No new dependencies without discussion in an issue first
