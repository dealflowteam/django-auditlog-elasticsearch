from django.conf import settings

from auditlog.diff import model_instance_diff
from auditlog.documents import ElasticSearchLogEntry
from auditlog.models import LogEntry


def get_backend():
    if getattr(settings, 'AUDITLOG_USE_ELASTIC_SEARCH', True):
        return ElasticSearchLogEntry
    else:
        return LogEntry.objects


def log_create(sender, instance, created, **kwargs):
    """
    Signal receiver that creates a log entry when a model instance is first saved to the database.

    Direct use is discouraged, connect your model through :py:func:`auditlog.registry.register` instead.
    """
    if created:
        changes = model_instance_diff(None, instance)
        log_entry = get_backend().log_create(
            instance,
            action=LogEntry.Action.CREATE,
            changes=changes,
        )
        return log_entry


def log_update(sender, instance, **kwargs):
    """
    Signal receiver that creates a log entry when a model instance is changed and saved to the database.

    Direct use is discouraged, connect your model through :py:func:`auditlog.registry.register` instead.
    """
    if instance.pk is not None:
        try:
            old = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            pass
        else:
            new = instance

            changes = model_instance_diff(old, new)

            # Log an entry only if there are changes
            if changes:
                log_entry = get_backend().log_create(
                    instance,
                    action=LogEntry.Action.UPDATE,
                    changes=changes,
                )
                return log_entry


def log_delete(sender, instance, **kwargs):
    """
    Signal receiver that creates a log entry when a model instance is deleted from the database.

    Direct use is discouraged, connect your model through :py:func:`auditlog.registry.register` instead.
    """
    if instance.pk is not None:
        changes = model_instance_diff(instance, None)
        log_entry = get_backend().log_create(
            instance,
            action=LogEntry.Action.DELETE,
            changes=changes,
        )
        return log_entry
