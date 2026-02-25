# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`ota-image-libs` is a Python library and CLI toolkit for creating, reading, verifying, and deploying OTA image version 1.

## Commands for dev

This project uses [uv](https://docs.astral.sh/uv/) for project management, dependency management, and virtualenv management.

**Testing:**
```bash
uv run pytest                                                                       # Run all tests
uv run pytest tests/test_artifact_reader.py                                         # Run a specific test file
uv run coverage run -m pytest && uv run coverage combine && uv run coverage report  # With coverage
```

**Linting & Formatting (ruff):**
```bash
uv run ruff check src/ tests/         # Lint
uv run ruff check --fix src/ tests/   # Auto-fix lint errors
uv run ruff format src/ tests/        # Format
```

**Type Checking:**
```bash
uv run pyright src/
```

**Build:**
```bash
uv build            # both source dist and wheel package
uv build --sdist    # only source dist
uv build --wheel    # only wheel package
```

## Architecture

### Project Layout

The repository contains two top-level packages under `src/`:

- **`ota_image_libs/`** — Core shared library for reading, writing, signing, and verifying OTA images.
- **`ota_image_tools/`** — Handy utility tools to work with OTA images.

### OTA image V1 support (`ota_image_libs/v1/`)

Currently ota-image-libs suports the OTA image specification version 1.
All schemas required for OTA image specification v1 are as follow:

| Module | Purpose |
|---|---|
| `image_index/` | `ImageIndex` — top-level OCI image index |
| `image_manifest/` | `ImageManifest` — per-image layer descriptors |
| `image_config/` | `ImageConfig`, `SysConfig` — image and system configuration |
| `file_table/` | SQLite-backed file metadata for each file in an OTA image |
| `resource_table/` | SQLite-backed blob/resource metadata |
| `index_jwt/` | JWT signing/verification schema and utilities |
| `otaclient_package/` | OTAClient release package format |

Within each modules, besides schemas, utils for operating the metadata files are also available.

### Common Internal Shared Libs and Utils (`ota_image_libs/common/`, `ota_image_libs/_crypto/`)

- **`common/model_spec.py`** — Helper base classes and utils for using pydantic v2.
- **`common/metafile_base.py`** — Helper base classes for defining and parsing OTA metadata files with using pydantic v2.
- **`common/db_utils.py`** — Shared helpers on top of `simple-sqlite3-orm` for using sqlite3.
- **`common/msgpack_utils.py`** — MessagePack serialization helpers.
- **`common/io.py`** — I/O utilities (e.g. zstandard/zstd compression wrappers).
- **`_crypto/jwt_utils.py`** — ES256 JWT signing and verification.
- **`_crypto/x509_utils.py`** — X.509 certificate chain validation.

### CLI Commands: ota-image-tools (`ota_image_tools/cmds/`)

`list-image`, `inspect-index`, `inspect-blob`, `lookup-image`, `deploy-image`, `verify-sign`, `verify-resources`. All commands accept `-d`/`--debug` for debug logging.

## CI/CD

Three GitHub Actions workflows live under `.github/workflows/`:

**`test.yaml` — Test CI**
- Triggers on PRs to `main`/`v*`, pushes to `main`/`v*` (only when `src/`, `tests/`, or the workflow file changes), and manual dispatch.
- Runs `uv run coverage run -m pytest` across a matrix of Python 3.8–3.13 (`fail-fast: false`).
- On Python 3.13 only, runs a SonarCloud scan using the generated `coverage.xml`.

**`release.yml` — Release CI**
- Triggers on GitHub release (published) and manual dispatch.
- Builds the wheel using the minimum supported Python version (read from `.python-version`), uploads it as an artifact, calculates checksums, and attaches all `dist/*` files to the GitHub release.

**`gen_requirements_txt.yaml` — Requirements sync**
- For syncing uv.lock from pyproject.toml, and one-way exporting `requirements.txt` from uv.lock for snyk scan.
- Triggers on PRs to `main` when `pyproject.toml` changes, and manual dispatch.
- Re-generates `requirements.txt` from `pyproject.toml` via `.github/tools/gen_requirements_txt.py` and auto-commits the update to the PR branch if changed.

## Code Style

- **Line length**: 88
- **Target version**: `py38` (ruff `target-version` and pyright `pythonVersion`)
- **Linting rules**: pyflakes (`F`), flake8-quotes (`Q`), isort (`I`), flake8-bugbear (`B`), flake8-builtins (`A`), flake8-import-conventions (`ICN`), and `E4`/`E7`/`E9`
- **Ignored rules**: `E266` (multiple `#`), `E203` (whitespace before `:`), `E701` (multiple statements per line), `S101` (use of `assert`)
- **Docstring convention**: Google style (`tool.ruff.lint.pydocstyle`)
- **Type checking**: Pyright in `standard` mode targeting Python 3.8; tests and scripts are excluded from type checking
