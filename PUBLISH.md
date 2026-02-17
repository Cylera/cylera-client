# Publishing to PyPI

This document describes how to build and publish `cylera-client` to PyPI.

## Prerequisites

- [uv](https://github.com/astral-sh/uv) installed
- PyPI account with access to the `cylera-client` package
- A PyPI API token (create one at https://pypi.org/manage/account/token/)

## Steps

### 1. Update the version

Edit the version in `pyproject.toml`:

```toml
[project]
version = "0.2.0"
```

Follow [semantic versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

### 2. Run the full test suite

Ensure all checks pass before publishing:

```bash
./test.sh
```

### 3. Build the package

```bash
uv build
```

This produces two artifacts in `dist/`:

- `cylera_client-<version>-py3-none-any.whl` — wheel
- `cylera_client-<version>.tar.gz` — source distribution

### 4. Publish to PyPI

The PyPi API token is required to publish. This secret, with a key "UV_PUBLISH_TOKEN"  is managed in Doppler. 

```bash
doppler run -- uv publish
```

### 5. Verify the release

Create a throwaway directory and change into the directory. Then to verify:

```bash
uv init
uv add cylera-client
uv run python -c "import cylera_client; print('ok')"
```

## TestPyPI (optional)

To do a dry run against TestPyPI first:

```bash
uv publish --publish-url https://test.pypi.org/legacy/ --token pypi-...
```

Then install from TestPyPI to verify:

```bash
pip install --index-url https://test.pypi.org/simple/ cylera-client
```

## Checklist

- [ ] Version bumped in `pyproject.toml`
- [ ] `CHANGELOG` / commit history reflects the changes
- [ ] All tests and quality checks pass (`./test.sh`)
- [ ] `dist/` artifacts built with `uv build`
- [ ] Published with `uv publish`
- [ ] Release verified by installing from PyPI
