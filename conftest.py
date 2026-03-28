"""
Root conftest.py — shared fixtures for the entire test suite.
"""
import django
import pytest
from django.conf import settings


def pytest_configure(config):
    """Ensure Django settings are configured before anything runs."""
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")


@pytest.fixture
def api_client():
    """Return a DRF APIClient instance (unauthenticated)."""
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def auth_client(db):
    """Return a DRF APIClient authenticated with a test user token."""
    from django.contrib.auth.models import User
    from rest_framework.authtoken.models import Token
    from rest_framework.test import APIClient

    user = User.objects.create_user(
        username="testuser",
        password="testpassword123",
        email="testuser@example.com",
    )
    token, _ = Token.objects.get_or_create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client
