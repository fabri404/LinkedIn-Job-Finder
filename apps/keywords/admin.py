from django.contrib import admin
from .models import Keyword


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ["id", "word", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["word"]
    ordering = ["word"]
