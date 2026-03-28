from django.urls import path
from .views import (
    StartSearchView,
    SearchSessionListView,
    SearchSessionDetailView,
    JobListView,
    JobDetailView,
    SendEmailView,
    ClearJobsView,
    ClearSessionsView,
)

urlpatterns = [
    # Search sessions
    path("searches/start/",   StartSearchView.as_view(),         name="search-start"),
    path("searches/clear/",   ClearSessionsView.as_view(),       name="search-clear"),
    path("searches/",         SearchSessionListView.as_view(),    name="search-list"),
    path("searches/<int:pk>/", SearchSessionDetailView.as_view(), name="search-detail"),
    # Jobs
    path("jobs/clear/",          ClearJobsView.as_view(),    name="job-clear"),
    path("jobs/",                JobListView.as_view(),       name="job-list"),
    path("jobs/<int:pk>/",       JobDetailView.as_view(),     name="job-detail"),
    path("jobs/<int:pk>/send-email/", SendEmailView.as_view(), name="job-send-email"),
]
