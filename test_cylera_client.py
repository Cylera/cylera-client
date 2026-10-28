# These tests depend on data that exists in the demo environment
# CYLERA_BASE_URL="https://partner.demo.cylera.com/"
#
# Test with
# $ uv run pytest -v -s

from sys import stderr
import os
import time
import unittest
import json
import sys
from unittest.mock import MagicMock, patch
from cylera_client import (
    CyleraAPIError,
    CyleraAuthError,
    CyleraClient,
    CyleraExchangeError,
    Organization,
    exchange_workos_token,
    Inventory,
    Utilization,
    Network,
    Risk,
    Threat,
)

# Check if verbose flag is present
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv


def log(message):
    """Print message only if verbose flag is set"""
    if VERBOSE:
        print(message)


def get_env_var(env_var_name: str):
    value = os.environ.get(env_var_name)
    if not value:
        print(
            f"Error: Required environment variable '{env_var_name}' is not set or is empty",
            file=stderr,
        )
        exit(1)
    return str(value)


class TestGetOrganization(unittest.TestCase):
    def test_get_organization(self):
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        organization = Organization(client)
        result = organization.get_organization()

        log(json.dumps(result, indent=2))
        self.assertIn("name", result)


class TestGetAvailableOrganizations(unittest.TestCase):
    def test_get_available_organizations(self):
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        organization = Organization(client)
        result = organization.get_available_organizations()

        log(json.dumps(result, indent=2))
        self.assertIsInstance(result, list)
        for org in result:
            self.assertIn("id", org)
            self.assertIn("name", org)


class TestSwitchOrganization(unittest.TestCase):
    def test_switch_and_reset_organization(self):
        client = CyleraClient(
            username=get_env_var("TEST_SWITCH_CYLERA_USERNAME"),
            password=get_env_var("TEST_SWITCH_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_SWITCH_CYLERA_BASE_URL"),
        )
        organization = Organization(client)

        current_org = organization.get_organization()
        available = organization.get_available_organizations()
        other_orgs = [o for o in available if o["name"] != current_org["name"]]
        if not other_orgs:
            self.skipTest("No other organizations available to switch into")

        target = other_orgs[0]
        result = organization.switch_organization(target["id"])
        log(json.dumps(result, indent=2))
        time.sleep(15)  # switch is processed asynchronously

        # Token should be cleared after switch
        self.assertIsNone(client._token)

        # Verify we are now in the target org (re-authenticates automatically)
        new_org = organization.get_organization()
        self.assertEqual(new_org["name"], target["name"])

        # Switch back to the original org
        result = organization.reset_organization()
        log(json.dumps(result, indent=2))
        time.sleep(15)  # reset is processed asynchronously
        current_org2 = organization.get_organization()
        self.assertEqual(current_org,current_org2)


class TestTokenModeConstructorValidation(unittest.TestCase):
    """No network required — pure input validation."""

    def test_token_and_password_together_raises(self):
        with self.assertRaises(ValueError):
            CyleraClient(
                username="someone@example.com",
                password="irrelevant",  # nosec B106 - placeholder, not a real credential
                base_url="https://partner.demo.cylera.com/",
                token="irrelevant-token",  # nosec B106 - placeholder, not a real credential
            )

    def test_neither_token_nor_password_raises(self):
        with self.assertRaises(ValueError):
            CyleraClient(base_url="https://partner.demo.cylera.com/")

    def test_missing_base_url_raises(self):
        with self.assertRaises(ValueError):
            CyleraClient(token="irrelevant-token")  # nosec B106 - placeholder, not a real credential

    def test_token_only_constructs_without_error(self):
        client = CyleraClient(
            token="irrelevant-token",  # nosec B106 - placeholder, not a real credential
            base_url="https://partner.demo.cylera.com/",
        )
        self.assertEqual(client._token, "irrelevant-token")
        self.assertTrue(client._token_mode)
        self.assertEqual(
            client.session.headers["Authorization"], "Bearer irrelevant-token"
        )


class TestTokenModeGetOrganization(unittest.TestCase):
    def test_token_mode_client_fetches_organization_with_a_real_token(self):
        # Get a real token the normal way first, then hand it to a second,
        # independent client constructed with token= only — no
        # username/password anywhere on the second client, proving the
        # request plumbing works end to end without ever calling
        # /auth/login_user itself.
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        client._authenticate()
        real_token = client._token
        self.assertIsNotNone(real_token)

        token_client = CyleraClient(
            token=real_token, base_url=get_env_var("TEST_CYLERA_BASE_URL")
        )
        organization = Organization(token_client)
        result = organization.get_organization()

        log(json.dumps(result, indent=2))
        self.assertIn("name", result)

    def test_invalid_token_surfaces_as_401_without_attempting_login(self):
        # In token mode there's no username/password to fall back on — an
        # invalid token must surface as a 401 CyleraAPIError, not attempt
        # to (impossibly) re-authenticate.
        token_client = CyleraClient(
            token="not-a-real-token",  # nosec B106 - placeholder, not a real credential
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        organization = Organization(token_client)
        with self.assertRaises(CyleraAPIError) as ctx:
            organization.get_organization()
        self.assertEqual(ctx.exception.status_code, 401)


class TestTokenModeSwitchOrganization(unittest.TestCase):
    def test_switch_and_reset_organization_keep_the_same_token(self):
        client = CyleraClient(
            username=get_env_var("TEST_SWITCH_CYLERA_USERNAME"),
            password=get_env_var("TEST_SWITCH_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_SWITCH_CYLERA_BASE_URL"),
        )
        client._authenticate()
        real_token = client._token
        self.assertIsNotNone(real_token)

        token_client = CyleraClient(
            token=real_token, base_url=get_env_var("TEST_SWITCH_CYLERA_BASE_URL")
        )
        organization = Organization(token_client)

        current_org = organization.get_organization()
        available = organization.get_available_organizations()
        other_orgs = [o for o in available if o["name"] != current_org["name"]]
        if not other_orgs:
            self.skipTest("No other organizations available to switch into")

        target = other_orgs[0]
        try:
            result = organization.switch_organization(target["id"])
            log(json.dumps(result, indent=2))
            time.sleep(15)  # switch is processed asynchronously

            # Unlike username/password mode (see TestSwitchOrganization above),
            # the token is NOT cleared in token mode.
            self.assertEqual(token_client._token, real_token)

            new_org = organization.get_organization()
            self.assertEqual(new_org["name"], target["name"])
        finally:
            # Always reset, even on assertion failure — this account is
            # shared with TestSwitchOrganization above, and a switch left
            # uncleared would leave it stuck for the next run.
            result = organization.reset_organization()
            log(json.dumps(result, indent=2))
            time.sleep(15)  # reset is processed asynchronously

        self.assertEqual(token_client._token, real_token)
        current_org2 = organization.get_organization()
        self.assertEqual(current_org, current_org2)


def _password_token(prefix: str = "TEST") -> str:
    """A real Cylera token from a password sign-in, standing in for one a
    token exchange would return."""
    client = CyleraClient(
        username=get_env_var(f"{prefix}_CYLERA_USERNAME"),
        password=get_env_var(f"{prefix}_CYLERA_PASSWORD"),
        base_url=get_env_var(f"{prefix}_CYLERA_BASE_URL"),
    )
    client._authenticate()
    if client._token is None:
        raise CyleraAuthError("No token from the password sign-in")
    return client._token


class TestTokenProviderConstructorValidation(unittest.TestCase):
    """No network required — pure input validation."""

    def test_token_provider_with_password_raises(self):
        with self.assertRaises(ValueError):
            CyleraClient(
                username="someone@example.com",
                password="irrelevant",  # nosec B106 - placeholder, not a real credential
                base_url="https://partner.demo.cylera.com/",
                token_provider=lambda: "irrelevant-token",
            )

    def test_token_provider_with_token_raises(self):
        with self.assertRaises(ValueError):
            CyleraClient(
                token="irrelevant-token",  # nosec B106 - placeholder, not a real credential
                token_provider=lambda: "irrelevant-token",
                base_url="https://partner.demo.cylera.com/",
            )

    def test_token_provider_isnt_called_until_the_first_request(self):
        provider = MagicMock(return_value="irrelevant-token")
        client = CyleraClient.with_token_provider(provider, "https://partner.demo.cylera.com/")
        provider.assert_not_called()
        self.assertIsNone(client._token)


class TestTokenProviderMode(unittest.TestCase):
    def test_the_token_is_fetched_once_and_reused(self):
        provider = MagicMock(return_value=_password_token())
        organization = Organization(
            CyleraClient(token_provider=provider, base_url=get_env_var("TEST_CYLERA_BASE_URL"))
        )

        organization.get_organization()
        result = organization.get_organization()

        log(json.dumps(result, indent=2))
        self.assertIn("name", result)
        provider.assert_called_once()

    def test_a_401_fetches_a_new_token_and_retries(self):
        # An expired token looks the same to the client as this one.
        provider = MagicMock(side_effect=["not-a-real-token", _password_token()])
        organization = Organization(
            CyleraClient(token_provider=provider, base_url=get_env_var("TEST_CYLERA_BASE_URL"))
        )

        result = organization.get_organization()

        self.assertIn("name", result)
        self.assertEqual(provider.call_count, 2)

    def test_a_provider_that_keeps_failing_surfaces_as_a_401(self):
        provider = MagicMock(return_value="not-a-real-token")
        organization = Organization(
            CyleraClient(token_provider=provider, base_url=get_env_var("TEST_CYLERA_BASE_URL"))
        )

        with self.assertRaises(CyleraAPIError) as ctx:
            organization.get_organization()
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(provider.call_count, 2)


class TestTokenProviderSwitchOrganization(unittest.TestCase):
    def test_a_switch_fetches_a_new_token(self):
        # A token from before a switch keeps acting on the old
        # organization, so the client asks for a new one, as an
        # integration exchanging a WorkOS token would.
        provider = MagicMock(side_effect=lambda: _password_token("TEST_SWITCH"))
        client = CyleraClient(token_provider=provider, base_url=get_env_var("TEST_SWITCH_CYLERA_BASE_URL"))
        organization = Organization(client)

        current_org = organization.get_organization()
        available = organization.get_available_organizations()
        other_orgs = [o for o in available if o["name"] != current_org["name"]]
        if not other_orgs:
            self.skipTest("No other organizations available to switch into")

        target = other_orgs[0]
        try:
            organization.switch_organization(target["id"])
            self.assertIsNone(client._token)
            time.sleep(15)  # switch is processed asynchronously
            self.assertEqual(organization.get_organization()["name"], target["name"])
            self.assertEqual(provider.call_count, 2)
        finally:
            # Always reset: the account is shared with the other switch tests.
            organization.reset_organization()
            time.sleep(15)  # reset is processed asynchronously

        self.assertEqual(organization.get_organization(), current_org)


def _exchange_response(status_code: int, body: dict) -> MagicMock:
    response = MagicMock(status_code=status_code, ok=status_code < 400)
    response.json.return_value = body
    return response


class TestExchangeWorkosToken(unittest.TestCase):
    """No network required: the demo system has no token exchange yet, so
    the Partner API's answers are mocked."""

    BASE_URL = "https://partner.demo.cylera.com/"

    def _exchange(self, status_code: int, body: dict):
        with patch("cylera_client.requests.post", return_value=_exchange_response(status_code, body)) as post:
            return exchange_workos_token(self.BASE_URL, "workos-token"), post

    def test_returns_the_cylera_token(self):
        token, post = self._exchange(200, {"token": "cylera-token", "user_role": "user"})  # nosec B105 - placeholder, not a real credential

        self.assertEqual(token, "cylera-token")
        self.assertEqual(post.call_args.args[0], "https://partner.demo.cylera.com/auth/token_exchange")
        self.assertEqual(post.call_args.kwargs["json"], {"token": "workos-token"})  # nosec B105 - placeholder, not a real credential

    def test_a_refused_token_raises_with_401(self):
        with self.assertRaises(CyleraExchangeError) as ctx:
            self._exchange(401, {"message": "Unauthorized Access"})
        self.assertEqual(ctx.exception.status_code, 401)

    def test_no_token_exchange_raises_with_404(self):
        with self.assertRaises(CyleraExchangeError) as ctx:
            self._exchange(404, {})
        self.assertEqual(ctx.exception.status_code, 404)

    def test_another_failure_raises_an_auth_error(self):
        with self.assertRaises(CyleraAuthError) as ctx:
            self._exchange(500, {})
        self.assertNotIsInstance(ctx.exception, CyleraExchangeError)

    def test_a_response_without_a_token_raises_an_auth_error(self):
        with self.assertRaises(CyleraAuthError):
            self._exchange(200, {})


class TestGetDevice(unittest.TestCase):
    def test_get_device(self):
        mac_address = "7f:14:22:72:00:e5"

        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        inventory = Inventory(client)
        result = inventory.get_device(mac_address)

        log(json.dumps(result, indent=2))
        self.assertIn("device", result)
        self.assertIn("aetitle", result["device"])


class TestGetProcedures(unittest.TestCase):
    def test_get_procedures(self):
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        utilization = Utilization(client)

        # Get first page
        result1 = utilization.get_procedures(
            device_uuid="ffc20dfe-4c24-11ec-8a38-5eeeaabea551", page=0, page_size=2
        )
        log(json.dumps(result1, indent=2))
        self.assertIn("procedures", result1)
        procedures_page1 = result1["procedures"]

        # Verify page 1 contains exactly 2 items
        self.assertEqual(
            len(procedures_page1), 2, "Page 1 should contain exactly 2 items"
        )

        # Verify all procedures are for the same device
        for procedure in procedures_page1:
            self.assertEqual(
                procedure["device_uuid"],
                "ffc20dfe-4c24-11ec-8a38-5eeeaabea551",
                f"Procedure {procedure.get('device_uuid', 'unknown')} should be ffc20dfe-4c24-11ec-8a38-5eeeaabea551",
            )

        # Get second page
        result2 = utilization.get_procedures(
            device_uuid="ffc20dfe-4c24-11ec-8a38-5eeeaabea551", page=1, page_size=2
        )
        log(json.dumps(result2, indent=2))
        self.assertIn("procedures", result2)
        procedures_page2 = result2["procedures"]

        # Verify page 1 contains exactly 2 items
        self.assertEqual(
            len(procedures_page2), 2, "Page 1 should contain exactly 2 items"
        )

        # Verify all procedures are for the same device
        for procedure in procedures_page2:
            self.assertEqual(
                procedure["device_uuid"],
                "ffc20dfe-4c24-11ec-8a38-5eeeaabea551",
                f"Procedure {procedure.get('device_uuid', 'unknown')} should be ffc20dfe-4c24-11ec-8a38-5eeeaabea551",
            )

        # Verify no duplicate records between pages (using start)
        start_page1 = {procedure["start"] for procedure in procedures_page1}
        start_page2 = {procedure["start"] for procedure in procedures_page2}
        duplicates = start_page1.intersection(start_page2)
        self.assertEqual(
            len(duplicates),
            0,
            f"Found duplicate procedure between pages: {duplicates}",
        )


class TestGetDeviceAttributes(unittest.TestCase):
    def test_get_device_attributes(self):
        mac_address = "7f:14:22:72:00:e5"
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        inventory = Inventory(client)
        result = inventory.get_device_attributes(mac_address)

        log(json.dumps(result, indent=2))
        self.assertIn("device_attributes", result)


class TestGetDevices(unittest.TestCase):
    def test_get_devices(self):
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        inventory = Inventory(client)

        # Get first page
        result1 = inventory.get_devices(
            model="Panasonic IP Camera", page=0, page_size=2
        )
        log(json.dumps(result1, indent=2))
        self.assertIn("devices", result1)
        devices_page1 = result1["devices"]

        # Verify page 1 contains exactly 2 items
        self.assertEqual(len(devices_page1), 2,
                         "Page 1 should contain exactly 2 items")

        # Verify all items on page 1 have a model of "Panasonic IP Camera"
        for device in devices_page1:
            self.assertEqual(
                device["model"],
                "Panasonic IP Camera",
                f"Device {device.get('model', 'unknown')} should be a Panasonic IP Camera",
            )

        # Get second page
        result2 = inventory.get_devices(
            model="Panasonic IP Camera", page=1, page_size=2
        )
        log(json.dumps(result2, indent=2))
        self.assertIn("devices", result2)
        devices_page2 = result2["devices"]

        # Verify all items on page 2 have a model of "Panasonic IP Camera"
        for device in devices_page2:
            self.assertEqual(
                device["model"],
                "Panasonic IP Camera",
                f"Device {device.get('model', 'unknown')} should be a Panasonic IP Camera",
            )

        # Verify no duplicate records between pages (using uuid)
        uuids_page1 = {device["uuid"] for device in devices_page1}
        uuids_page2 = {device["uuid"] for device in devices_page2}
        duplicates = uuids_page1.intersection(uuids_page2)
        self.assertEqual(
            len(duplicates),
            0,
            f"Found duplicate device UUIDs between pages: {duplicates}",
        )


class TestGetExcludedDevices(unittest.TestCase):
    def test_get_excluded_devices(self):
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        inventory = Inventory(client)

        result = inventory.get_excluded_devices(page=0, page_size=2)
        log(json.dumps(result, indent=2))
        self.assertIn("devices", result)
        self.assertIn("total", result)
        self.assertIn("page", result)


class TestGetSubnets(unittest.TestCase):
    def test_get_subnets(self):
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        network = Network(client)
        result = network.get_subnets(page=0, page_size=1)
        log(json.dumps(result, indent=2))

        # The get_subnets API does appear to support pagination
        # but, it doesn't seem to work and provides the entire
        # data set in the first page. page_size appears to be
        # ignored. This is probably ok if a little weird.
        self.assertIn("subnets", result)


class TestGetMitigations(unittest.TestCase):
    def test_get_mitigations(self):
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        risk = Risk(client)
        result = risk.get_mitigations(vulnerability="CVE-2017-2852")
        log(json.dumps(result, indent=2))
        self.assertIn("mitigations", result)


class TestGetVulnerabilities(unittest.TestCase):
    def test_get_vulnerabilities(self):
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        risk = Risk(client)

        # Get first page
        result1 = risk.get_vulnerabilities(
            page=0, page_size=2, severity="CRITICAL")
        log(json.dumps(result1, indent=2))
        self.assertIn("vulnerabilities", result1)
        vulnerabilities_page1 = result1["vulnerabilities"]

        # Verify page 1 contains exactly 2 items
        self.assertEqual(
            len(vulnerabilities_page1), 2, "Page 1 should contain exactly 2 items"
        )

        # Verify all items on page 1 have CRITICAL severity
        for vuln in vulnerabilities_page1:
            self.assertEqual(
                vuln["severity"],
                "Critical",
                f"Vulnerability {vuln.get('name', 'unknown')} should have Critical severity",
            )

        # Get second page
        result2 = risk.get_vulnerabilities(
            page=1, page_size=2, severity="CRITICAL")
        log(json.dumps(result2, indent=2))
        self.assertIn("vulnerabilities", result2)
        vulnerabilities_page2 = result2["vulnerabilities"]

        # Verify page 2 contains exactly 2 items
        self.assertEqual(len(vulnerabilities_page2), 2,
                         "Page 2 should contain 2 items")

        # Verify all items on page 2 have CRITICAL severity
        for vuln in vulnerabilities_page2:
            self.assertEqual(
                vuln["severity"],
                "Critical",
                f"Vulnerability {vuln.get('name', 'unknown')} should have Critical severity",
            )

        # Verify no duplicate records between pages (using uuid)
        uuids_page1 = {vuln["uuid"] for vuln in vulnerabilities_page1}
        uuids_page2 = {vuln["uuid"] for vuln in vulnerabilities_page2}
        duplicates = uuids_page1.intersection(uuids_page2)
        self.assertEqual(
            len(duplicates),
            0,
            f"Found duplicate vulnerability UUIDs between pages: {duplicates}",
        )


    def test_get_vulnerabilities_exclude_suppressed_devices(self):
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        risk = Risk(client)

        result_excluded = risk.get_vulnerabilities(exclude_suppressed_devices=True)
        log(json.dumps(result_excluded, indent=2))
        self.assertIn("vulnerabilities", result_excluded)

        result_included = risk.get_vulnerabilities(exclude_suppressed_devices=False)
        log(json.dumps(result_included, indent=2))
        self.assertIn("vulnerabilities", result_included)


class TestThreats(unittest.TestCase):
    def test_get_threats(self):
        client = CyleraClient(
            username=get_env_var("TEST_CYLERA_USERNAME"),
            password=get_env_var("TEST_CYLERA_PASSWORD"),
            base_url=get_env_var("TEST_CYLERA_BASE_URL"),
        )
        threat = Threat(client)

        # Get first page
        result1 = threat.get_threats(page=0, page_size=2, severity="MEDIUM")
        log(json.dumps(result1, indent=2))
        self.assertIn("threats", result1)
        self.assertEqual(result1["total"], 15, "Expected 16 Medium threats")
        threats_page1 = result1["threats"]

        # Verify page 1 contains exactly 2 items
        self.assertEqual(len(threats_page1), 2,
                         "Page 1 should contain exactly 2 items")

        # Verify all items on page 1 have Medium severity
        for t in threats_page1:
            self.assertEqual(
                t["severity"],
                "Medium",
                f"Threat {t.get('name', 'unknown')} should have Medium severity",
            )

        # Get second page
        result2 = threat.get_threats(page=1, page_size=2, severity="MEDIUM")
        log(json.dumps(result2, indent=2))
        threats_page2 = result2["threats"]

        # Verify page 2 contains exactly 2 items
        self.assertEqual(len(threats_page2), 2,
                         "Page 2 should contain exactly 2 items")

        # Verify all items on page 2 have Medium severity
        for t in threats_page2:
            self.assertEqual(
                t["severity"],
                "Medium",
                f"Threat {t.get('name', 'unknown')} should have Medium severity",
            )
        #
        # Verify no duplicate records between pages (using uuid)
        uuids_page1 = {t["uuid"] for t in threats_page1}
        uuids_page2 = {t["uuid"] for t in threats_page2}
        duplicates = uuids_page1.intersection(uuids_page2)
        self.assertEqual(
            len(duplicates),
            0,
            f"Found duplicate vulnerability UUIDs between pages: {duplicates}",
        )


if __name__ == "__main__":
    unittest.main()
