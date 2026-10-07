from django.contrib import admin
from .models import DocumentLink, LinkedDocument

@admin.register(LinkedDocument)
class LinkedDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "bid", "label", "status", "page_number", "created_at")
    list_filter = ("status",)
    search_fields = ("url", "label", "bid__title", "bid__bid_number")

admin.site.register(DocumentLink)
