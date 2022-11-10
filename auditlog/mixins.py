from django import urls as urlresolvers
from django.conf import settings
from django.contrib.admin.options import get_content_type_for_model
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.text import capfirst
from django.utils.timezone import localtime
from django.utils.translation import gettext as _

from auditlog.models import LogEntry, get_int_id

MAX = 75


class LogEntryAdminMixin:
    def created(self, obj):
        return localtime(obj.timestamp).strftime("%Y-%m-%d %H:%M:%S.%f")

    created.short_description = "Created"

    def user_url(self, obj):
        if obj.actor:
            app_label, model = settings.AUTH_USER_MODEL.split(".")
            viewname = f"admin:{app_label}_{model.lower()}_change"
            try:
                link = urlresolvers.reverse(viewname, args=[obj.actor_id])
            except NoReverseMatch:
                return "%s" % (obj.actor)
            return format_html('<a href="{}">{}</a>', link, obj.actor.email)

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
            msg.append("<table class='grp-table'>")
            msg.append(self._format_header("#", "Field", "From", "To"))
            for i, (field, change) in enumerate(sorted(atom_changes.items()), 1):
                value = [i, field] + (["***", "***"] if field == "password" else change)
                msg.append(self._format_line(*value, _class=f"grp-row grp-row-{'event' if i % 2 else 'odd'}"))
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
            "<thead>" + "".join(["<tr>", "<th>{}</th>" * len(labels), "</tr>"]) + "</thead>", *labels
        )

    def _format_line(self, *values, _class=''):
        return format_html(
            "".join([f"<tr class='{_class}'>", "<td>{}</td>" * len(values), "</tr>"]), *values
        )


class AuditlogAdminHistoryMixin(LogEntryAdminMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.list_display = list(self.list_display) + ['history']
        self.readonly_fields = list(self.readonly_fields) + ['history']

    def get_log_entries(self, object):
        content_type = get_content_type_for_model(object)
        from auditlog.models import LogEntry, get_backend
        backend = get_backend()
        object_id = get_int_id(object.pk)
        if backend == 'elastic':
            from auditlog.documents import ElasticSearchLogEntry
            from elasticsearch_dsl import Q
            query = [Q('match', object_pk=str(object.pk))]
            if isinstance(object_id, int):
                query.append(Q('match', object_id=object_id))
            entries = ElasticSearchLogEntry.search().query(
                Q('bool', must=[Q('bool', should=query),
                                Q('match', content_type_id=content_type.pk)])
            ).sort('-timestamp')
            entries = entries[:entries.count()]
        else:
            from django.db.models import Q
            query = Q(object_pk=object.pk)
            if isinstance(object_id, int):
                query = query | Q(object_id=object_id)
            entries = LogEntry.objects.filter(
                query & Q(content_type=content_type)
            ).select_related().order_by('-timestamp')
        for entry in entries:
            if backend == 'elastic':
                link = reverse('admin:auditlog_elasticlogentrymodel_change', kwargs={'object_id': entry.meta.id})
                entry = entry.to_log_entry()
            else:
                link = reverse('admin:auditlog_logentry_change', kwargs={'object_id': entry.id})
            entry.user_link = self.user_url(entry)
            entry.log_link = format_html(u'<a href="{}">Log entry</a>', link)
            yield entry

    def history_view(self, request, object_id, extra_context=None):
        "The 'history' admin view for this model."

        # First check if the user can see this history.
        model = self.model
        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            return self._get_obj_does_not_exist_redirect(request, model._meta, object_id)

        if not self.has_view_or_change_permission(request, obj):
            raise PermissionDenied

        # Then get the history for this object.
        opts = model._meta
        app_label = opts.app_label
        context = {
            **self.admin_site.each_context(request),
            'title': _('Change history: %s') % obj,
            'subtitle': None,
            'log_entry_list': self.get_log_entries(obj),
            'module_name': str(capfirst(opts.verbose_name_plural)),
            'object': obj,
            'opts': opts,
            'preserved_filters': self.get_preserved_filters(request),
            **(extra_context or {}),
        }

        request.current_app = self.admin_site.name
        return TemplateResponse(request, self.object_history_template or [
            "admin/%s/%s/auditlog_history.html" % (app_label, opts.model_name),
            "admin/%s/auditlog_history.html" % app_label,
            "admin/auditlog_history.html"
        ], context)

    def history(self, obj):
        info = self.model._meta.app_label, self.model._meta.model_name
        link = reverse(f'admin:{info[0]}_{info[1]}_history', kwargs={'object_id': obj.pk})
        return format_html(u'<a href="{}">History</a>', link)
