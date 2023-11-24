from django.contrib import admin
from django.http import Http404
from django.shortcuts import render
from django.urls import path

from auditlog.filters import ResourceTypeFilter, ActorInputFilter, DateTimeFilter, ActionChoiceFilter, ChangesFilter, \
    ContentTypeChoiceFilter
from auditlog.mixins import LogEntryAdminMixin
from auditlog.models import LogEntry
from auditlog.utils.admin import CustomPaginator, CustomChangeList, get_headers, results


@admin.register(LogEntry)
class LogEntryAdmin(LogEntryAdminMixin, admin.ModelAdmin):
    list_select_related = ["content_type", "actor"]
    list_display = ["created", "resource_url", "action", "msg_short", "user_url"]
    search_fields = [
        "timestamp",
        "object_repr",
        "changes",
        "actor__first_name",
        "actor__last_name",
        "actor__email",
    ]
    list_filter = ["action", ResourceTypeFilter]
    readonly_fields = ["created", "resource_url", "action", "user_url", "msg", "additional_data", "serialized_data"]
    fieldsets = [
        (None, {"fields": ["created", "user_url", "resource_url"]}),
        ("Changes", {"fields": ["action", "msg"]}),
        ("Other", {"fields": ["additional_data", "serialized_data"]})
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('actor', 'content_type')

    def has_add_permission(self, request):
        # As audit admin doesn't allow log creation from admin
        return False


class ElasticLogEntryModelAdmin(LogEntryAdmin):
    list_fields = ['timestamp', 'action', 'content_type_model', 'object_repr', 'actor', 'changed_fields']
    filters = [ActorInputFilter, 'object_repr', ActionChoiceFilter, ('timestamp', DateTimeFilter),
               ChangesFilter, ContentTypeChoiceFilter]
    detail_fields = {
        'Details': ('created', 'user', 'resource'),
        'Changes': ('action', 'changes')
    }

    paginator = CustomPaginator

    # readonly_fields = []

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        return [
                   path('', self.list_view, name='%s_%s_changelist' % info),
                   # path('<path:object_id>/', self.detail_view, name='%s_%s_change' % info),
               ] + super().get_urls()

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        from auditlog.documents import ElasticSearchLogEntry
        s = ElasticSearchLogEntry.search()
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

    def get_object(self, request, object_id, from_field=None):
        import elasticsearch
        from auditlog.documents import ElasticSearchLogEntry
        try:
            return ElasticSearchLogEntry.get(object_id).to_log_entry()
        except elasticsearch.exceptions.NotFoundError:
            raise Http404()


try:
    from .documents import ElasticSearchLogEntry


    class ElasticLogEntryModel(LogEntry):
        class Meta:
            proxy = True
            verbose_name_plural = 'Elastic Log Entries'
            app_label = 'auditlog'


    admin.site.register(ElasticLogEntryModel, ElasticLogEntryModelAdmin)
except ImportError:
    pass
