# cylera-client

A Python client for the [Cylera Partner API](https://partner.us1.cylera.com/apidocs/).

## Installation

```bash
pip install cylera-client
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv add cylera-client
```

## Usage

```python
from cylera_client import CyleraClient, Inventory, Utilization, Network, Risk, Threat

client = CyleraClient(
    username="you@example.com",
    password="your-password",
    base_url="https://partner.us1.cylera.com/",
)
```

Authentication is handled automatically. Tokens are cached and refreshed before expiry.

### Inventory

```python
inventory = Inventory(client)

# Get a single device by MAC address
device = inventory.get_device("7f:14:22:72:00:e5")

# List devices with optional filters
devices = inventory.get_devices(
    vendor="Philips",
    device_class="Medical",
    page=0,
    page_size=50,
)

# Get device attributes
attrs = inventory.get_device_attributes("7f:14:22:72:00:e5")
```

### Utilization

```python
utilization = Utilization(client)

procedures = utilization.get_procedures(
    device_uuid="ffc20dfe-4c24-11ec-8a38-5eeeaabea551",
    completed_after="2024/01/01",
    page=0,
    page_size=100,
)
```

### Network

```python
network = Network(client)

subnets = network.get_subnets(vlan=477)
```

### Risk

```python
risk = Risk(client)

# Get vulnerabilities
vulns = risk.get_vulnerabilities(severity="CRITICAL", status="OPEN")

# Get mitigations for a specific CVE
mitigations = risk.get_mitigations(vulnerability="CVE-2017-2852")
```

### Threats

```python
threat = Threat(client)

threats = threat.get_threats(severity="HIGH", status="OPEN", page=0, page_size=50)
```

## Debugging

Set `DEBUG=1` to print request details to stderr (authorization headers are redacted):

```bash
DEBUG=1 python your_script.py
```

## Development

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
```

Then run the full test suite (pytest, linting, type checking, security scanning):

```bash
./test.sh
```

Or with [Doppler](https://docs.doppler.com/docs/install-cli) for secrets management:

```bash
./test.sh --use-doppler
```

To run pytest only:

```bash
uv run pytest -v
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
