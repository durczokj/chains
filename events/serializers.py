from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import serializers

from events.models import (
    Chain,
    CodeTransition,
    CodeType,
    Country,
    Discontinuation,
    Event,
    Introduction,
    TransitionType,
)


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ["code", "name", "families_dirty"]
        read_only_fields = ["families_dirty"]


class CodeTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodeType
        fields = ["id", "type"]


class IntroductionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Introduction
        fields = ["id", "introduction_code"]


class DiscontinuationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discontinuation
        fields = ["id", "discontinuation_code"]


class ChainSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chain
        fields = ["id", "introduction_code", "discontinuation_code"]


class CodeTransitionSerializer(serializers.ModelSerializer):
    introduction = IntroductionSerializer(read_only=True)
    discontinuation = DiscontinuationSerializer(read_only=True)
    chain = ChainSerializer(read_only=True)
    code_type_id = serializers.CharField()

    class Meta:
        model = CodeTransition
        fields = [
            "id",
            "code_type_id",
            "type",
            "date",
            "introduction",
            "discontinuation",
            "chain",
        ]


class CodeTransitionWriteSerializer(serializers.Serializer):
    code_type_id = serializers.CharField()
    type = serializers.ChoiceField(choices=TransitionType.choices)
    date = serializers.DateField()
    introduction_code = serializers.IntegerField(required=False)
    discontinuation_code = serializers.IntegerField(required=False)

    def validate_code_type_id(self, value: str) -> str:
        if not CodeType.objects.filter(pk=value).exists():
            raise serializers.ValidationError(f"Code type '{value}' does not exist.")
        return value

    def validate(self, data: dict[str, object]) -> dict[str, object]:
        t = data["type"]
        if t == TransitionType.INTRODUCTION:
            if "introduction_code" not in data:
                raise serializers.ValidationError("Introduction requires 'introduction_code'.")
        elif t == TransitionType.DISCONTINUATION:
            if "discontinuation_code" not in data:
                raise serializers.ValidationError(
                    "Discontinuation requires 'discontinuation_code'."
                )
        elif t == TransitionType.chain:
            if "introduction_code" not in data or "discontinuation_code" not in data:
                raise serializers.ValidationError(
                    "chain requires 'introduction_code' and 'discontinuation_code'."
                )
        return data


class EventSerializer(serializers.ModelSerializer):
    transitions = CodeTransitionSerializer(many=True, read_only=True)
    transitions_write = CodeTransitionWriteSerializer(
        many=True, write_only=True, source="transitions"
    )

    class Meta:
        model = Event
        fields = [
            "id",
            "iso_country_code",
            "comment",
            "transitions",
            "transitions_write",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def create(self, validated_data: dict[str, Any]) -> Event:
        transitions_data: list[dict[str, Any]] = validated_data.pop("transitions", [])
        event = Event.objects.create(**validated_data)
        self._save_transitions(event, transitions_data)
        return event

    def update(self, instance: Event, validated_data: dict[str, Any]) -> Event:
        transitions_data: list[dict[str, Any]] | None = validated_data.pop("transitions", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if transitions_data is not None:
            self._save_transitions(instance, transitions_data)
        return instance

    def _save_transitions(self, event: Event, transitions_data: list[dict[str, Any]]) -> None:
        from events.services import save_event_transitions

        try:
            save_event_transitions(event, transitions_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        except IntegrityError as exc:
            raise serializers.ValidationError(str(exc))
        except ObjectDoesNotExist as exc:
            raise serializers.ValidationError(str(exc))
