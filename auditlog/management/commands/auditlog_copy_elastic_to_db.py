from datetime import timedelta

from dateutil.parser import parse
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import BaseCommand
from django.utils import timezone
from django.utils.timezone import make_aware, localtime

from auditlog.documents import ElasticSearchLogEntry
from auditlog.models import LogEntry, get_int_id


def get_valid_ids():
    User = get_user_model()
    valid_actors = set(get_int_id(pk) for pk in User.objects.values_list('pk', flat=True))
    valid_content_types = set(ContentType.objects.values_list('id', flat=True))
    return {'actors': valid_actors, 'content_types': valid_content_types}


def create_db_entries_from_document_entries(from_timestamp, to_timestamp, existing=None, valid_ids=None):
    to_create = []
    count = 0
    if valid_ids is None:
        valid_ids = get_valid_ids()
    last_timestamp = from_timestamp
    for e in ElasticSearchLogEntry.search().filter('range', timestamp={'gte': from_timestamp.isoformat(),
                                                                       'lt': to_timestamp.isoformat()}).scan():
        entry = e.to_log_entry(valid_ids)
        key = (entry.timestamp, entry.content_type_id, entry.object_id)
        if e.timestamp > last_timestamp:
            last_timestamp = e.timestamp
        if existing is not None:
            if key in existing:
                continue
            existing.add(key)
        count += 1
        to_create.append(entry)
        if len(to_create) > 10000:
            LogEntry.objects.bulk_create(to_create)
            to_create = []
    if to_create:
        LogEntry.objects.bulk_create(to_create)
    return count, last_timestamp


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--timestamp', default=None)

    def handle(self, *args, timestamp=None, **options):
        if timestamp:
            timestamp = make_aware(parse(timestamp))
        else:
            try:
                first = ElasticSearchLogEntry.search().sort('timestamp').execute()[0]
                timestamp = localtime(first.timestamp)
            except IndexError:
                print("No records in ElasticSearch")
                return
        now = timezone.now()
        valid_ids = get_valid_ids()
        while timestamp < now:
            end_timestamp = (timestamp + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            existing = set(
                LogEntry.objects.filter(timestamp__gte=timestamp, timestamp__lt=end_timestamp) \
                    .values_list('timestamp', 'content_type_id', 'object_id'))
            print(f"Migrating records from {timestamp} to {end_timestamp}. Omitting {len(existing)} records")
            count, last_timestamp = create_db_entries_from_document_entries(timestamp, end_timestamp, existing,
                                                                            valid_ids)
            print(f"Created {count} new records. Last record from {last_timestamp}")
            timestamp = end_timestamp
