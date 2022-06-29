# Generated by Django 3.2.13 on 2022-06-29 18:53

import django.core.serializers.json
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auditlog', '0009_logmodel'),
    ]

    operations = [
        migrations.AlterField(
            model_name='logentry',
            name='changes',
            field=models.JSONField(blank=True, decoder=django.core.serializers.json.DjangoJSONEncoder, encoder=django.core.serializers.json.DjangoJSONEncoder, verbose_name='change message'),
        ),
    ]
