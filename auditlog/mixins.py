from auditlog.models import LogEntry
from django import urls as urlresolvers
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import render
from django.urls import path, reverse
from django.urls.exceptions import NoReverseMatch
from django.utils import dateformat
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.timezone import localtime
from elasticsearch_dsl import Q

from auditlog.documents import ElasticSearchLogEntry

MAX = 75

class LogEntryAdminMixin:
    def created(self, obj):
        return localtime(obj.timestamp).strftime("%Y-%m-%d %H:%M:%S")

    created.short_description = "Created"

    def user_url(self, obj):
        if obj.actor:
            app_label, model = settings.AUTH_USER_MODEL.split(".")
            viewname = f"admin:{app_label}_{model.lower()}_change"
            try:
                link = urlresolvers.reverse(viewname, args=[obj.actor_id])
            except NoReverseMatch:
                return "%s" % (obj.actor)
            return format_html('<a href="{}">{}</a>', link, obj.actor_email)

        return "system"

    user_url.short_description = "User"

    def resource_url(self, obj):
        app_label, model = obj.content_type.app_label, obj.content_type.model
        viewname = f"admin:{app_label}_{model}_change"
        try:
            args = [obj.object_pk] if obj.object_id is None else [obj.object_id]
            link = urlresolvers.reverse(viewname, args=args)
        except NoReverseMatch:
            return obj.object_repr
        else:
            return format_html(
                '<a href="{}">{} - {}</a>', link, obj.content_type, obj.object_repr
            )

    resource_url.short_description = "Resource"

    def msg_short(self, obj):
        if obj.action == LogEntry.Action.DELETE:
            return ""  # delete
        changes = obj.changes
        s = "" if len(changes) == 1 else "s"
        fields = ", ".join(changes.keys())
        if len(fields) > MAX:
            i = fields.rfind(" ", 0, MAX)
            fields = fields[:i] + " .."
        return "%d change%s: %s" % (len(changes), s, fields)

    msg_short.short_description = "Changes"

    def changes(self, obj):
        if obj.action == ElasticSearchLogEntry.Action.DELETE or not obj.changes:
            return ''  # delete
        changes = obj.changes
        msg = '<table class="grp-table"><thead><tr><th>#</th><th>Field</th><th>From</th><th>To</th></tr></thead>'
        for i, change in enumerate(changes):
            class_ = [f"grp-row grp-row-{'event' if i % 2 else 'odd'}"]
            value = class_ + [i, change.field] + (['***', '***'] if change.field == 'password'
                                                  else [change.old, change.new])
            msg += format_html('<tr class="{}"><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>', *value)
        msg.append("</table>")

        return mark_safe("".join(msg))

    def msg(self, obj):
        changes = obj.changes

        atom_changes = {}
        m2m_changes = {}

        for field, change in changes.items():
            if isinstance(change, dict):
                assert (
                    change["type"] == "m2m"
                ), "Only m2m operations are expected to produce dict changes now"
                m2m_changes[field] = change
            else:
                atom_changes[field] = change

        msg = []

        if atom_changes:
            msg.append("<table>")
            msg.append(self._format_header("#", "Field", "From", "To"))
            for i, (field, change) in enumerate(sorted(atom_changes.items()), 1):
                value = [i, field] + (["***", "***"] if field == "password" else change)
                msg.append(self._format_line(*value))
            msg.append("</table>")

        if m2m_changes:
            msg.append("<table>")
            msg.append(self._format_header("#", "Relationship", "Action", "Objects"))
            for i, (field, change) in enumerate(sorted(m2m_changes.items()), 1):
                change_html = format_html_join(
                    mark_safe("<br>"),
                    "{}",
                    [(value,) for value in change["objects"]],
                )

                msg.append(
                    format_html(
                        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>",
                        i,
                        field,
                        change["operation"],
                        change_html,
                    )
                )

            msg.append("</table>")

        return mark_safe("".join(msg))

    msg.short_description = "Changes"

    def _format_header(self, *labels):
        return format_html(
            "".join(["<tr>", "<th>{}</th>" * len(labels), "</tr>"]), *labels
        )

    def _format_line(self, *values):
        return format_html(
            "".join(["<tr>", "<td>{}</td>" * len(values), "</tr>"]), *values
        )


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
        s = ElasticSearchLogEntry.search().query(
            Q('bool', must=[Q('bool', should=[Q('match', object_pk=str(instance.pk)),
                                              Q('match', object_id=id_)]),
                            Q('match', content_type_id=content_type.pk)])
        ).sort('-timestamp')

        def entries():
            for entry in s[:s.count()]:
                entry.user_link = self.user(entry)
                link = reverse('admin:auditlog_logmodel_change', kwargs={'object_id': entry.meta.id})
                entry.log_link = format_html(u'<a href="{}">Log entry</a>', link)
                yield entry

        context = {
            'title': f'Change history: {instance}',
            'opts': self.model._meta,
            'log_entry_list': entries()
        }
        return render(request, 'admin/auditlog_history.html', context)

    def history(self, obj):
        info = self.model._meta.app_label, self.model._meta.model_name
        link = reverse(f'admin:{info[0]}_{info[1]}_auditlog-history', kwargs={'object_id': obj.pk})
        return format_html(u'<a href="{}">History</a>', link)
