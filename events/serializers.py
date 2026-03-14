from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers

from events.models import (
    CodeTransition,
    CodeType,
    Discontinuation,
    Event,
    Introduction,
    Pipo,
    TransitionType,
)


class CodeTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodeType
        fields = ["id", "type"]


class IntroductionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Introduction
        fields = ["id", "pi_code"]


class DiscontinuationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discontinuation
        fields = ["id", "po_code"]


class PipoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pipo
        fields = ["id", "pi_code", "po_code"]


class CodeTransitionSerializer(serializers.ModelSerializer):
    introduction = IntroductionSerializer(read_only=True)
    discontinuation = DiscontinuationSerializer(read_only=True)
    pipo = PipoSerializer(read_only=True)
    code_type_id = serializers.CharField()

    class Meta:
        model = CodeTransition
        fields = [
            "id", "code_type_id", "type",
            "introduction", "discontinuation", "pipo",
        ]


class CodeTransitionWriteSerializer(serializers.Serializer):
    code_type_id = serializers.CharField()
    type = serializers.ChoiceField(choices=TransitionType.choices)
    pi_code = serializers.IntegerField(required=False)
    po_code = serializers.IntegerField(required=False)
    proxy_introduction = serializers.BooleanField(required=False, default=False)
    proxy_po = serializers.BooleanField(required=False, default=False)
    discontinue_po = serializers.BooleanField(required=False, default=True)

    def validate_code_type_id(self, value):
        if not CodeType.objects.filter(pk=value).exists():
            raise serializers.ValidationError(f"Code type '{value}' does not exist.")
        return value

    def validate(self, data):
        t = data["type"]
        if t == TransitionType.INTRODUCTION:
            if "pi_code" not in data:
                raise serializers.ValidationError("Introduction requires 'pi_code'.")
        elif t == TransitionType.DISCONTINUATION:
            if "po_code" not in data:
                raise serializers.ValidationError("Discontinuation requires 'po_code'.")
        elif t == TransitionType.PIPO:
            if "pi_code" not in data or "po_code" not in data:
                raise serializers.ValidationError("PIPO requires 'pi_code' and 'po_code'.")
        return data


class EventSerializer(serializers.ModelSerializer):
    transitions = CodeTransitionSerializer(many=True, read_only=True)
    transitions_write = CodeTransitionWriteSerializer(many=True, write_only=True, source="transitions")

    class Meta:
        model = Event
        fields = [
            "id", "date", "iso_country_code", "comment",
            "transitions", "transitions_write",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def create(self, validated_data):
        transitions_data = validated_data.pop("transitions", [])
        with transaction.atomic():
            event = Event.objects.create(**validated_data)
            self._create_transitions(event, transitions_data)
        return event

    def update(self, instance, validated_data):
        transitions_data = validated_data.pop("transitions", None)
        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            if transitions_data is not None:
                instance.transitions.all().delete()
                self._create_transitions(instance, transitions_data)
        return instance

    def _create_transitions(self, event, transitions_data):
        from events.services import create_transition

        for td in transitions_data:
            try:
                create_transition(
                    event,
                    type=td["type"],
                    code_type_id=td["code_type_id"],
                    pi_code=td.get("pi_code"),
                    po_code=td.get("po_code"),
                    proxy_introduction=td.get("proxy_introduction", False),
                    proxy_po=td.get("proxy_po", False),
                    discontinue_po=td.get("discontinue_po", False),
                )
            except DjangoValidationError as exc:
                raise serializers.ValidationError(
                    exc.message_dict if hasattr(exc, "message_dict") else exc.messages
                )
            except IntegrityError as exc:
                raise serializers.ValidationError(str(exc))
            except ObjectDoesNotExist as exc:
                raise serializers.ValidationError(str(exc))
