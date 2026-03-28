from django.urls import path
from .views import KeywordListCreateView, KeywordDestroyView

urlpatterns = [
    path("keywords/", KeywordListCreateView.as_view(), name="keyword-list-create"),
    path("keywords/<int:pk>/", KeywordDestroyView.as_view(), name="keyword-destroy"),
]
