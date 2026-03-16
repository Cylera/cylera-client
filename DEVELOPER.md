# Developer Guide

This project uses [uv](https://github.com/astral-sh/uv) for dependency management.

```bash
# Install dependencies
uv sync --group dev
```

### Running tests

Tests run against the Cylera demo environment. Set the required environment variables first:

```bash
export TEST_CYLERA_USERNAME="you@example.com"
export TEST_CYLERA_PASSWORD="your-password"
export TEST_CYLERA_BASE_URL="https://partner.demo.cylera.com/"
export TEST_SWITCH_CYLERA_USERNAME="you@example.com"
export TEST_SWITCH_CYLERA_PASSWORD="your-password"
export TEST_SWITCH_CYLERA_BASE_URL="https://partner.demo.cylera.com/"
```

The TEST_SWITCH_* environment variables are required to test the /organization/switch 
and /organization/reset endpoints. This test account must have at least one organization 
that it can switch into for the tests to work.

Note that these two endpoints are handled asynchronously and so the test 
TestSwitchOrganization::test_switch_and_reset_organization must sleep to give the
backend time to process the requests. If the test fails, first ensure that the
organization for the test account has been reset. If the test still fails, then 
consider increasing the sleep duration.

The tests expect to find data that exists in the demo environment under the Cylera organization.

Then run the full test suite (pytest, linting, type checking, security scanning):

```bash
./test.sh
```

Alternatively, you may choose to use [Doppler](https://docs.doppler.com/docs/install-cli) for secrets management of the required environment variables:

```bash
./test.sh --use-doppler
```

Or, if you want to see log messages during the test run:
```bash
./test.sh --use-doppler --verbose
```

To run pytest only:

```bash
uv run pytest -v
```

If you prefer to use 1Password for secrets management (assuming you have the 1Password 
CLI already installed), make sure 1Password is running. Also, ensure the environment
variable OP_ENVIRONMENT_ID is set.

```bash
./test.sh --use-op 
```

### Quality checks

The `test.sh` script runs these checks in order:

| Tool | Purpose |
|------|---------|
| `pytest` | Tests |
| `ruff` | Linting |
| `pyright` | Type checking |
| `shellcheck` | Shell script linting |
| `bandit` | Python security scanning |
| `pip-audit` | Dependency vulnerability scanning |

