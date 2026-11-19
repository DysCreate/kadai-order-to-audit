"""pytest configuration for Kadai backend tests."""

import pytest


@pytest.fixture(scope="session")
def django_db_setup():
    """Use the test database configured in config.settings.test."""
    pass
