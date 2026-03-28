"""
Serializers for the jobs app.
"""
from rest_framework import serializers
from .models import Job, SearchSession


class JobSerializer(serializers.ModelSerializer):
    emails_count = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            "id",
            "url",
            "title",
            "company",
            "location",
            "search_keyword",
            "text_preview",
            "score",
            "is_verified",
            "found_at",
            "emails_extracted",
            "emails_count",
            "session",
        ]
        read_only_fields = fields

    def get_emails_count(self, obj: Job) -> int:
        return len(obj.emails_extracted) if obj.emails_extracted else 0


class JobDetailSerializer(JobSerializer):
    """Extended serializer that includes score breakdown when available."""

    score_reasons = serializers.SerializerMethodField()

    class Meta(JobSerializer.Meta):
        fields = JobSerializer.Meta.fields + ["score_reasons"]

    def get_score_reasons(self, obj: Job) -> list[str]:
        # The reasons are stored in context when the view passes them
        return self.context.get("score_reasons", [])


class SearchSessionSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.ReadOnlyField()

    class Meta:
        model = SearchSession
        fields = [
            "id",
            "started_at",
            "finished_at",
            "scroll_duration",
            "search_mode",
            "search_keywords",
            "status",
            "total_found",
            "total_verified",
            "duration_seconds",
        ]
        read_only_fields = [
            "id",
            "started_at",
            "finished_at",
            "status",
            "total_found",
            "total_verified",
            "duration_seconds",
            "search_keywords",
        ]


class SearchSessionDetailSerializer(SearchSessionSerializer):
    jobs = JobSerializer(many=True, read_only=True)

    class Meta(SearchSessionSerializer.Meta):
        fields = SearchSessionSerializer.Meta.fields + ["jobs"]


class StartSearchSerializer(serializers.Serializer):
    scroll_duration = serializers.IntegerField(
        min_value=5,
        max_value=600,
        default=60,
        required=False,
        help_text="Seconds to scroll the LinkedIn feed (5–600). Only used in 'feed' mode.",
    )
    search_mode = serializers.ChoiceField(
        choices=["jobs", "feed"],
        default="jobs",
        required=False,
        help_text="'jobs' busca en LinkedIn Jobs directamente. 'feed' escanea el feed general.",
    )
