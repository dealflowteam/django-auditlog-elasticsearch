from django.core.management import BaseCommand
from elasticsearch_dsl import connections

from auditlog.documents import ElasticSearchLogEntry, Change
from auditlog.models import LogEntry as LogEntry_db


class Command(BaseCommand):
    def handle(self, *args, **options):
        ElasticSearchLogEntry.init()
        count = LogEntry_db.objects.count()
        step = 10000
        last = 0
        for i in range(0, count, step):
            entries = []
            for entry_db in LogEntry_db.objects.all()[i:last+step]:
                last += step
                entry = ElasticSearchLogEntry(
                    meta={'id': entry_db.pk},
                    action=['create', 'update', 'delete'][entry_db.action],
                    content_type_id=entry_db.content_type.pk,
                    content_type_app_label=entry_db.content_type.app_label,
                    content_type_model=entry_db.content_type.model,
                    object_id=entry_db.object_id,
                    object_pk=entry_db.object_pk,
                    object_repr=entry_db.object_repr,
                    timestamp=entry_db.timestamp
                )
                if entry_db.actor:
                    entry.actor_id = str(entry_db.actor.pk)
                    entry.actor_email = entry_db.actor.email
                    entry.actor_first_name = entry_db.actor.first_name
                    entry.actor_last_name = entry_db.actor.last_name
                if entry_db.remote_addr:
                    entry.remote_addr = entry_db.remote_addr
                if entry_db.changes:
                    entry.changes = [
                        Change(field=key, old=val[0], new=val[1]) for key, val in entry_db.changes.items()
                    ]
                entries.append(entry)

            ElasticSearchLogEntry.bulk(connections.get_connection(), entries)
            print(f'Uploaded {i} logs')
