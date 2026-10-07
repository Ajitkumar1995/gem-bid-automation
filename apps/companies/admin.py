from django.contrib import admin
from .models import CompanyDocument, CompanyProfile

admin.site.register(CompanyProfile)
admin.site.register(CompanyDocument)
