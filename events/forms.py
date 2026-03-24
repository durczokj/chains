from typing import Any

from django import forms
from django.forms import inlineformset_factory

from events.models import (
    Chain,
    CodeTransition,
    CodeType,
    Discontinuation,
    Event,
    Introduction,
    TransitionType,
)
from families.models import Generation


def _active_code_choices(
    code_type: CodeType | None = None,
) -> list[tuple[str | int, str]]:
    """Return choices of currently active codes (end_date = 9999-12-31)."""
    qs = Generation.objects.filter(discontinuation__isnull=True).select_related(
        "introduction__introduction"
    )
    if code_type:
        qs = qs.filter(product_family__code_type=code_type)
    codes = sorted({g.introduction.introduction.introduction_code for g in qs})
    return [("", "---")] + [(c, str(c)) for c in codes]


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ["iso_country_code", "comment"]
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 2}),
        }


class CodeTransitionForm(forms.ModelForm):
    introduction_code = forms.IntegerField(required=False, help_text="Introduction code")
    discontinuation_code = forms.TypedChoiceField(
        required=False,
        coerce=int,
        empty_value=None,
        help_text="Discontinuation code (active codes only)",
    )

    class Meta:
        model = CodeTransition
        fields = ["code_type", "type"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        field = self.fields["discontinuation_code"]
        assert isinstance(field, forms.TypedChoiceField)
        field.choices = _active_code_choices()

    def clean(self) -> dict[str, object] | None:
        cleaned = super().clean()
        if not cleaned:
            return cleaned
        t = cleaned.get("type")
        if t == TransitionType.INTRODUCTION:
            if not cleaned.get("introduction_code"):
                raise forms.ValidationError("Introduction requires an introduction code.")
        elif t == TransitionType.DISCONTINUATION:
            if not cleaned.get("discontinuation_code"):
                raise forms.ValidationError("Discontinuation requires a discontinuation code.")
        elif t == TransitionType.chain:
            if not cleaned.get("introduction_code") or not cleaned.get("discontinuation_code"):
                raise forms.ValidationError(
                    "chain requires both introduction and discontinuation codes."
                )
        return cleaned

    def _is_active_code(self, code: int, code_type: CodeType) -> bool:
        return Generation.objects.filter(
            code=code,
            product_family__code_type=code_type,
            discontinuation__isnull=True,
        ).exists()

    def save(self, commit: bool = True) -> CodeTransition:
        ct: CodeTransition = super().save(commit=commit)
        if commit:
            self._save_subtype(ct)
        return ct

    def _save_subtype(self, ct: CodeTransition) -> None:
        # Delete any existing subtypes when editing
        Introduction.objects.filter(code_transition=ct).delete()
        Discontinuation.objects.filter(code_transition=ct).delete()
        Chain.objects.filter(code_transition=ct).delete()

        if ct.type == TransitionType.INTRODUCTION:
            intro = Introduction(
                code_transition=ct, introduction_code=self.cleaned_data["introduction_code"]
            )
            intro.full_clean()
            intro.save()
        elif ct.type == TransitionType.DISCONTINUATION:
            disco = Discontinuation(
                code_transition=ct, discontinuation_code=self.cleaned_data["discontinuation_code"]
            )
            disco.full_clean()
            disco.save()
        elif ct.type == TransitionType.chain:
            ch = Chain(
                code_transition=ct,
                introduction_code=self.cleaned_data["introduction_code"],
                discontinuation_code=self.cleaned_data["discontinuation_code"],
            )
            ch.full_clean()
            ch.save()


CodeTransitionFormSet = inlineformset_factory(
    Event,
    CodeTransition,
    form=CodeTransitionForm,
    extra=1,
    can_delete=True,
)


class TransitionForm(forms.Form):
    """Standalone form for the frontend two-step flow (one transition per event)."""

    date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "border rounded px-3 py-2 w-full"}),
    )
    type = forms.ChoiceField(
        choices=[("", "---")] + list(TransitionType.choices),
        widget=forms.Select(attrs={"class": "border rounded px-3 py-2 w-full"}),
    )
    code_type = forms.ModelChoiceField(
        queryset=CodeType.objects.all(),
        empty_label="---",
        widget=forms.Select(attrs={"class": "border rounded px-3 py-2 w-full"}),
    )
    introduction_code = forms.IntegerField(required=False)
    discontinuation_code = forms.IntegerField(required=False)

    def clean(self) -> dict[str, object] | None:
        cleaned = super().clean()
        if not cleaned:
            return cleaned
        t = cleaned.get("type")
        if t == TransitionType.INTRODUCTION:
            if not cleaned.get("introduction_code"):
                raise forms.ValidationError("Introduction requires an introduction code.")
        elif t == TransitionType.DISCONTINUATION:
            if not cleaned.get("discontinuation_code"):
                raise forms.ValidationError("Discontinuation requires a discontinuation code.")
        elif t == TransitionType.chain:
            if not cleaned.get("introduction_code") or not cleaned.get("discontinuation_code"):
                raise forms.ValidationError(
                    "chain requires both introduction and discontinuation codes."
                )
        return cleaned

    def _is_active_code(self, code: int, code_type: CodeType) -> bool:
        return Generation.objects.filter(
            code=code,
            product_family__code_type=code_type,
            discontinuation__isnull=True,
        ).exists()

    def save(self, event: Event, existing_transition: CodeTransition | None = None) -> None:
        from events.services import save_event_transitions

        data = self.cleaned_data

        if existing_transition:
            existing_transition.delete()

        save_event_transitions(
            event,
            [
                {
                    "date": data["date"],
                    "type": data["type"],
                    "code_type_id": data["code_type"].pk,
                    "introduction_code": data.get("introduction_code"),
                    "discontinuation_code": data.get("discontinuation_code"),
                }
            ],
        )
