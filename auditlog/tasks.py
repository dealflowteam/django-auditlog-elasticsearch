from celery import current_app as app
from celery_batches import Batches

from auditlog.models import LogEntry


@app.task(base=Batches, flush_every=100, flush_interval=10)
def save_log_entries(requests):
    to_create = []
    for request in requests:
        to_create.append(LogEntry(**request.kwargs))
        app.backend.mark_as_done(request.id, None, request=request)
    return LogEntry.objects.bulk_create(to_create)
