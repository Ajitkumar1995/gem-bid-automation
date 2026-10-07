import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.generation.models import GeneratedDocument


class Command(BaseCommand):
    help = "Archive and remove legacy generated PDFs; editable document records remain in the database."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Back up files, clear legacy file pointers, and remove the files.")
        parser.add_argument("--backup-dir", help="Directory outside MEDIA_ROOT for recoverable copies; required with --apply.")

    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT).resolve()
        generated_root = media_root / "generated"
        if not generated_root.is_dir():
            self.stdout.write("No generated file directory exists; nothing to clean.")
            return
        files = sorted(path for path in generated_root.rglob("*") if path.is_file())
        if not files:
            self.stdout.write("No legacy generated files found.")
            return
        names = [path.relative_to(media_root).as_posix() for path in files]
        referenced = list(GeneratedDocument.objects.exclude(file="").values_list("file", flat=True))
        database_references = [name for name in referenced if name in set(names)]
        self.stdout.write(f"Found {len(files)} generated file(s), {sum(path.stat().st_size for path in files):,} bytes.")
        self.stdout.write(f"{len(database_references)} file pointer(s) will be cleared; editable document text remains unchanged.")
        if not options["apply"]:
            self.stdout.write("Dry run only. Use --apply --backup-dir /path/outside/storage to clean these legacy outputs.")
            return
        backup_option = options.get("backup_dir")
        if not backup_option:
            raise CommandError("--backup-dir is required with --apply so removed files can be recovered.")
        backup_root = Path(backup_option).resolve()
        if backup_root == media_root or media_root in backup_root.parents:
            raise CommandError("The backup directory must be outside MEDIA_ROOT.")
        if backup_root.exists() and any(backup_root.iterdir()):
            raise CommandError("The backup directory must be empty or not exist.")
        for path in files:
            target = backup_root / path.relative_to(media_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        try:
            with transaction.atomic():
                for name in database_references:
                    GeneratedDocument.objects.filter(file=name).update(file="")
        except Exception:
            raise
        for path in files:
            path.unlink()
        for directory in sorted((p for p in generated_root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            directory.rmdir()
        generated_root.rmdir()
        self.stdout.write(self.style.SUCCESS(
            f"Archived and removed {len(files)} legacy generated file(s). Recoverable copies: {backup_root}"
        ))
