"""
factory_boy factories for the keywords app.
"""
import factory
from factory.django import DjangoModelFactory

from apps.keywords.models import Keyword


class KeywordFactory(DjangoModelFactory):
    class Meta:
        model = Keyword

    word = factory.Sequence(lambda n: f"keyword{n}")
    is_active = True
