from django.db import migrations


OLD_DEFAULT = [
    "experience_declaration",
    "past_performance",
    "bidder_turnover",
    "additional_doc_1",
    "additional_doc_2",
    "atc_certificate",
    "boq_specifications",
    "oem_annual_turnover",
]
PREVIOUS_DEFAULT = [*OLD_DEFAULT, "non_blacklisting_declaration"]
ALL_BUILTIN_PDFS = [
    "experience_declaration",
    "past_performance",
    "bidder_turnover",
    "undertaking",
    "declaration",
    "authorization_letter",
    "technical_compliance",
    "non_blacklisting_declaration",
    "turnover_declaration",
    "mse_startup_declaration",
    "additional_doc_1",
    "additional_doc_2",
    "atc_certificate",
    "boq_specifications",
    "oem_annual_turnover",
]


def enable_all_builtin_pdfs_for_default_profiles(apps, schema_editor):
    CompanyProfile = apps.get_model("companies", "CompanyProfile")
    for profile in CompanyProfile.objects.all().iterator():
        selected = profile.signature_document_types or []
        if selected in (OLD_DEFAULT, PREVIOUS_DEFAULT):
            profile.signature_document_types = ALL_BUILTIN_PDFS
            profile.save(update_fields=["signature_document_types"])


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0018_enable_non_blacklisting_signature"),
    ]

    operations = [
        migrations.RunPython(enable_all_builtin_pdfs_for_default_profiles, migrations.RunPython.noop),
    ]
