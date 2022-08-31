import elasticsearch
from django.contrib import admin
from django.http import Http404
from django.shortcuts import render
from django.urls import path

from auditlog.documents import LogEntry as ElasticLogEntry
from auditlog.filters import ResourceTypeFilter, ActorInputFilter, DateTimeFilter, ActionChoiceFilter, ChangesFilter, \
    ContentTypeChoiceFilter
from auditlog.mixins import LogEntryAdminMixin
from auditlog.models import LogEntry
from auditlog.utils.admin import CustomPaginator, CustomChangeList, get_headers, results


class LogEntryAdmin(admin.ModelAdmin, LogEntryAdminMixin):
    list_select_related = ["content_type", "actor"]
    list_display = ["created", "resource_url", "action", "msg_short", "user_url"]
    search_fields = [
        "timestamp",
        "object_repr",
        "changes",
        "actor__first_name",
        "actor__last_name",
        "actor__username",
    ]
    list_filter = ["action", ResourceTypeFilter]
    readonly_fields = ["created", "resource_url", "action", "user_url", "msg"]
    fieldsets = [
        (None, {"fields": ["created", "user_url", "resource_url"]}),
        ("Changes", {"fields": ["action", "msg"]}),
    ]

    def has_add_permission(self, request):
        # As audit admin doesn't allow log creation from admin
        return False


admin.site.register(LogEntry, LogEntryAdmin)


class ElasticLogEntryModel(LogEntry):
    class Meta:
        proxy = True
        verbose_name_plural = 'Log Entries'
        app_label = 'auditlog'


@admin.register(ElasticLogEntryModel)
class DummyModelAdmin(LogEntryAdminMixin, admin.ModelAdmin):
    list_fields = ['timestamp', 'action', 'content_type_model', 'object_repr', 'actor', 'changed_fields']
    filters = [ActorInputFilter, 'object_repr', ActionChoiceFilter, ('timestamp', DateTimeFilter),
               ChangesFilter, ContentTypeChoiceFilter]
    detail_fields = {
        'Details': ('created', 'user', 'resource'),
        'Changes': ('action', 'changes')
    }

    paginator = CustomPaginator
    readonly_fields = []

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        return [
            path('', self.list_view, name='%s_%s_changelist' % info),
            path('<path:object_id>/', self.detail_view, name='%s_%s_change' % info),
        ]

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        s = ElasticLogEntry.search()
        s = s.sort('-timestamp')
        return s

    def list_view(self, request):
        cl = CustomChangeList(self, request, list_filter=self.filters)
        cl.get_results()

        context = {
            'title': 'Log entries',
            'opts': self.model._meta,
            'cl': cl,
            'result_headers': get_headers(self.list_fields),
            'num_sorted_fields': 0,
            'results': list(results(cl.result_list, self.list_fields, self.model._meta)),
        }

        return render(request, 'admin/logs_list.html', context=context)

    def detail_view(self, request, object_id):
        try:
            obj = ElasticLogEntry.get(object_id)
        except elasticsearch.exceptions.NotFoundError:
            raise Http404()
        context = {
            'opts': self.model._meta,
            'title': str(obj),
            'fieldsets': self._get_obj_fields(obj)
        }
        return render(request, 'admin/logs_detail.html', context=context)

    def _get_obj_fields(self, obj):
        fields = {}
        for key, values in self.detail_fields.items():
            fields[key] = []
            for value in values:
                if hasattr(self, value):
                    val = getattr(self, value)
                    if callable(val):
                        fields[key].append((value, val(obj)))
                else:
                    fields[key].append((value, getattr(obj, value)))
        return fields
