import hashlib
import shutil
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.bids.models import Bid
from apps.companies.models import CompanyDocument, CompanyProfile
from apps.documents.models import LinkedDocument
from apps.generation.models import GeneratedDocument


FILE_FIELDS = (
    (Bid, "source_pdf"),
    (LinkedDocument, "file"),
    (GeneratedDocument, "file"),
    (CompanyDocument, "file"),
    (CompanyProfile, "signature_image"),
    (CompanyProfile, "stamp_image"),
)


def _references(name):
    return sum(model.objects.filter(**{field: name}).count() for model, field in FILE_FIELDS)


def _retarget(old_name, new_name):
    for model, field in FILE_FIELDS:
        model.objects.filter(**{field: old_name}).update(**{field: new_name})


class Command(BaseCommand):
    help = "Find byte-identical files in MEDIA_ROOT and optionally merge their references and remove duplicate copies."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Back up duplicate files, merge references, then remove duplicates.")
        parser.add_argument("--backup-dir", help="Directory outside MEDIA_ROOT for recoverable copies; required with --apply.")

    def handle(self, *args, **options):
        root = Path(settings.MEDIA_ROOT).resolve()
        if not root.is_dir():
            self.stdout.write("Media directory does not exist; nothing to clean.")
            return
        files = [path for path in root.rglob("*") if path.is_file() and path.name != ".gitkeep"]
        by_digest = defaultdict(list)
        for path in files:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            by_digest[digest.digest()].append(path)

        duplicate_groups = [group for group in by_digest.values() if len(group) > 1]
        if not duplicate_groups:
            self.stdout.write("No byte-identical files found.")
            return
        groups = []
        reclaimed = 0
        for group in duplicate_groups:
            names = [path.relative_to(root).as_posix() for path in group]
            canonical = min(names, key=lambda name: (-_references(name), len(name), name))
            canonical_path = root / canonical
            duplicates = [root / name for name in names if name != canonical]
            reclaimed += sum(path.stat().st_size for path in duplicates)
            groups.append((canonical, duplicates))
            self.stdout.write(f"Keep {canonical}; duplicate(s): {', '.join(path.relative_to(root).as_posix() for path in duplicates)}")
        self.stdout.write(f"{len(duplicate_groups)} duplicate group(s), {reclaimed:,} bytes reclaimable.")

        if not options["apply"]:
            self.stdout.write("Dry run only. Re-run with --apply --backup-dir /path/outside/storage to clean these files.")
            return
        backup_option = options.get("backup_dir")
        if not backup_option:
            raise CommandError("--backup-dir is required with --apply so removed files can be recovered.")
        backup_root = Path(backup_option).resolve()
        if backup_root == root or root in backup_root.parents:
            raise CommandError("The backup directory must be outside MEDIA_ROOT.")
        if backup_root.exists() and any(backup_root.iterdir()):
            raise CommandError("The backup directory must be empty or not exist.")

        # Copy first. If the database update fails, all original files remain
        # in place and the backup can simply be discarded.
        for _canonical, duplicates in groups:
            for duplicate in duplicates:
                target = backup_root / duplicate.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(duplicate, target)

        try:
            with transaction.atomic():
                for canonical, duplicates in groups:
                    canonical_path = root / canonical
                    for duplicate in duplicates:
                        _retarget(duplicate.relative_to(root).as_posix(), canonical)
        except Exception:
            raise

        removed = 0
        for _canonical, duplicates in groups:
            for duplicate in duplicates:
                duplicate.unlink()
                removed += 1
        self.stdout.write(self.style.SUCCESS(
            f"Removed {removed} duplicate file(s), reclaimed {reclaimed:,} bytes. Recoverable copies: {backup_root}"
        ))
