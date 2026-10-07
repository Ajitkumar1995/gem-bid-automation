from django.core.management.base import BaseCommand

from apps.bids.retention import expire_old_bids


class Command(BaseCommand):
    help = "Delete expired GeM bid workspaces and their bid-specific files."

    def handle(self, *args, **options):
        removed = expire_old_bids()
        self.stdout.write(self.style.SUCCESS(f"Deleted {removed} expired bid workspace(s)."))
