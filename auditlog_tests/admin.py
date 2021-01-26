from django.contrib import admin

from auditlog.mixins import AuditlogAdminHistoryMixin
from auditlog.registry import auditlog
from auditlog_tests.models import SimpleModel, HashIdModel


class BaseAdmin(AuditlogAdminHistoryMixin, admin.ModelAdmin):
    pass


@admin.register(HashIdModel)
class HashIdModelAdmin(BaseAdmin):
    list_display = ['text']


@admin.register(SimpleModel)
class SimpleModelAdmin(BaseAdmin):
    list_display = ['text', 'datetime']


for model in auditlog.get_models():
    if model not in (SimpleModel, HashIdModel):
        admin.site.register(model)
