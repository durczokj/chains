from django import forms
from django.forms import inlineformset_factory

from events.models import (
    CodeTransition,
    CodeType,
    Discontinuation,
    Event,
    Introduction,
    Pipo,
    TransitionType,
)
from lifecycles.models import Generation


def _active_code_choices(code_type=None):
    """Return choices of currently active codes (end_date = 9999-12-31)."""
    qs = Generation.objects.filter(end_date__year=9999)
    if code_type:
        qs = qs.filter(product_family__code_type=code_type)
    codes = sorted(qs.values_list("code", flat=True).distinct())
    return [("", "---")] + [(c, str(c)) for c in codes]


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ["date", "iso_country_code", "comment"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "comment": forms.Textarea(attrs={"rows": 2}),
        }


class CodeTransitionForm(forms.ModelForm):
    pi_code = forms.IntegerField(required=False, help_text="Phase-In code")
    po_code = forms.TypedChoiceField(
        required=False, coerce=int, empty_value=None,
        help_text="Phase-Out code (active codes only)",
    )
    discontinue_po = forms.BooleanField(required=False, initial=True, help_text="Discontinue PO code")

    class Meta:
        model = CodeTransition
        fields = ["code_type", "type"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["po_code"].choices = _active_code_choices()

    def clean(self):
        cleaned = super().clean()
        t = cleaned.get("type")
        if t == TransitionType.INTRODUCTION:
            if not cleaned.get("pi_code"):
                raise forms.ValidationError("Introduction requires a PI code.")
        elif t == TransitionType.DISCONTINUATION:
            if not cleaned.get("po_code"):
                raise forms.ValidationError("Discontinuation requires a PO code.")
        elif t == TransitionType.PIPO:
            if not cleaned.get("pi_code") or not cleaned.get("po_code"):
                raise forms.ValidationError("PIPO requires both PI and PO codes.")
        return cleaned

    def _is_active_code(self, code, code_type):
        return Generation.objects.filter(
            code=code,
            product_family__code_type=code_type,
            end_date__year=9999,
        ).exists()

    def save(self, commit=True):
        ct = super().save(commit=commit)
        if commit:
            self._save_subtype(ct)
        return ct

    def _save_subtype(self, ct):
        # Delete any existing subtypes when editing
        Introduction.objects.filter(code_transition=ct).delete()
        Discontinuation.objects.filter(code_transition=ct).delete()
        Pipo.objects.filter(code_transition=ct).delete()

        if ct.type == TransitionType.INTRODUCTION:
            intro = Introduction(code_transition=ct, pi_code=self.cleaned_data["pi_code"])
            intro.full_clean()
            intro.save()
        elif ct.type == TransitionType.DISCONTINUATION:
            disco = Discontinuation(code_transition=ct, po_code=self.cleaned_data["po_code"])
            disco.full_clean()
            disco.save()
        elif ct.type == TransitionType.PIPO:
            pipo = Pipo(
                code_transition=ct,
                pi_code=self.cleaned_data["pi_code"],
                po_code=self.cleaned_data["po_code"],
            )
            pipo.full_clean()
            pipo.save()
            if self.cleaned_data.get("discontinue_po", False):
                disco_ct = CodeTransition.objects.create(
                    event=ct.event,
                    code_type=ct.code_type,
                    type=TransitionType.DISCONTINUATION,
                )
                Discontinuation.objects.create(
                    code_transition=disco_ct,
                    po_code=self.cleaned_data["po_code"],
                )


CodeTransitionFormSet = inlineformset_factory(
    Event,
    CodeTransition,
    form=CodeTransitionForm,
    extra=1,
    can_delete=True,
)


class TransitionForm(forms.Form):
    """Standalone form for the frontend two-step flow (one transition per event)."""

    type = forms.ChoiceField(
        choices=[("" , "---")] + list(TransitionType.choices),
        widget=forms.Select(attrs={"class": "border rounded px-3 py-2 w-full"}),
    )
    code_type = forms.ModelChoiceField(
        queryset=CodeType.objects.all(),
        empty_label="---",
        widget=forms.Select(attrs={"class": "border rounded px-3 py-2 w-full"}),
    )
    pi_code = forms.IntegerField(required=False)
    po_code = forms.IntegerField(required=False)
    proxy_introduction = forms.BooleanField(required=False, initial=False)
    proxy_po = forms.BooleanField(required=False, initial=False)
    discontinue_po = forms.BooleanField(required=False, initial=True)

    def clean(self):
        cleaned = super().clean()
        t = cleaned.get("type")
        if t == TransitionType.INTRODUCTION:
            if not cleaned.get("pi_code"):
                raise forms.ValidationError("Introduction requires a PI code.")
        elif t == TransitionType.DISCONTINUATION:
            if not cleaned.get("po_code"):
                raise forms.ValidationError("Discontinuation requires a PO code.")
        elif t == TransitionType.PIPO:
            if not cleaned.get("pi_code") or not cleaned.get("po_code"):
                raise forms.ValidationError("PIPO requires both PI and PO codes.")
        return cleaned

    def _is_active_code(self, code, code_type):
        return Generation.objects.filter(
            code=code,
            product_family__code_type=code_type,
            end_date__year=9999,
        ).exists()

    def save(self, event, existing_transition=None):
        from events.services import create_transition

        data = self.cleaned_data

        if existing_transition:
            # Delete old transition (and subtypes via cascade) before re-creating
            existing_transition.delete()

        return create_transition(
            event,
            type=data["type"],
            code_type_id=data["code_type"].pk,
            pi_code=data.get("pi_code"),
            po_code=data.get("po_code"),
            proxy_introduction=data.get("proxy_introduction", False),
            proxy_po=data.get("proxy_po", False),
            discontinue_po=data.get("discontinue_po", False),
        )
