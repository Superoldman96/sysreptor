import argparse
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from sysreptor.api_utils.backup_utils import walk_storage_dir
from sysreptor.utils.files import get_all_file_fields
from sysreptor.utils.utils import groupby_to_dict


class Command(BaseCommand):
    help = 'Clean up unused files.'

    def add_arguments(self, parser) -> None:
        parser.add_argument('--database', action=argparse.BooleanOptionalAction, default=True, help='Clean up files from the database')
        parser.add_argument('--filesystem', action=argparse.BooleanOptionalAction, default=True, help='Clean up files from the filesystem')
        parser.add_argument('--storage', action='store', default=None, help='Clean up files from a specific storage')

    def file_exists(self, f):
        try:
            with f.open():
                return True
        except Exception:
            return False

    def handle(self, database=False, filesystem=False, storage=None, *args, **options):
        if database:
            self.cleanup_database(only_storage=storage)
        if filesystem:
            self.cleanup_filesystem(only_storage=storage)

    def get_db_files(self, qs, field_info):
        qs = qs \
            .annotate(file_path=F(field_info['field_name'])) \
            .values_list('file_path', flat=True) \
            .exclude(file_path__isnull=True) \
            .exclude(file_path='') \
            .distinct()
        return set(qs)

    @transaction.atomic
    def cleanup_database(self, only_storage=None):
        logging.info('Cleaning up file references from the database that no longer exist on the filesystem')
        cleanup_older_than = timezone.now() - timedelta(hours=1)

        for storage_name, fields in groupby_to_dict(get_all_file_fields(), key=lambda f: f['storage_name']).items():
            if only_storage and only_storage != storage_name:
                continue

            storage = fields[0]['storage']
            fs_files = None
            for field_info in fields:
                logging.info(f'Cleaning up {field_info["model"]._meta.label}.{field_info["field_name"]} in storage {field_info["storage_name"]}')

                db_files = self.get_db_files(field_info['model'].objects.filter(created__lt=cleanup_older_than), field_info)
                if fs_files is None:
                    fs_files = set(walk_storage_dir(storage))
                missing_files = db_files - fs_files

                qs = field_info['model'].objects \
                    .filter(**{field_info['field_name'] + '__in': missing_files})
                if field_info['field'].null:
                    qs.update(**{field_info['field_name']: None})
                    logging.info(f'  Updated {qs.count()} entries')
                else:
                    qs.delete()
                    logging.info(f'  Deleted {qs.count()} entries')

    def cleanup_filesystem(self, only_storage=None):
        logging.info('Cleaning up files from the filesystem that are not referenced in the database')
        cleanup_older_than = timezone.now() - timedelta(hours=1)

        for storage_name, fields in groupby_to_dict(get_all_file_fields(), key=lambda f: f['storage_name']).items():
            if only_storage and only_storage != storage_name:
                continue

            storage = fields[0]['storage']
            logging.info(f'Cleaning up files for storage {storage_name}')

            db_files = set()
            for field_info in fields:
                db_files.update(self.get_db_files(field_info['model'].objects.all(), field_info))
                if hasattr(field_info['model'], 'history'):
                    db_files.update(self.get_db_files(field_info['model'].history.all(), field_info))
            fs_files = set(walk_storage_dir(storage))

            unreferenced_files = fs_files - db_files
            deleted_files = []
            for f in unreferenced_files:
                try:
                    try:
                        if storage.get_created_time(f) > cleanup_older_than:
                            continue
                    except (OSError, NotImplementedError):
                        pass

                    storage.delete(f)
                    deleted_files.append(f)
                except FileNotFoundError:
                    pass
                except Exception as ex:
                    logging.warning(f'  Could not delete {f}: {ex}')
            logging.info(f'  Deleted {len(deleted_files)} files')
