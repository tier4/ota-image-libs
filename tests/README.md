# Tests for ota-image-libs

This directory contains the test suite for the ota-image-libs project.

## Running Tests

To run all tests:

```bash
uv run pytest
```

To run tests with coverage:

```bash
uv run pytest --cov=ota_image_libs --cov-report=html
```

To run a specific test file:

```bash
uv run pytest tests/test_version.py
```

To run a specific test:

```bash
uv run pytest tests/test_version.py::test_version_exists
```
