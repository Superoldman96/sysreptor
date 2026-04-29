import argparse
import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

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

    @transaction.atomic
    def cleanup_database(self, only_storage=None):
        logging.info('Cleaning up file references from the database that no longer exist on the filesystem')
        for field_info in get_all_file_fields():
            if only_storage and only_storage != field_info['storage_name']:
                continue

            logging.info(f'Cleaning up {field_info["model"]._meta.label}.{field_info["field_name"]} in storage {field_info["storage_name"]}')
            qs = field_info['model'].objects \
                .filter(pk__in=[
                    o.pk
                    for o in field_info['model'].objects.iterator()
                    if not self.file_exists(getattr(o, field_info['field_name']))
                ])
            if field_info['field'].null:
                qs.update(**{field_info['field_name']: None})
                logging.info(f'  Updated {qs.count()} entries')
            else:
                qs.delete()
                logging.info(f'  Deleted {qs.count()} entries')

    def cleanup_filesystem(self, only_storage=None):
        logging.info('Cleaning up files from the filesystem that are not referenced in the database')
        for storage_name, fields in groupby_to_dict(get_all_file_fields(), key=lambda f: f['storage_name']).items():
            if only_storage and only_storage != storage_name:
                continue

            storage = fields[0]['storage']
            logging.info(f'Cleaning up files for storage {storage_name}')

            query_parts = []
            for field_info in fields:
                query_parts.append(field_info['model'].objects.annotate(file_path=F(field_info['field_name'])).values('file_path'))
                if hasattr(field_info['model'], 'history'):
                    query_parts.append(field_info['model'].history.annotate(file_path=F(field_info['field_name'])).values('file_path'))
            fs_files = set(walk_storage_dir(storage))
            if not query_parts:
                db_files = set()
            elif len(query_parts) == 1:
                db_files = set(query_parts[0].values_list('file_path', flat=True))
            else:
                db_files = set(query_parts[0].union(*query_parts[1:]).values_list('file_path', flat=True))

            unreferenced_files = fs_files - db_files
            for f in unreferenced_files:
                try:
                    storage.delete(f)
                except FileNotFoundError:
                    pass
                except Exception as ex:
                    logging.warning(f'  Could not delete {f}: {ex}')
            logging.info(f'  Deleted {len(unreferenced_files)} files')
