from rest_framework import generics
from .models import Keyword
from .serializers import KeywordSerializer


class KeywordListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/keywords/ — list all keywords (active + inactive)
    POST /api/keywords/ — create a new keyword
    """
    queryset = Keyword.objects.all()
    serializer_class = KeywordSerializer
    filterset_fields = ["is_active"]
    search_fields = ["word"]


class KeywordDestroyView(generics.DestroyAPIView):
    """DELETE /api/keywords/{id}/ — remove a keyword."""
    queryset = Keyword.objects.all()
    serializer_class = KeywordSerializer
