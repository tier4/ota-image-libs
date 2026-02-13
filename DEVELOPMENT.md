# Development Guide

## Prerequisites

- Python 3.8 or later
- [uv](https://docs.astral.sh/uv/) (package manager)
- Git

## Setup

### Clone and install dependencies

```bash
git clone https://github.com/tier4/ota-image-libs.git
cd ota-image-libs
uv sync
```

### Dev Container (optional)

A [Dev Container](https://containers.dev/) configuration is provided in `.devcontainer/`. Open the project in VS Code and select **Reopen in Container** to get a pre-configured development environment with Python 3.8 and uv.

## Running Tests

Run all tests:

```bash
uv run pytest
```

Run a specific test file or test case:

```bash
uv run pytest tests/test_artifact_reader.py
uv run pytest tests/test_artifact_reader.py::TestClassName::test_method_name
```

Run tests with coverage:

```bash
uv run coverage run -m pytest
uv run coverage combine
uv run coverage report
```

## Linting and Formatting

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

Check for lint errors:

```bash
uv run ruff check src/ tests/
```

Auto-fix lint errors:

```bash
uv run ruff check --fix src/ tests/
```

Format code:

```bash
uv run ruff format src/ tests/
```

### Pre-commit Hooks

[pre-commit](https://pre-commit.com/) hooks are configured to run ruff, markdownlint, and other checks automatically on each commit.

Install the hooks:

```bash
uv run pre-commit install
```

Run all hooks manually:

```bash
uv run pre-commit run --all-files
```

## Type Checking

[Pyright](https://github.com/microsoft/pyright) is configured for type checking with standard mode targeting Python 3.8:

```bash
uv run pyright src/
```

## Building

Build the package (sdist and wheel):

```bash
uv build
```
