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


def enable_for_default_profiles(apps, schema_editor):
    CompanyProfile = apps.get_model("companies", "CompanyProfile")
    for profile in CompanyProfile.objects.all().iterator():
        selected = profile.signature_document_types or []
        if selected == OLD_DEFAULT:
            profile.signature_document_types = [*selected, "non_blacklisting_declaration"]
            profile.save(update_fields=["signature_document_types"])


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0017_adjust_signature_stamp_position_defaults"),
    ]

    operations = [
        migrations.RunPython(enable_for_default_profiles, migrations.RunPython.noop),
    ]
