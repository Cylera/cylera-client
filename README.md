# cylera-client

A Python client for the [Cylera Partner API](https://github.com/Cylera/cylera-partner-api)

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
from cylera_client import CyleraClient, Organization, Inventory, Utilization, Network, Risk, Threat

client = CyleraClient(
    username="you@example.com",
    password="your-password",
    base_url="https://partner.us1.cylera.com/",
)
```

Authentication is handled automatically. Tokens are cached and refreshed before expiry.

### Organization

```python
organization = Organization(client)

# Get the organization associated with your API credentials
org = organization.get_organization()
# {"organization_id": 17, "name": "Cylera", "internal_name": "cylera"}

# List organizations available to switch into
available = organization.get_available_organizations()

# Switch into a different organization (token is invalidated after switch)
# Note that switch_organization is handled asynchronously
# So, whenever you switch, it is wise to sleep for a few seconds to give
# the back-end time to process the reset request.
organization.switch_organization(available[0]["id"])

# Reset back to your home organization
# Note that reset_organization is handled asynchronously
# So, whenever you reset, it is wise to sleep for a few seconds to give
# the back-end time to process the reset request.
organization.reset_organization()
```

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

