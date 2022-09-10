import datetime

from celery import current_app as app
from celery_batches import Batches
from django.core.cache import cache
from django.utils import timezone

from auditlog.management.commands.auditlog_copy_elastic_to_db import create_db_entries_from_document_entries
from auditlog.models import LogEntry


@app.task(base=Batches, flush_every=100, flush_interval=10)
def save_log_entries(requests):
    to_create = []
    for request in requests:
        to_create.append(LogEntry(**request.kwargs))
        app.backend.mark_as_done(request.id, None, request=request)
    return LogEntry.objects.bulk_create(to_create)

@app.task
def backup_auditlog_to_db():
    timestamp = cache.get("backup_auditlog_to_db_timestamp")
    if timestamp is None:
        try:
            timestamp = LogEntry.objects.latest().timestamp
        except LogEntry.DoesNotExist:
            timestamp = timezone.now() - datetime.timedelta(weeks=52 * 30)
    # Ensure that all events will be available for search
    # https://www.elastic.co/guide/en/elasticsearch/reference/current/near-real-time.html
    end_timestamp = timezone.now() - datetime.timedelta(seconds=30)
    count, last_timestamp = create_db_entries_from_document_entries(timestamp, end_timestamp)
    cache.set("backup_auditlog_to_db_timestamp", last_timestamp, None)
    return count
