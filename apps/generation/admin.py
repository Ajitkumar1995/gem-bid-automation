from django.contrib import admin
from .models import BidBOQItem, BidPreparation, CustomDocumentTemplate, GeneratedDocument

admin.site.register(BidPreparation)
admin.site.register(BidBOQItem)
admin.site.register(GeneratedDocument)
admin.site.register(CustomDocumentTemplate)
