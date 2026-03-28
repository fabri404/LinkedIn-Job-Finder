from django.urls import path
from .views import EmailLogListView, EmailLogDetailView, ClearEmailLogsView

urlpatterns = [
    path("emails/clear/",      ClearEmailLogsView.as_view(),  name="email-log-clear"),
    path("emails/",            EmailLogListView.as_view(),     name="email-log-list"),
    path("emails/<int:pk>/",   EmailLogDetailView.as_view(),   name="email-log-detail"),
]
