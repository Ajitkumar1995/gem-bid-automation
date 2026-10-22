from django.db import migrations


PREVIOUS_BUILTIN_PDFS = {
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
}
NEW_DOCUMENT_TYPE = "msme_turnover_exemption"


def enable_new_document_marks(apps, schema_editor):
    CompanyProfile = apps.get_model("companies", "CompanyProfile")
    for profile in CompanyProfile.objects.all().iterator():
        updates = []
        for field_name in ("signature_document_types", "stamp_document_types"):
            selected = getattr(profile, field_name) or []
            if PREVIOUS_BUILTIN_PDFS.issubset(selected) and NEW_DOCUMENT_TYPE not in selected:
                setattr(profile, field_name, [*selected, NEW_DOCUMENT_TYPE])
                updates.append(field_name)
        if updates:
            profile.save(update_fields=updates)


class Migration(migrations.Migration):
    dependencies = [("companies", "0020_companyprofile_stamp_document_types")]

    operations = [
        migrations.RunPython(enable_new_document_marks, migrations.RunPython.noop),
    ]
