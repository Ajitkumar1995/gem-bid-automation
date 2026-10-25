from django import forms
from django.forms import inlineformset_factory
from .models import BidBOQItem, BidPreparation


class BidPreparationForm(forms.ModelForm):
    apply_mse_purchase_preference = forms.TypedChoiceField(
        choices=(("False", "No"), ("True", "Yes")),
        coerce=lambda value: value == "True",
        widget=forms.RadioSelect,
        required=False,
        label="Apply for MSE purchase preference",
    )

    class Meta:
        model = BidPreparation
        exclude = ("bid", "updated_at", "recipient_title")
        widgets = {
            "buyer_address": forms.Textarea(attrs={"rows": 2}),
            "beneficiary_details": forms.Textarea(attrs={"rows": 4}),
            "payment_note": forms.Textarea(attrs={"rows": 2}),
            "bid_date": forms.DateInput(attrs={"type": "date"}), "invoice_address": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {"beneficiary_details": "To / Beneficiary details"}
        help_texts = {
            "beneficiary_details": "Extracted from the uploaded bid PDF. Review and edit these recipient details before generating documents."
        }


class BidBOQItemForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.bidder_response:
            self.initial["bidder_response"] = "Complied"

    class Meta:
        model = BidBOQItem
        fields = ("sort_order", "description", "quantity", "unit", "bidder_response")


class CustomDocumentForm(forms.Form):
    title = forms.CharField(max_length=255, label="Custom document title", required=False)
    content = forms.CharField(
        max_length=100000,
        label="Document template text",
        widget=forms.Textarea(attrs={"rows": 12}),
        help_text="This text is saved as your reusable template. Optional dynamic tokens: {{to}}, {{bid_number}}, {{bid_title}}, {{buyer_name}}, {{buyer_department}}, {{company_name}}, {{signatory_name}}, and {{date}}.",
        required=False,
    )

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if self.data.get("action") == "create_custom" and not title:
            raise forms.ValidationError("Enter a custom document title.")
        return title

    def clean_content(self):
        content = self.cleaned_data["content"].strip()
        if self.data.get("action") == "create_custom" and not content:
            raise forms.ValidationError("Enter document template text.")
        return content


BidBOQFormSet = inlineformset_factory(BidPreparation, BidBOQItem, form=BidBOQItemForm, extra=0, can_delete=True)
