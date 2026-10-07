from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import BidCreationLock


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_bid_creation_lock(sender, instance, created, **kwargs):
    if created:
        BidCreationLock.objects.get_or_create(user_id=instance.pk)
