from django import urls as urlresolvers
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import render
from django.urls import path, reverse
from django.urls.exceptions import NoReverseMatch
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from elasticsearch_dsl import Q

from auditlog.documents import LogEntry


class LogEntryAdminMixin(object):

    def created(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')

    def user(self, obj):
        if obj.actor_id:
            app_label, model = settings.AUTH_USER_MODEL.split('.')
            viewname = 'admin:%s_%s_change' % (app_label, model.lower())
            try:
                link = urlresolvers.reverse(viewname, args=[obj.actor_id])
            except NoReverseMatch:
                return u'%s' % (obj.actor)
            return format_html(u'<a href="{}">{}</a>', link, obj.actor_email)

        return 'system'

    def resource(self, obj):
        app_label, model = obj.content_type_app_label, obj.content_type_model
        viewname = 'admin:%s_%s_change' % (app_label, model)
        try:
            args = [obj.object_pk] if obj.object_id is None else [obj.object_id]
            link = urlresolvers.reverse(viewname, args=args)
        except NoReverseMatch:
            return obj.object_repr
        else:
            return format_html(u'<a href="{}">{}</a>', link, obj.object_repr)

    def changes(self, obj):
        if obj.action == LogEntry.Action.DELETE or not obj.changes:
            return ''  # delete
        changes = obj.changes
        msg = '<table class="grp-table"><thead><tr><th>#</th><th>Field</th><th>From</th><th>To</th></tr></thead>'
        for i, change in enumerate(changes):
            class_ = [f"grp-row grp-row-{'event' if i % 2 else 'odd'}"]
            value = class_ + [i, change.field] + (['***', '***'] if change.field == 'password'
                                                  else [change.old, change.new])
            msg += format_html('<tr class="{}"><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>', *value)

        msg += '</table>'
        return mark_safe(msg)


class AuditlogAdminHistoryMixin(LogEntryAdminMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.list_display = list(self.list_display) + ['history']
        self.readonly_fields = list(self.readonly_fields) + ['history']

    def get_urls(self):
        urls = super().get_urls()
        info = self.model._meta.app_label, self.model._meta.model_name
        new_urls = [
            path('<object_id>/auditlog-history/', self.auditlog_history, name='%s_%s_auditlog-history' % info)
        ]
        return new_urls + urls

    def auditlog_history(self, request, *args, **kwargs):
        pk = self.model._meta.pk.to_python(kwargs['object_id'])
        id_ = self.model._meta.pk.get_prep_value(kwargs['object_id'])
        instance = self.model.objects.get(pk=pk)
        content_type = ContentType.objects.get_for_model(instance)
        s = LogEntry.search().query(
            Q('bool', must=[Q('bool', should=[Q('match', object_pk=str(instance.pk)),
                                              Q('match', object_id=id_)]),
                            Q('match', content_type_id=content_type.pk)])
        ).sort('timestamp')

        for entry in s:
            entry.user_link = self.user(entry)
            link = reverse('admin:auditlog_logmodel_change', kwargs={'object_id': entry.meta.id})
            entry.log_link = format_html(u'<a href="{}">Log entry</a>', link)

        context = {
            'title': f'Change history: {instance}',
            'opts': self.model._meta,
            'log_entry_list': s
        }
        return render(request, 'admin/auditlog_history.html', context)

    def history(self, obj):
        info = self.model._meta.app_label, self.model._meta.model_name
        link = reverse(f'admin:{info[0]}_{info[1]}_auditlog-history', kwargs={'object_id': obj.pk})
        return format_html(u'<a href="{}">History</a>', link)
