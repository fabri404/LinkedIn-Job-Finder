"""
factory_boy factories for the mailer app.
"""
import factory
from factory.django import DjangoModelFactory

from apps.mailer.models import EmailLog
from apps.jobs.tests.factories import JobFactory


class EmailLogFactory(DjangoModelFactory):
    class Meta:
        model = EmailLog

    job = factory.SubFactory(JobFactory)
    to_email = factory.Faker("email")
    language = EmailLog.Language.SPANISH
    subject = factory.Faker("sentence", nb_words=6)
    body = factory.Faker("paragraph", nb_sentences=4)
    success = True
    error_message = ""
