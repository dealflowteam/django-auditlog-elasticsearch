from django.core.management import BaseCommand
from elasticsearch_dsl import connections

from auditlog.documents import ElasticSearchLogEntry
from auditlog.models import LogEntry as LogEntry_db


class Command(BaseCommand):
    def handle(self, *args, **options):
        ElasticSearchLogEntry.init()
        count = LogEntry_db.objects.count()
        step = 10000
        last = 0
        for i in range(0, count, step):
            entries = []
            for entry_db in LogEntry_db.objects.all()[i:last + step]:
                last += step
                entry = ElasticSearchLogEntry.from_db_entry(entry_db)
                entries.append(entry)

            ElasticSearchLogEntry.bulk(connections.get_connection(), entries)
            print(f'Uploaded {i} logs')
