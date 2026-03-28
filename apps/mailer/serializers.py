"""
Serializers for the mailer app.
"""
from rest_framework import serializers
from .models import EmailLog


class EmailLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailLog
        fields = [
            "id",
            "job",
            "to_email",
            "language",
            "subject",
            "success",
            "error_message",
            "sent_at",
        ]
        read_only_fields = fields


class SendEmailRequestSerializer(serializers.Serializer):
    to_email = serializers.EmailField(help_text="Recipient email address.")
    language = serializers.ChoiceField(
        choices=EmailLog.Language.choices,
        default=EmailLog.Language.SPANISH,
        help_text="Language for the email body ('es' or 'en').",
    )
