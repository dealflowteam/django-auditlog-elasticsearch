import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.utils import timezone
from django.utils.encoding import smart_str
from elasticsearch.helpers import bulk
from elasticsearch_dsl import Document, connections, Keyword, Date, Nested, InnerDoc, Text

# Define a default Elasticsearch client
from auditlog.models import LogEntry, get_int_id

connections.create_connection(hosts=[settings.ELASTICSEARCH_HOST])

MAX = 75


class Change(InnerDoc):
    field = Keyword(required=True)
    old = Text()
    new = Text()


class ElasticSearchLogEntry(Document):
    class Action:
        CREATE = 'create'
        UPDATE = 'update'
        DELETE = 'delete'

        choices = (
            (CREATE, CREATE),
            (UPDATE, UPDATE),
            (DELETE, DELETE)
        )

    action = Keyword(required=True)

    content_type_id = Keyword(required=True)
    content_type_app_label = Keyword(required=True)
    content_type_model = Keyword(required=True)

    object_id = Keyword()
    object_pk = Keyword()
    object_repr = Text()

    actor_id = Keyword()
    actor_email = Keyword()
    actor_first_name = Text()
    actor_last_name = Text()

    remote_addr = Text()

    timestamp = Date(required=True)

    changes = Nested(Change)

    class Index:
        name = settings.AUDITLOG_INDEX_NAME

    @property
    def actor(self):
        if self.actor_email:
            if self.actor_first_name and self.actor_last_name:
                return f'{self.actor_first_name} {self.actor_last_name} ({self.actor_email})'
            return self.actor_email
        return None

    @property
    def changed_fields(self):
        if self.action == ElasticSearchLogEntry.Action.DELETE:
            return ''  # delete
        changes = self.changes
        s = '' if len(changes) == 1 else 's'
        fields = ', '.join(change['field'] for change in changes)
        if len(fields) > MAX:
            i = fields.rfind(' ', 0, MAX)
            fields = fields[:i] + ' ..'
        return '%d change%s: %s' % (len(changes), s, fields)

    @staticmethod
    def bulk(client, documents):
        actions = (i.to_dict(True) for i in documents)
        return bulk(client, actions)

    def __str__(self):
        if self.action == self.Action.CREATE:
            fstring = "Created {repr:s}"
        elif self.action == self.Action.UPDATE:
            fstring = "Updated {repr:s}"
        elif self.action == self.Action.DELETE:
            fstring = "Deleted {repr:s}"
        else:
            fstring = "Logged {repr:s}"

        return fstring.format(repr=self.object_repr)

    @classmethod
    def log_create(cls, instance, **kwargs):
        """
        Helper method to create a new log entry. This method automatically populates some fields when no explicit value
        is given.

        :param instance: The model instance to log a change for.
        :type instance: Model
        :param kwargs: Field overrides for the :py:class:`LogEntry` object.
        :return: The new log entry or `None` if there were no changes.
        :rtype: ElasticSearchLogEntry
        """
        changes = kwargs.get('changes', None)
        pk = cls._get_pk_value(instance)
        kwargs['action'] = ["create", 'update', 'delete'][kwargs['action']]
        if changes is not None:
            content_type = ContentType.objects.get_for_model(instance)
            kwargs.setdefault('content_type_id', content_type.id)
            kwargs.setdefault('content_type_app_label', content_type.app_label)
            kwargs.setdefault('content_type_model', content_type.model)
            kwargs.setdefault('object_pk', str(pk))
            kwargs.setdefault('object_repr', smart_str(instance))
            kwargs.setdefault('timestamp', timezone.now())

            id_ = instance._meta.pk.get_prep_value(pk)
            if isinstance(id_, int):
                kwargs.setdefault('object_id', id_)
            log_entry = cls(**kwargs)
            transaction.on_commit(log_entry.save)
            return log_entry
        return None

    def save(self, using=None, index=None, validate=True, skip_empty=True, **kwargs):
        try:
            return super().save(using, index, validate, skip_empty, **kwargs)
        except Exception:
            logging.exception("Error when saving log to elasticsearch", extra={'log_entry': self.to_dict()})

    @classmethod
    def _get_pk_value(cls, instance):
        """
        Get the primary key field value for a model instance.

        :param instance: The model instance to get the primary key for.
        :type instance: Model
        :return: The primary key value of the given model instance.
        """
        pk_field = instance._meta.pk.name
        pk = getattr(instance, pk_field, None)

        # Check to make sure that we got an pk not a model object.
        if isinstance(pk, models.Model):
            pk = cls._get_pk_value(pk)
        return pk

    @classmethod
    def create_from_log_entry(cls, log_entry):
        entry = log_entry
        e_log_entry = ElasticSearchLogEntry(
            action={entry.Action.DELETE: ElasticSearchLogEntry.Action.DELETE,
                    entry.Action.UPDATE: ElasticSearchLogEntry.Action.UPDATE,
                    entry.Action.CREATE: ElasticSearchLogEntry.Action.CREATE}[entry.action],
            content_type_id=entry.content_type.id,
            content_type_app_label=entry.content_type.app_label,
            content_type_model=entry.content_type.model,

            object_pk=entry.object_pk,
            object_id=entry.object_id,
            object_repr=entry.object_repr,

            actor_id=get_int_id(entry.actor.id) if entry.actor else None,
            actor_email=entry.actor.email if entry.actor else None,
            actor_first_name=entry.actor.first_name if entry.actor else None,
            actor_last_name=entry.actor.last_name if entry.actor else None,
            remote_addr=entry.remote_addr,
            timestamp=entry.timestamp or timezone.now(),
            changes=[Change(field=field, old=old, new=new) for field, (old, new) in entry.changes.items()]
        )
        e_log_entry.save()
        return e_log_entry

    def to_log_entry(self, valid_ids=None):
        if not valid_ids or self.content_type_id in valid_ids['content_types']:
            content_type = ContentType(id=self.content_type_id,
                                       model=self.content_type_model,
                                       app_label=self.content_type_app_label)
        else:
            content_type = None
        actor = None
        if self.actor_id:
            User = get_user_model()
            if not valid_ids or self.actor_id in valid_ids['actors']:
                actor = User(id=self.actor_id, email=self.actor_email, first_name=self.actor_first_name,
                             last_name=self.actor_last_name)
        return LogEntry(
            timestamp=self.timestamp,
            action={self.Action.CREATE: LogEntry.Action.CREATE,
                    self.Action.UPDATE: LogEntry.Action.UPDATE,
                    self.Action.DELETE: LogEntry.Action.DELETE}[self.action],
            content_type=content_type,
            object_id=self.object_id,
            object_pk=self.object_pk,
            object_repr=self.object_repr,
            actor=actor,
            changes={c.field: [c.old, c.new] for c in self.changes},
            additional_data={
                'actor_id': self.actor_id,
                'actor_email': self.actor_email,
                'actor_first_name': self.actor_first_name,
                'actor_last_name': self.actor_last_name,
                'content_type_id': self.content_type_id,
                'content_type_model': self.content_type_model,
                'content_type_app_label': self.content_type_app_label
            },
            remote_addr=self.remote_addr,
        )
