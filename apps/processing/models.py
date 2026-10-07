from django.db import models

class ProcessingJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    bid = models.ForeignKey("bids.Bid", on_delete=models.CASCADE, related_name="processing_jobs")
    task_id = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class ProcessingLog(models.Model):
    job = models.ForeignKey(ProcessingJob, on_delete=models.CASCADE, related_name="logs")
    level = models.CharField(max_length=20, default="info")
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
