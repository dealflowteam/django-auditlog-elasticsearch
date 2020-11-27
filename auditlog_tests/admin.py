from django.contrib import admin

from auditlog.mixins import AuditlogAdminHistoryMixin
from auditlog.registry import auditlog
from auditlog_tests.models import SimpleModel


class SimpleModelAdmin(AuditlogAdminHistoryMixin, admin.ModelAdmin):
    list_display = ['text']


for model in auditlog.get_models():
    if model == SimpleModel:
        admin.site.register(model, SimpleModelAdmin)
    else:
        admin.site.register(model)
