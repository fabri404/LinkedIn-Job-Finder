"""
Root URL configuration.
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.authtoken.views import obtain_auth_token
from .views import home, health

urlpatterns = [
    # Frontend SPA — served at the root
    path("", home, name="home"),
    path("api/health/", health, name="health"),
    path("admin/", admin.site.urls),
    # Token auth endpoint: POST /api/auth/token/
    path("api/auth/token/", obtain_auth_token, name="api-token-auth"),
    # App routers
    path("api/", include("apps.jobs.urls")),
    path("api/", include("apps.keywords.urls")),
    path("api/", include("apps.mailer.urls")),
]
