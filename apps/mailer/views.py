"""
Views for the mailer app.
"""
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import EmailLog
from .serializers import EmailLogSerializer


class ClearEmailLogsView(APIView):
    """DELETE /api/emails/clear/ — elimina todos los logs de emails."""

    def delete(self, request: Request) -> Response:
        count, _ = EmailLog.objects.all().delete()
        return Response({"deleted": count}, status=status.HTTP_200_OK)


class EmailLogListView(generics.ListAPIView):
    """
    GET /api/emails/ — paginated list of all email send attempts.

    Supports filtering by:
      ?success=true|false
      ?job=<job_id>
    """
    serializer_class = EmailLogSerializer
    filterset_fields = ["success", "job"]
    ordering_fields = ["sent_at"]

    def get_queryset(self):
        return EmailLog.objects.select_related("job").all()


class EmailLogDetailView(generics.RetrieveAPIView):
    """GET /api/emails/{id}/ — detail of a single email log entry."""
    serializer_class = EmailLogSerializer

    def get_queryset(self):
        return EmailLog.objects.select_related("job").all()
