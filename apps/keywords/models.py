from django.db import models


class Keyword(models.Model):
    word = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["word"]
        verbose_name = "Keyword"
        verbose_name_plural = "Keywords"

    def __str__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return f"{self.word} [{status}]"

    def save(self, *args, **kwargs):
        # Normalise: strip whitespace and lowercase
        self.word = self.word.strip().lower()
        super().save(*args, **kwargs)
