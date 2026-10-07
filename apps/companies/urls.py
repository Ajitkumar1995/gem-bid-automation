from django.urls import path
from . import views

urlpatterns = [
    path("profile/", views.company_profile, name="company-profile"),
    path("profile/signature/", views.view_company_signature, name="company-signature-view"),
    path("profile/stamp/", views.view_company_stamp, name="company-stamp-view"),
    path("documents/<int:document_id>/", views.view_company_document, name="company-document-view"),
]
