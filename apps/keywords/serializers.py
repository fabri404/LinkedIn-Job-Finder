from rest_framework import serializers
from .models import Keyword


class KeywordSerializer(serializers.ModelSerializer):
    class Meta:
        model = Keyword
        fields = ["id", "word", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_word(self, value: str) -> str:
        normalised = value.strip().lower()
        if not normalised:
            raise serializers.ValidationError("Keyword cannot be blank.")
        return normalised
