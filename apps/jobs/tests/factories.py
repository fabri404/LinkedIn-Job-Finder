"""
factory_boy factories for the jobs app.
"""
import factory
from factory.django import DjangoModelFactory

from apps.jobs.models import Job, SearchSession


class SearchSessionFactory(DjangoModelFactory):
    class Meta:
        model = SearchSession

    scroll_duration = factory.Faker("random_int", min=10, max=300)
    status = SearchSession.Status.COMPLETED
    total_found = factory.Faker("random_int", min=0, max=50)
    total_verified = factory.Faker("random_int", min=0, max=20)
    search_mode = "jobs"
    search_keywords = ""


class JobFactory(DjangoModelFactory):
    class Meta:
        model = Job

    session = factory.SubFactory(SearchSessionFactory)
    url = factory.Sequence(
        lambda n: f"https://www.linkedin.com/jobs/view/{1000000 + n}/"
    )
    title = factory.Faker("job")
    company = factory.Faker("company")
    location = factory.Faker("city")
    search_keyword = factory.Faker("word")
    text_preview = factory.Faker("paragraph", nb_sentences=5)
    score = factory.Faker("random_int", min=0, max=15)
    is_verified = factory.Faker("boolean", chance_of_getting_true=50)
    emails_extracted = factory.LazyFunction(list)
