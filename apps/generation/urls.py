from django.urls import path
from .views import (
    delete_custom_generated_document,
    edit_generated_document,
    preview_generated_document,
    view_generated_document,
)

urlpatterns = [
    path("documents/<int:document_id>/", view_generated_document, name="generated-document-view"),
    path("documents/<int:document_id>/edit/", edit_generated_document, name="generated-document-edit"),
    path("documents/<int:document_id>/preview/", preview_generated_document, name="generated-document-preview"),
    path("documents/<int:document_id>/delete/", delete_custom_generated_document, name="generated-document-delete"),
]
