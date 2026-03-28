"""
Root views — serves the single-page frontend.
"""
from django.http import JsonResponse
from django.views.generic import TemplateView

home = TemplateView.as_view(template_name="index.html")


def health(request):
    return JsonResponse({"status": "ok"})
