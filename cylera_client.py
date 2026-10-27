"""
Cylera API Client

This module provides a Python client for interacting with the Cylera Partner
API https://partner.us1.cylera.com/apidocs/

Turn on debugging by setting the environment variable DEBUG=1
"""

from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from datetime import datetime, timedelta
from sys import stderr

import requests
import os
from requests.exceptions import RequestException


def print_request_details(response, *args, **kwargs):
    if not os.environ.get("DEBUG"):
        return
    headers = dict(response.request.headers)
    if "Authorization" in headers:
        headers["Authorization"] = "[REDACTED]"
    print(f"Request URL: {response.request.url}", file=stderr)
    print(f"Request Headers: {headers}", file=stderr)
    # Never log request body for auth endpoints
    if "auth/login" not in response.request.url and response.request.body:
        print(f"Request Body: {response.request.body}", file=stderr)


class CyleraAuthError(Exception):
    """Exception raised for authentication errors."""

    pass


class CyleraAPIError(Exception):
    """Base exception for Cylera API errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[requests.Response] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


class _AuthStrategy:
    """
    Internal — how a CyleraClient obtains and manages its bearer token.
    Not part of the public API; CyleraClient picks one based on whether
    it was constructed with username/password or token.

    Adding a new auth mode (e.g. an OAuth2 flow, or a scoped API key)
    means adding one of these plus a branch in CyleraClient.__init__ —
    not touching _make_request/Organization.switch_organization/etc.
    """

    def authenticate(self, client: "CyleraClient") -> None:
        raise NotImplementedError

    def should_retry_unauthorized(self) -> bool:
        """Whether _make_request should retry once on a 401 after
        forcing re-authentication. False when there's nothing to
        re-authenticate with (e.g. a bare token)."""
        return False

    def invalidate_after_organization_change(self, client: "CyleraClient") -> None:
        """Called after switch_organization()/reset_organization(). Only
        username/password mode needs to clear the cached token here;
        an externally-supplied token keeps working across the switch."""


class _PasswordAuth(_AuthStrategy):
    def authenticate(self, client: "CyleraClient") -> None:
        if client._is_token_valid():
            return

        try:
            response = client.session.post(
                urljoin(client.base_url, "auth/login_user"),
                json={"email": client.username, "password": client.password},
            )
            response.raise_for_status()
            data = response.json()

            if "token" not in data:
                raise CyleraAuthError("No token received in authentication response")

            client._store_token(data["token"])

        except requests.exceptions.HTTPError as e:
            raise CyleraAuthError(f"Authentication failed: {str(e)}")
        except RequestException as e:
            raise CyleraAuthError(f"Authentication request failed: {str(e)}")

    def should_retry_unauthorized(self) -> bool:
        return True

    def invalidate_after_organization_change(self, client: "CyleraClient") -> None:
        # Token is invalidated server-side; clear it so the next request
        # re-authenticates.
        client._token = None
        client._token_expiry = None


class _TokenAuth(_AuthStrategy):
    def authenticate(self, client: "CyleraClient") -> None:
        return  # The token was already provided; never call /auth/login_user.

    # should_retry_unauthorized and invalidate_after_organization_change
    # both keep the base class's defaults: no username/password to
    # re-authenticate with, and the same externally-supplied token keeps
    # working across an organization switch/reset.


class CyleraClient:
    """Client for interacting with the Cylera Partner API."""

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        base_url: Optional[str] = None,
        *,
        token: Optional[str] = None,
    ):
        """
        Initialize the Cylera API client.

        Provide either username/password (the client authenticates itself
        against /auth/login_user and re-authenticates automatically before
        expiry or on a 401) or an already-obtained bearer token (the
        client trusts it as-is, never calls /auth/login_user, and never
        attempts to re-authenticate) — never both.

        Args:
            username: Your Cylera username (mutually exclusive with token)
            password: Your Cylera password (mutually exclusive with token)
            base_url: Base URL for the API (always required)
            token: An already-obtained Cylera token, e.g. one an
                   integration obtained for its user from the Partner API
                   (mutually exclusive with username/password)

        Raises:
            ValueError: If both token and password are given, if neither
                is given, or if base_url is missing
        """
        if token is not None and password is not None:
            raise ValueError("Pass either username/password or token, not both")
        if token is None and password is None:
            raise ValueError("Pass either username/password or token")
        if not base_url:
            raise ValueError("base_url is required")

        self.username = username
        self.password = password
        self.base_url = base_url
        self.session = requests.Session()
        self.session.hooks["response"].append(print_request_details)
        self.session.headers.update(
            {
                # "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "cylera-client-python",
            }
        )
        self._token_mode = token is not None
        self._auth: _AuthStrategy = _TokenAuth() if self._token_mode else _PasswordAuth()
        self._token = token
        self._token_expiry = None
        if self._token_mode:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

    @classmethod
    def with_password(cls, username: str, password: str, base_url: str) -> "CyleraClient":
        """Equivalent to CyleraClient(username=..., password=..., base_url=...) —
        an explicit, self-documenting alternative for callers who'd rather
        not rely on which keyword-combination implies which mode."""
        return cls(username=username, password=password, base_url=base_url)

    @classmethod
    def with_token(cls, token: str, base_url: str) -> "CyleraClient":
        """Equivalent to CyleraClient(token=..., base_url=...) — an explicit,
        self-documenting alternative for callers who'd rather not rely on
        which keyword-combination implies which mode."""
        return cls(token=token, base_url=base_url)

    def _is_token_valid(self) -> bool:
        """Check if the current token is valid and not expired."""
        return bool(
            self._token and self._token_expiry and datetime.now() < self._token_expiry
        )

    def _store_token(self, token: str) -> None:
        """Store the authentication token and update session headers."""
        self._token = token
        # Set token expiry to 23 hours (assuming 24-hour token validity)
        self._token_expiry = datetime.now() + timedelta(hours=23)
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def _authenticate(self) -> None:
        """
        Ensure this client has a valid token, per its auth strategy
        (username/password: authenticate if needed; token: no-op, since
        the token was already provided at construction time and this
        client never calls /auth/login_user).

        Raises:
            CyleraAuthError: If authentication fails
        """
        self._auth.authenticate(self)

    def test_authenticate(self) -> Dict[str, Any]:
        """
        Test authentication with the Cylera API.

        This method forces a fresh authentication attempt, ignoring any
        cached token. Use this to verify credentials are valid.

        Returns:
            The full authentication response data

        Raises:
            CyleraAuthError: If authentication fails
        """
        # Clear any cached token to force fresh authentication
        self._token = None
        self._token_expiry = None

        try:
            response = self.session.post(
                urljoin(self.base_url, "auth/login_user"),
                json={"email": self.username, "password": self.password},
            )
            response.raise_for_status()
            data = response.json()

            if "token" not in data:
                raise CyleraAuthError("No token received in authentication response")

            self._store_token(data["token"])
            return data

        except requests.exceptions.HTTPError as e:
            raise CyleraAuthError(f"Authentication failed: {str(e)}")
        except RequestException as e:
            raise CyleraAuthError(f"Authentication request failed: {str(e)}")

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def __enter__(self) -> "CyleraClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - closes the session."""
        self.close()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Any:
        """
        Make an HTTP request to the Cylera API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint to call
            params: Query parameters
            json: JSON body for POST/PUT requests
            **kwargs: Additional arguments to pass to requests

        Returns:
            API response data

        Raises:
            CyleraAPIError: If the API request fails
            CyleraAuthError: If authentication fails
        """
        # Ensure we have a valid token
        self._authenticate()

        url = urljoin(self.base_url, endpoint)

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json,
                headers={"Accept": "application/json"},
                **kwargs,
            )

            # If we get a 401, try to re-authenticate once — except when
            # the auth strategy has nothing to re-authenticate with (e.g.
            # a bare token), where an invalid/expired credential just
            # surfaces as a 401 CyleraAPIError below.
            if response.status_code == 401 and self._auth.should_retry_unauthorized():
                self._token = None  # Force re-authentication
                self._authenticate()
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                    headers={"Accept": "application/json"},
                    **kwargs,
                )

            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            raise CyleraAPIError(
                f"API request failed: {str(e)}",
                status_code=e.response.status_code,
                response=e.response,
            )
        except RequestException as e:
            raise CyleraAPIError(f"Request failed: {str(e)}")


class Organization:
    """
    Helper class for organization-related endpoints using composition with
    CyleraClient.
    """

    def __init__(self, client: CyleraClient):
        self.client = client

    def get_organization(self) -> Dict[str, Any]:
        """
        Get the current organization.

        Returns the name of the organization associated with the API credentials
        used to authenticate this request.

        Returns:
            Organization data
        """
        return self.client._make_request("GET", "/organization/")

    def get_available_organizations(self) -> List[Dict[str, Any]]:
        """
        Get organizations available to switch into.

        Returns:
            List of organization objects with 'id' and 'name' fields
        """
        return self.client._make_request("GET", "/organization/available")

    def switch_organization(self, organization_id: str) -> Dict[str, Any]:
        """
        Switch to a different organization.

        After a successful switch the current token is invalidated. The next
        API call will automatically re-authenticate.

        Args:
            organization_id: Organization ID from get_available_organizations()

        Returns:
            Response data confirming the switch

        Raises:
            CyleraAuthError: If not authorized to switch to the organization
        """
        result = self.client._make_request(
            "POST", "/organization/switch", params={"id": organization_id}
        )
        self.client._auth.invalidate_after_organization_change(self.client)
        return result

    def reset_organization(self) -> Dict[str, Any]:
        """
        Reset organization to home.

        Resets the authenticated user back to their home organization. This is the
        inverse of switch_organization(). If already in the home organization,
        the request is a no-op.

        After a successful reset the current token is invalidated. The next
        API call will automatically re-authenticate.

        Returns:
            Response data confirming the reset
        """
        result = self.client._make_request("POST", "/organization/reset")
        self.client._auth.invalidate_after_organization_change(self.client)
        return result


class Inventory:
    """
    Helper class for inventory-related endpoints using composition with
    CyleraClient.
    """

    def __init__(self, client: CyleraClient):
        self.client = client

    def get_device(self, device_id: str) -> Dict[str, Any]:
        """
        Get details for a specific device.

        Args:
            device_id: The ID of the device to retrieve (MAC address)

        Returns:
            Device object similar to this:
            "device": {
                 "aetitle": "TGXYNUGMIK",
                 "class": "Medical",
                 "fda_class": null,
                 "first_seen": 1635056234.0,
                 "hostname": "TGXYNUGMIK",
                 "id": "ffc20dfe-4c24-11ec-8a38-5eeeaabea551",
                 "ip_address": "10.40.6.159",
                 "last_seen": 1767887269.0,
                 "location": "Location 2",
                 "mac_address": "7f:14:22:72:00:e5",
                 "model": "Allura Xper X-Ray System",
                 "os": "Windows XP",
                 "outdated": true,
                 "risk": 4,
                 "serial_number": null,
                 "type": "X-Ray Machine",
                 "uuid": "ffc20dfe-4c24-11ec-8a38-5eeeaabea551",
                 "vendor": "Philips",
                 "version": "Allura Xper, 8.1.17.2",
                 "vlan": 477
            }

        """
        return self.client._make_request(
            "GET", "/inventory/device", params={"mac_address": device_id}
        )

    def get_devices(
        self,
        aetitle: Optional[str] = None,
        device_class: Optional[str] = None,
        hostname: Optional[str] = None,
        ip_address: Optional[str] = None,
        mac_address: Optional[str] = None,
        model: Optional[str] = None,
        os: Optional[str] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        serial_number: Optional[str] = None,
        since_last_seen: Optional[int] = None,
        device_type: Optional[str] = None,
        vendor: Optional[str] = None,
        first_seen_before: Optional[int] = None,
        first_seen_after: Optional[int] = None,
        last_seen_before: Optional[int] = None,
        last_seen_after: Optional[int] = None,
        attribute_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a list of devices.

        Args:
            aetitle: Complete AE Title of device
            device_class: Device class (e.g. Medical)
            hostname: Complete hostname of device
            ip_address: Partial or complete IP or subnet
            mac_address: Partial or complete MAC address
            model: Device model
            os: Device operating system
            page: Controls which page of results to return
            page_size: Controls number of results in each response. Max 100.
            serial_number: Complete serial number of device
            since_last_seen: [DEPRECATED] Number of seconds since activity from
                             device was last detected
            device_type: Device type (e.g. EEG)
            vendor: Device vendor or manufacturer
            first_seen_before: Finds devices that were first seen before this
                               epoch timestamp
            first_seen_after: Finds devices that were first seen after this
                              epoch timestamp
            last_seen_before: Finds devices that were last seen before this
                              epoch timestamp
            last_seen_after: Finds devices that were last seen after this
                             epoch timestamp
            attribute_label: Partial or complete attribute label

        Returns:
            List of devices similar to this:
            {
              "devices": [
                {
                  "aetitle": null,
                  "class": "Infrastructure",
                  "fda_class": null,
                  "first_seen": 1635057696.0,
                  "hostname": "PMLETVCUTA",
                  "id": "67c470a6-4c28-11ec-8a38-5eeeaabea551",
                  "ip_address": "10.50.170.146",
                  "last_seen": 1768397443.0,
                  "location": "Location 1",
                  "mac_address": "00:c8:58:bd:2c:66",
                  "model": "Panasonic IP Camera",
                  "os": "Windows",
                  "outdated": null,
                  "risk": 1,
                  "serial_number": null,
                  "type": "Surveillance Camera",
                  "uuid": "67c470a6-4c28-11ec-8a38-5eeeaabea551",
                  "vendor": "Panasonic",
                  "version": null,
                  "vlan": 889
                }
              ],
              "total": null,
              "page": 1
            }
        """
        params = {
            "aetitle": aetitle,
            "class": device_class,
            "hostname": hostname,
            "ip_address": ip_address,
            "mac_address": mac_address,
            "model": model,
            "os": os,
            "page": page,
            "page_size": page_size,
            "serial_number": serial_number,
            "since_last_seen": since_last_seen,
            "type": device_type,
            "vendor": vendor,
            "first_seen_before": first_seen_before,
            "first_seen_after": first_seen_after,
            "last_seen_before": last_seen_before,
            "last_seen_after": last_seen_after,
            "attribute_label": attribute_label,
        }
        # remove None values
        params = {k: v for k, v in params.items() if v is not None}
        return self.client._make_request("GET", "/inventory/devices", params=params)

    def get_device_attributes(self, mac_address: str) -> List[Dict[str, Any]]:
        """
        Get attributes for a device.

        Args:
            mac_address: MAC address of device

        Returns:
            Device attributes object
        """
        return self.client._make_request(
            "GET", "/inventory/device_attributes", params={"mac_address": mac_address}
        )

    def get_excluded_devices(
        self,
        device_class: Optional[str] = None,
        device_type: Optional[str] = None,
        vendor: Optional[str] = None,
        model: Optional[str] = None,
        hostname: Optional[str] = None,
        ip_address: Optional[str] = None,
        mac_address: Optional[str] = None,
        first_seen_before: Optional[int] = None,
        first_seen_after: Optional[int] = None,
        last_seen_before: Optional[int] = None,
        last_seen_after: Optional[int] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get a list of excluded (unclassified) devices.

        Args:
            device_class: Device class (e.g. Medical)
            device_type: Device type (e.g. Workstation)
            vendor: Device vendor or manufacturer (e.g. Lenovo)
            model: Device model (e.g. Apple Mac Pro)
            hostname: Complete hostname of device
            ip_address: Partial or complete IP or subnet
            mac_address: Partial or complete MAC address
            first_seen_before: Finds devices that were first seen before this
                               epoch timestamp
            first_seen_after: Finds devices that were first seen after this
                              epoch timestamp
            last_seen_before: Finds devices that were last seen before this
                              epoch timestamp
            last_seen_after: Finds devices that were last seen after this
                             epoch timestamp
            page: Controls which page of results to return
            page_size: Controls number of results in each response. Max 100.

        Returns:
            List of excluded devices similar to this:
            {
              "devices": [
                {
                  "class": "Unknown",
                  "first_seen": 1635057696.0,
                  "hostname": "PMLETVCUTA",
                  "id": "67c470a6-4c28-11ec-8a38-5eeeaabea551",
                  "ip_address": "10.50.170.146",
                  "last_seen": 1768397443.0,
                  "location": "Location 1",
                  "mac_address": "00:c8:58:bd:2c:66",
                  "model": "Panasonic IP Camera",
                  "type": "Surveillance Camera",
                  "uuid": "67c470a6-4c28-11ec-8a38-5eeeaabea551",
                  "vendor": "Panasonic",
                  "vlan": 889
                }
              ],
              "total": null,
              "page": 1
            }
        """
        params = {
            "class": device_class,
            "type": device_type,
            "vendor": vendor,
            "model": model,
            "hostname": hostname,
            "ip_address": ip_address,
            "mac_address": mac_address,
            "first_seen_before": first_seen_before,
            "first_seen_after": first_seen_after,
            "last_seen_before": last_seen_before,
            "last_seen_after": last_seen_after,
            "page": page,
            "page_size": page_size,
        }
        # remove None values
        params = {k: v for k, v in params.items() if v is not None}
        return self.client._make_request("GET", "/inventory/excluded/devices", params=params)


class Utilization:
    """
    Helper class for utilization-related endpoints using composition with
    CyleraClient.
    """

    def __init__(self, client: CyleraClient):
        self.client = client

    def get_procedures(
        self,
        procedure_name: Optional[str] = None,
        accession_number: Optional[str] = None,
        device_uuid: Optional[str] = None,
        completed_after: Optional[str] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get a list of procedures.

        Args:
            procedure_name: Name of Procedure (will match partial)
            accession_number: Accession Number of Procedure
            device_uuid: Device UUID
            completed_after: Completion Date (format: YYYY/MM/DD)
            page: Controls which page of results to return
            page_size: Controls number of results in each response. Max 100.

        Returns:
            List of procedures similar to this:
            {
              "procedures": [
                {
                  "device_uuid": "ffc20dfe-4c24-11ec-8a38-5eeeaabea551",
                  "accession_number": "BNPVTYOPAZYRJOSGLBMJMGBDFJMMJBYEUQT",
                  "image_count": 8,
                  "start": "2025-12-25T05:17:36",
                  "end": "2025-12-25T17:01:17",
                  "procedure_name": "IR CHEST PORT PLACEMENT 5+ YEARS"
                }
              ],
              "total": 452,
              "page": 1
            }
        """
        params = {
            "procedure_name": procedure_name,
            "accession_number": accession_number,
            "device_uuid": device_uuid,
            "completed_after": completed_after,
            "page": page,
            "page_size": page_size,
        }
        # remove None values
        params = {k: v for k, v in params.items() if v is not None}
        return self.client._make_request(
            "GET", "/utilization/procedures", params=params
        )


class Network:
    """
    Helper class for network-related endpoints using composition with
    CyleraClient.
    """

    def __init__(self, client: CyleraClient):
        self.client = client

    def get_subnets(
        self,
        cidr_range: Optional[str] = None,
        description: Optional[str] = None,
        vlan: Optional[int] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get a list of subnets.

        Args:
            cidr_range: CIDR Range (will match partial)
            description: Description of Subnet
            vlan: VLAN
            page: Controls which page of results to return
            page_size: Controls number of results in each response. Max 100.

        Returns:
            List of subnets similar to this:
            {
              "subnets": [
                {
                  "subnet": "10.40.0.0",
                  "vlan": 477,
                  "description": "Main Building - Floor 4",
                  "mask_len": 16,
                  "subnet_inet": "10.40.0.0/16",
                  "total_devices": 865,
                  "device_breakdown": [
                    {
                      "class": "Infrastructure",
                      "count": 160
                    },
                    {
                      "class": "Medical",
                      "count": 380
                    },
                    {
                      "class": "Misc IoT",
                      "count": 240
                    },
                    {
                      "class": "Non-IoT",
                      "count": 85
                    }
                  ]
                }
              ],
              "total": 1,
              "page": 0
            }
        """
        params = {
            "cidr_range": cidr_range,
            "description": description,
            "vlan": vlan,
            "page": page,
            "page_size": page_size,
        }
        # remove None values
        params = {k: v for k, v in params.items() if v is not None}
        return self.client._make_request("GET", "/network/subnets", params=params)


class Risk:
    """
    Helper class for risk-related endpoints using composition with
    CyleraClient.
    """

    def __init__(self, client: CyleraClient):
        self.client = client

    def get_mitigations(self, vulnerability: str) -> List[Dict[str, Any]]:
        """
        Get a list of mitigations for a vulnerability.

        Args:
            vulnerability: The name of the vulnerability.

        Returns:
            List of mitigation objects
        """
        return self.client._make_request(
            "GET", "/risk/mitigations", params={"vulnerability": vulnerability}
        )

    def get_vulnerabilities(
        self,
        confidence: Optional[str] = None,
        detected_after: Optional[int] = None,
        mac_address: Optional[str] = None,
        name: Optional[str] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        exclude_suppressed_devices: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Get a list of vulnerabilities.

        Args:
            confidence: Confidence in vulnerability detection.
                        Enum: "LOW", "MEDIUM", "HIGH"
            detected_after: Epoch timestamp after which a vulnerability was
                            detected.
            mac_address: MAC address of device.
            name: Name of the vulnerability (complete or partial).
            page: Controls which page of results to return.
            page_size: Controls number of results in each response. Max 100.
            severity: Vulnerability severity.
                      Enum: "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"
            status: Vulnerability status.
                    Enum: "OPEN", "IN_PROGRESS", "RESOLVED", "SUPPRESSED"
            exclude_suppressed_devices: When True, exclude vulnerability
                                        instances for suppressed devices.

        Returns:
            List of vulnerabilities similar to this:
            {
              "vulnerabilities": [
                {
                  "uuid": "1fd9204a-4c26-11ec-8a38-5eeeaabea551",
                  "ip_address": "10.20.233.235",
                  "mac_address": "65:cc:15:5c:46:f0",
                  "model": null,
                  "type": null,
                  "vendor": null,
                  "class": "Medical",
                  "vulnerability_name": "Ripple20 (ICSA-20-168-01)",
                  "vulnerability_category": "Security",
                  "first_seen": 1637648717,
                  "last_seen": 1637648717,
                  "severity": "Critical",
                  "status": "In Progress",
                  "confidence": "High"
                }
              ],
              "total": null,
              "page": 1
            }

        """
        params = {
            "confidence": confidence,
            "detected_after": detected_after,
            "mac_address": mac_address,
            "name": name,
            "page": page,
            "page_size": page_size,
            "severity": severity,
            "status": status,
            "exclude_suppressed_devices": exclude_suppressed_devices,
        }
        # remove None values
        params = {k: v for k, v in params.items() if v is not None}
        return self.client._make_request("GET", "/risk/vulnerabilities", params=params)


class Threat:
    """
    Helper class for threat-related endpoints using composition with
    CyleraClient.
    """

    def __init__(self, client: CyleraClient):
        self.client = client

    def get_threats(
        self,
        detected_after: Optional[int] = None,
        mac_address: Optional[str] = None,
        name: Optional[str] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a list of threats.

        Args:
            detected_after: Epoch timestamp after which a threat was detected.
            mac_address: MAC address of device.
            name: Name of the threat (complete or partial).
            page: Controls which page of results to return.
            page_size: Controls number of results in each response. Max 100.
            severity: Threat severity.
                      Enum: "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"
            status: Threat status.
                    Enum: "OPEN", "IN_PROGRESS", "RESOLVED", "SUPPRESSED"

        Returns:
            List of threats similar to this:
            {
              "threats": [
                {
                  "uuid": "9b2bd1ea-4c24-11ec-8a38-5eeeaabea551",
                  "ip_address": "10.30.150.250",
                  "mac_address": "bb:b0:71:cf:30:0a",
                  "hostname": "MOGJBMHEAG",
                  "device_identifier": "Philips Achieva dStream MRI",
                  "description": null,
                  "threat": "Anomalous network communication behavior",
                  "category": "GENERAL",
                  "first_seen": 1637579837,
                  "last_seen": 1637648064,
                  "severity": "Medium",
                  "status": "Open"
                }
              ],
              "total": 23,
              "page": 0
            }
        """
        params = {
            "detected_after": detected_after,
            "mac_address": mac_address,
            "name": name,
            "page": page,
            "page_size": page_size,
            "severity": severity,
            "status": status,
        }
        # remove None values
        params = {k: v for k, v in params.items() if v is not None}
        return self.client._make_request("GET", "/threat/threats", params=params)
