"""
Views for the jobs app.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Job, SearchSession
from .serializers import (
    JobDetailSerializer,
    JobSerializer,
    SearchSessionDetailSerializer,
    SearchSessionSerializer,
    StartSearchSerializer,
)
from .services import JobAnalyzer


# ─── Search Sessions ─────────────────────────────────────────────────────────

class SearchSessionListView(generics.ListAPIView):
    """GET /api/searches/ — paginated history of all search sessions."""

    queryset = SearchSession.objects.prefetch_related("jobs").all()
    serializer_class = SearchSessionSerializer


class SearchSessionDetailView(generics.RetrieveAPIView):
    """GET /api/searches/{id}/ — session detail with all jobs found."""

    queryset = SearchSession.objects.prefetch_related("jobs").all()
    serializer_class = SearchSessionDetailSerializer


class StartSearchView(APIView):
    """
    POST /api/searches/start/

    Body: { "scroll_duration": 60 }

    Creates a SearchSession and launches the scraper in a background thread
    so the HTTP response is returned immediately.
    """

    def post(self, request: Request) -> Response:
        # Guard: reject if there's already a session running
        if SearchSession.objects.filter(status=SearchSession.Status.RUNNING).exists():
            return Response(
                {"error": "Ya hay una sesión de búsqueda en curso. Esperá a que termine antes de iniciar otra."},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = StartSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session = SearchSession.objects.create(
            scroll_duration=serializer.validated_data["scroll_duration"],
            search_mode=serializer.validated_data.get("search_mode", "jobs"),
            status=SearchSession.Status.PENDING,
        )

        # Run scraper asynchronously so the client is not blocked
        thread = threading.Thread(
            target=self._run_scraper,
            args=(session.pk,),
            daemon=True,
        )
        thread.start()

        return Response(
            SearchSessionSerializer(session).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @staticmethod
    def _run_scraper(session_id: int) -> None:
        from .services import ScraperService
        try:
            ScraperService(session_id).run()
        except Exception as exc:  # noqa: BLE001
            # Error is already persisted on the session
            logger.error("[ScraperService] session=%s failed: %s", session_id, exc)


# ─── Jobs ────────────────────────────────────────────────────────────────────

class JobListView(generics.ListAPIView):
    """GET /api/jobs/ — all jobs, filterable by is_verified, session."""

    serializer_class = JobSerializer
    filterset_fields = ["is_verified", "session"]
    search_fields = ["text_preview", "url"]
    ordering_fields = ["found_at", "score"]

    def get_queryset(self):
        return (
            Job.objects.select_related("session")
            .all()
        )


class JobDetailView(generics.RetrieveAPIView):
    """GET /api/jobs/{id}/ — job detail with score breakdown re-computed."""

    serializer_class = JobDetailSerializer

    def get_queryset(self):
        return Job.objects.select_related("session").all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        job = get_object_or_404(Job, pk=self.kwargs["pk"])
        if job.text_preview:
            analysis = JobAnalyzer().analyze(job.text_preview)
            context["score_reasons"] = analysis["reasons"]
        return context


class ClearJobsView(APIView):
    """DELETE /api/jobs/clear/ — elimina todos los jobs."""

    def delete(self, request: Request) -> Response:
        from .models import Job
        count, _ = Job.objects.all().delete()
        return Response({"deleted": count}, status=status.HTTP_200_OK)


class ClearSessionsView(APIView):
    """DELETE /api/searches/clear/ — elimina todas las sesiones (y sus jobs en cascada)."""

    def delete(self, request: Request) -> Response:
        count, _ = SearchSession.objects.all().delete()
        return Response({"deleted": count}, status=status.HTTP_200_OK)


class SendEmailView(APIView):
    """
    POST /api/jobs/{id}/send-email/

    Body: { "to_email": "recruiter@company.com", "language": "es" }
    Sends the CV email and records an EmailLog entry.
    """

    def post(self, request: Request, pk: int) -> Response:
        from apps.mailer.services import MailerService
        from apps.mailer.serializers import SendEmailRequestSerializer

        job = get_object_or_404(Job, pk=pk)

        req_serializer = SendEmailRequestSerializer(data=request.data)
        req_serializer.is_valid(raise_exception=True)

        to_email = req_serializer.validated_data["to_email"]
        language = req_serializer.validated_data["language"]

        log = MailerService.send_cv(job=job, to_email=to_email, language=language)

        if log.success:
            return Response({"detail": f"Email sent to {to_email}."}, status=status.HTTP_200_OK)
        return Response(
            {"detail": "Failed to send email.", "error": log.error_message},
            status=status.HTTP_502_BAD_GATEWAY,
        )
