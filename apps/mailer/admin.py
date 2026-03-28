from django.contrib import admin
from .models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ["id", "to_email", "language", "success", "job", "sent_at"]
    list_filter = ["success", "language"]
    search_fields = ["to_email", "subject", "error_message"]
    ordering = ["-sent_at"]
    readonly_fields = ["sent_at"]
    raw_id_fields = ["job"]
