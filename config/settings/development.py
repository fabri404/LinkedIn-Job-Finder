"""
Development settings — DEBUG on, SQLite database.
"""
from .base import *  # noqa: F401, F403

DEBUG = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

# Allow all origins in development
CORS_ALLOW_ALL_ORIGINS = True

# Show emails in the console instead of sending them during development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Disable auth for easier local testing (override in specific tests)
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}
