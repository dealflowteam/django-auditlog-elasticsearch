import datetime
from time import time

from celery import current_app as app
from celery_batches import Batches
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from auditlog.models import LogEntry

BATCH_SIZE = getattr(settings, 'AUDITLOG_CELERY_BATCH_SIZE', 8)
FLUSH_INTERVAL = getattr(settings, 'AUDITLOG_CELERY_FLUSH_INTERVAL', 1)


@app.task(
    base=Batches,
    flush_every=BATCH_SIZE,
    flush_interval=FLUSH_INTERVAL,
    autoretry_for=(Exception,),
    max_retries=None,
    retry_backoff=True,
          retry_backoff_max=60 * 60 * 24)
def save_log_entries(requests):
    to_create = []
    start = time()
    for request in requests:
        log_entry = LogEntry(**request.kwargs)
        LogEntry.objects.clear_logs(log_entry)
        to_create.append(log_entry)
    LogEntry.objects.bulk_create(to_create)
    if not settings.CELERY_TASK_ALWAYS_EAGER:
        for request in requests:
            app.backend.mark_as_done(request.id, None, request=request)
    print(f"Created {len(to_create)} log entries in {time() - start}s")


@app.task
def backup_elastic_to_db():
    CACHE_KEY = "auditlog_backup_elastic_to_db_timestamp"
    timestamp = cache.get(CACHE_KEY)
    from auditlog.management.commands.auditlog_copy_elastic_to_db import create_db_entries_from_document_entries
    if timestamp is None:
        try:
            timestamp = LogEntry.objects.latest().timestamp
        except LogEntry.DoesNotExist:
            timestamp = timezone.now() - datetime.timedelta(weeks=52 * 30)
    # Ensure that all events will be available for search
    # https://www.elastic.co/guide/en/elasticsearch/reference/current/near-real-time.html
    end_timestamp = timezone.now() - datetime.timedelta(seconds=30)
    count, last_timestamp = create_db_entries_from_document_entries(
        timestamp, end_timestamp
    )
    cache.set(CACHE_KEY, last_timestamp, None)
    return count
