# Tests for ota-image-libs

This directory contains the test suite for the ota-image-libs project.

## Running Tests

To run all tests:

```bash
uv run pytest
```

To run tests with coverage:

```bash
uv run coverage report
```

To run a specific test file:

```bash
uv run pytest tests/test_common.py
```

To run a specific test:

```bash
uv run pytest tests/test_common.py::TestTmpFname::test_tmp_fname_all_parameters
```
