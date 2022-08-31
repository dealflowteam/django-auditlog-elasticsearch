from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import BaseCommand
from django.utils import timezone

from auditlog.documents import ElasticSearchLogEntry
from auditlog.models import LogEntry, get_int_id


def create_db_entries_from_document_entries(timestamp):
    to_create = []
    User = get_user_model()
    valid_actors = set(get_int_id(pk) for pk in User.objects.values_list('pk', flat=True))
    valid_content_types = set(ContentType.objects.values_list('id', flat=True))
    valid_ids = {'actors': valid_actors, 'content_types': valid_content_types}
    last_timestamp = timestamp
    count = 0
    now = timezone.now() - timedelta(seconds=30)  # Ensure that all events will be found
    for e in ElasticSearchLogEntry.search().filter('range', timestamp={'gt': timestamp.isoformat(),
                                                                       'lt': now.isoformat()}).scan():
        entry = e.to_log_entry(valid_ids)
        to_create.append(entry)
        if len(to_create) > 10000:
            LogEntry.objects.bulk_create(to_create)
            to_create = []
        if e.timestamp > last_timestamp:
            last_timestamp = e.timestamp
        count += 1
    LogEntry.objects.bulk_create(to_create)
    return count, last_timestamp


class Command(BaseCommand):
    def handle(self, *args, **options):
        try:
            timestamp = LogEntry.objects.latest().timestamp
        except LogEntry.DoesNotExist:
            timestamp = timezone.now() - timedelta(weeks=52 * 30)
        count, last_timestamp = create_db_entries_from_document_entries(timestamp)
        print(f"Created {count} new records. Last record from {last_timestamp}")
