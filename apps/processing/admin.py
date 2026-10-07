from django.contrib import admin
from .models import ProcessingJob, ProcessingLog

admin.site.register(ProcessingJob)
admin.site.register(ProcessingLog)
