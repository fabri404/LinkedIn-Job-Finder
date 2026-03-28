from django.contrib import admin
from .models import Job, SearchSession


@admin.register(SearchSession)
class SearchSessionAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "scroll_duration", "total_found", "total_verified", "started_at"]
    list_filter = ["status"]
    ordering = ["-started_at"]
    readonly_fields = ["started_at", "finished_at"]


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["id", "is_verified", "score", "session", "found_at", "url"]
    list_filter = ["is_verified", "session"]
    search_fields = ["url", "text_preview"]
    ordering = ["-found_at"]
    readonly_fields = ["found_at"]
