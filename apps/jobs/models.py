"""
Models for the jobs app.

SearchSession — tracks a single scraping run.
Job           — a LinkedIn post detected as a potential job offer.
"""
from django.db import models


class SearchSession(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    scroll_duration = models.PositiveIntegerField(
        help_text="How many seconds the scraper scrolled the feed."
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    total_found = models.PositiveIntegerField(
        default=0,
        help_text="Posts that matched keyword filter.",
    )
    total_verified = models.PositiveIntegerField(
        default=0,
        help_text="Posts confirmed as real job offers after score analysis.",
    )
    search_mode = models.CharField(
        max_length=10,
        default="jobs",
        choices=[("jobs", "LinkedIn Jobs Search"), ("feed", "Feed Scan")],
        help_text="Whether to search LinkedIn Jobs directly or scan the general feed.",
    )
    search_keywords = models.TextField(
        blank=True,
        default="",
        help_text="Comma-separated keywords used during this session.",
    )

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Search Session"
        verbose_name_plural = "Search Sessions"

    def __str__(self) -> str:
        return f"Session #{self.pk} [{self.status}] — {self.started_at:%Y-%m-%d %H:%M}"

    @property
    def duration_seconds(self) -> int | None:
        """Wall-clock seconds from start to finish, or None if still running."""
        if self.finished_at and self.started_at:
            return int((self.finished_at - self.started_at).total_seconds())
        return None


class Job(models.Model):
    session = models.ForeignKey(
        SearchSession,
        on_delete=models.CASCADE,
        related_name="jobs",
        db_index=True,
    )
    url = models.URLField(max_length=512, unique=True)
    title = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text="Job title extracted from LinkedIn job card.",
    )
    company = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Company name extracted from LinkedIn job card.",
    )
    location = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Job location extracted from LinkedIn job card.",
    )
    search_keyword = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="The keyword that led to finding this job.",
    )
    text_preview = models.TextField(
        blank=True,
        help_text="First ~2000 chars of the post/job text collected during scraping.",
    )
    score = models.IntegerField(
        default=0,
        help_text="Score produced by JobAnalyzer. Higher means more likely a real job post.",
        db_index=True,
    )
    is_verified = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True when score >= threshold and the post was confirmed as a real offer.",
    )
    found_at = models.DateTimeField(auto_now_add=True, db_index=True)
    emails_extracted = models.JSONField(
        default=list,
        blank=True,
        help_text="List of recruiter emails found in the post text.",
    )

    class Meta:
        ordering = ["-found_at"]
        verbose_name = "Job"
        verbose_name_plural = "Jobs"
        indexes = [
            models.Index(fields=["found_at"]),
            models.Index(fields=["is_verified", "found_at"]),
        ]

    def __str__(self) -> str:
        verified = "verified" if self.is_verified else "unverified"
        return f"Job #{self.pk} [{verified}] score={self.score}"
