"""
Models for the mailer app.

EmailLog — tracks every CV-email send attempt.
"""
from django.db import models


class EmailLog(models.Model):
    class Language(models.TextChoices):
        SPANISH = "es", "Spanish"
        ENGLISH = "en", "English"

    job = models.ForeignKey(
        "jobs.Job",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_logs",
        db_index=True,
    )
    to_email = models.EmailField(db_index=True)
    language = models.CharField(
        max_length=2,
        choices=Language.choices,
        default=Language.SPANISH,
    )
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)
    success = models.BooleanField(default=False, db_index=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-sent_at"]
        verbose_name = "Email Log"
        verbose_name_plural = "Email Logs"
        indexes = [
            models.Index(fields=["success", "sent_at"]),
        ]

    def __str__(self) -> str:
        status = "OK" if self.success else "FAIL"
        return f"EmailLog #{self.pk} [{status}] → {self.to_email} ({self.sent_at:%Y-%m-%d %H:%M})"
