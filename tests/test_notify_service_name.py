"""Regression tests for CODE_REVIEW_PASS2.md N3.

HA's mobile_app integration registers services as `notify.mobile_app_<device>`.
Bare `notify.<device>` aliases do NOT exist by default. The pre-fix code
stripped the `mobile_app_` prefix, then called `notify.<device>` — yielding
service-not-found and silent notification failure for the entire codebase.

The fix: for `mobile_app_<device>` (the most common HA format), keep the
prefix intact so the resulting service call is `notify.mobile_app_<device>`,
which is what HA actually registers.
"""

import pytest

from app.ha_client import HAClient
from app.config import Config, HAConfig


@pytest.fixture
def client():
    """Minimal HAClient for testing _extract_notify_service_name only."""
    config = Config()
    config.home_assistant = HAConfig(
        url="http://example", token="x", verify_ssl=False
    )
    return HAClient(config)


class TestMobileAppPrefix:
    """The most common HA format: entity_id == 'mobile_app_<device_slug>'.

    HA registers `notify.mobile_app_<device>` — so the service-name returned
    here MUST keep the prefix intact.
    """

    def test_mobile_app_keeps_prefix(self, client):
        assert client._extract_notify_service_name(
            "mobile_app_iphone_van_nicolas_2"
        ) == "mobile_app_iphone_van_nicolas_2"

    def test_mobile_app_kitchen(self, client):
        assert client._extract_notify_service_name(
            "mobile_app_kitchen"
        ) == "mobile_app_kitchen"

    def test_mobile_app_with_trailing_whitespace(self, client):
        assert client._extract_notify_service_name(
            "  mobile_app_hall  "
        ) == "mobile_app_hall"


class TestNotifyDomainPrefix:
    """`notify.<service>` — user explicitly typed the domain. Strip it."""

    def test_notify_dot_strip(self, client):
        # notify.mobile_app_<device> -> mobile_app_<device> (preserves the
        # service name underneath; final HA call is notify.mobile_app_<device>)
        assert client._extract_notify_service_name(
            "notify.mobile_app_iphone_van_nicolas_2"
        ) == "mobile_app_iphone_van_nicolas_2"

    def test_notify_dot_custom_alias(self, client):
        # User has a hand-rolled `notify.iphone` alias — return 'iphone'
        assert client._extract_notify_service_name(
            "notify.iphone"
        ) == "iphone"


class TestPlainServiceName:
    """No recognised prefix — treat as literal service name (notify.<name>)."""

    def test_bare_service_name(self, client):
        assert client._extract_notify_service_name("iphone") == "iphone"

    def test_bare_alphanumeric(self, client):
        assert client._extract_notify_service_name(
            "telegram_bot"
        ) == "telegram_bot"


class TestEmptyOrNone:
    def test_empty_string(self, client):
        assert client._extract_notify_service_name("") == ""

    def test_none(self, client):
        assert client._extract_notify_service_name(None) == ""

    def test_whitespace_only(self, client):
        # strip() turns this into "" -> empty
        assert client._extract_notify_service_name("   ") == ""


class TestMobileAppDotForm:
    """`mobile_app.<device>` (literal dot, atypical HA format).

    Treat the same as `mobile_app_<device>`: keep the prefix in slug form
    so the final HA call lands on `notify.mobile_app_<device>`.
    """

    def test_mobile_app_dot_normalises_to_underscore(self, client):
        assert client._extract_notify_service_name(
            "mobile_app.kitchen"
        ) == "mobile_app_kitchen"


class TestUnknownDottedEntity:
    """CR-P5: Pre-rewrite, the resolver had a final "split on dot and return
    the last segment" fallback. Removing it broke any user-configured
    `switch.foo` or `notification.bar` form — `notify.switch.foo` is not a
    valid HA service name. Restore that fallback."""

    def test_switch_dot_entity_returns_suffix(self, client):
        """A typo like `switch.kitchen` for a notify entity should yield
        `kitchen` (still wrong-ish but a recoverable HA error), NOT the
        literal `switch.kitchen` which produces `notify.switch.kitchen` —
        a parser error."""
        assert client._extract_notify_service_name(
            "switch.kitchen"
        ) == "kitchen"

    def test_multiple_dots_returns_last_segment(self, client):
        assert client._extract_notify_service_name(
            "binary_sensor.front_door.contact"
        ) == "contact"


class TestRegression_PreFixBehaviour:
    """Pin the bug: pre-fix, mobile_app_<device> was wrongly stripped."""

    def test_does_not_strip_mobile_app_prefix(self, client):
        """The pre-fix code returned 'iphone_van_nicolas_2' which produces a
        nonexistent `notify.iphone_van_nicolas_2`. Must NOT happen anymore."""
        result = client._extract_notify_service_name(
            "mobile_app_iphone_van_nicolas_2"
        )
        assert result != "iphone_van_nicolas_2", (
            "Pre-fix bug: stripped mobile_app_ prefix would yield a "
            "service name that doesn't exist in HA."
        )
