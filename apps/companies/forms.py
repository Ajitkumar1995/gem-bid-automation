from django import forms
from .models import CompanyDocument, CompanyProfile

GENERATED_SIGNATURE_CHOICES = [
    ("experience_declaration", "Experience Criteria"),
    ("past_performance", "Past Performance"),
    ("bidder_turnover", "Bidder Turnover"),
    ("additional_doc_1", "Additional Document 1"),
    ("additional_doc_2", "Additional Document 2"),
    ("atc_certificate", "ATC Certificate"),
    ("boq_specifications", "BoQ Compliance"),
    ("oem_annual_turnover", "OEM Annual Turnover"),
]


class CompanyProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("legal_name", "address", "signatory_name"):
            self.fields[field_name].required = True

    class Meta:
        model = CompanyProfile
        exclude = (
            "owner",
            "created_at",
            "updated_at",
            "signature_image",
            "stamp_image",
            "signature_style",
            "signature_rotation",
            "signature_scale",
            "stamp_rotation",
            "stamp_scale",
            "signature_position_x",
            "signature_position_y",
            "stamp_position_x",
            "stamp_position_y",
            "signature_document_types",
        )
        widgets = {"address": forms.Textarea(attrs={"rows": 3}), "professional_experience_summary": forms.Textarea(attrs={"rows": 3})}


class CompanySignatureForm(forms.ModelForm):
    clear_signature = forms.BooleanField(required=False, label="Remove current saved signature")
    clear_stamp = forms.BooleanField(required=False, label="Remove saved stamp")
    stamp_rotation = forms.DecimalField(
        max_digits=4,
        decimal_places=1,
        required=False,
        min_value=-90,
        max_value=90,
        widget=forms.NumberInput(attrs={"type": "range", "min": "-90", "max": "90", "step": "0.5"}),
    )
    stamp_scale = forms.DecimalField(
        max_digits=3,
        decimal_places=2,
        required=False,
        min_value=0.5,
        max_value=1.5,
        widget=forms.NumberInput(attrs={"type": "range", "min": "0.5", "max": "1.5", "step": "0.05"}),
    )
    signature_position_x = forms.DecimalField(required=False, min_value=0, max_value=100, widget=forms.HiddenInput())
    signature_position_y = forms.DecimalField(required=False, min_value=0, max_value=100, widget=forms.HiddenInput())
    stamp_position_x = forms.DecimalField(required=False, min_value=0, max_value=100, widget=forms.HiddenInput())
    stamp_position_y = forms.DecimalField(required=False, min_value=0, max_value=100, widget=forms.HiddenInput())
    signature_style = forms.ChoiceField(choices=[("blue_ink", "Blue ink (sample format)"), ("black_ink", "Black ink")], label="Signature ink format")
    signature_document_types = forms.MultipleChoiceField(choices=GENERATED_SIGNATURE_CHOICES, required=False, label="Use this signature on generated PDFs", widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = CompanyProfile
        fields = (
            "signature_image",
            "stamp_image",
            "signature_style",
            "signature_rotation",
            "signature_scale",
            "stamp_rotation",
            "stamp_scale",
            "signature_position_x",
            "signature_position_y",
            "stamp_position_x",
            "stamp_position_y",
        )
        labels = {"signature_image": "Signature image (PNG or JPEG)", "stamp_image": "Optional company stamp / seal (PNG or JPEG)"}
        widgets = {
            "signature_image": forms.FileInput(attrs={"accept": ".png,.jpg,.jpeg,image/png,image/jpeg"}),
            "stamp_image": forms.FileInput(attrs={"accept": ".png,.jpg,.jpeg,image/png,image/jpeg"}),
            "signature_rotation": forms.NumberInput(attrs={"type": "range", "min": "-90", "max": "90", "step": "0.5"}),
            "signature_scale": forms.NumberInput(attrs={"type": "range", "min": "0.5", "max": "1.5", "step": "0.05"}),
            "stamp_rotation": forms.NumberInput(attrs={"type": "range", "min": "-90", "max": "90", "step": "0.5"}),
            "stamp_scale": forms.NumberInput(attrs={"type": "range", "min": "0.5", "max": "1.5", "step": "0.05"}),
            "signature_position_x": forms.HiddenInput(),
            "signature_position_y": forms.HiddenInput(),
            "stamp_position_x": forms.HiddenInput(),
            "stamp_position_y": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["signature_document_types"].initial = getattr(self.instance, "signature_document_types", None) or [key for key, _ in GENERATED_SIGNATURE_CHOICES]

    def clean_signature_image(self):
        image = self.cleaned_data.get("signature_image")
        if not image or not hasattr(image, "image"):
            return image
        if image.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Signature image must be 2 MB or smaller.")
        if image.image.format not in {"PNG", "JPEG"}:
            raise forms.ValidationError("Upload a PNG or JPEG signature image.")
        if image.image.width > 4000 or image.image.height > 1500:
            raise forms.ValidationError("Signature image dimensions must not exceed 4000 by 1500 pixels.")
        return image

    def clean_stamp_rotation(self):
        value = self.cleaned_data.get("stamp_rotation")
        return value if value is not None else (getattr(self.instance, "stamp_rotation", None) or 0)

    def clean_stamp_scale(self):
        value = self.cleaned_data.get("stamp_scale")
        return value if value is not None else (getattr(self.instance, "stamp_scale", None) or 1)

    def _clean_position(self, field_name, default):
        value = self.cleaned_data.get(field_name)
        if value is not None:
            return value
        saved_value = getattr(self.instance, field_name, None)
        return self.fields[field_name].to_python(saved_value if saved_value is not None else default)

    def clean_signature_position_x(self):
        return self._clean_position("signature_position_x", 0)

    def clean_signature_position_y(self):
        return self._clean_position("signature_position_y", 50)

    def clean_stamp_position_x(self):
        return self._clean_position("stamp_position_x", 77)

    def clean_stamp_position_y(self):
        return self._clean_position("stamp_position_y", 50)

    def clean_stamp_image(self):
        image = self.cleaned_data.get("stamp_image")
        if not image or not hasattr(image, "image"):
            return image
        if image.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Stamp image must be 2 MB or smaller.")
        if image.image.format not in {"PNG", "JPEG"}:
            raise forms.ValidationError("Upload a PNG or JPEG stamp image.")
        if image.image.width > 4000 or image.image.height > 3000:
            raise forms.ValidationError("Stamp image dimensions must not exceed 4000 by 3000 pixels.")
        return image


class CompanyDocumentForm(forms.ModelForm):
    class Meta:
        model = CompanyDocument
        fields = ("title", "file", "document_type", "entity_name", "assessment_year", "expires_on")
        widgets = {"expires_on": forms.DateInput(attrs={"type": "date"})}

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if uploaded.size > 50 * 1024 * 1024:
            raise forms.ValidationError("Each supporting file must be 50 MB or smaller.")
        if not uploaded.name.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
            raise forms.ValidationError("Upload a PDF or image file.")
        return uploaded
