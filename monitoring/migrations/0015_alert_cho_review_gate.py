from django.db import migrations, models
import django.db.models.deletion


def withdraw_existing_alerts(apps, schema_editor):
    """Require CHO to explicitly review legacy alerts before reactivation."""
    Alert = apps.get_model('monitoring', 'Alert')
    Alert.objects.filter(is_active=True).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0014_resident_email_verification'),
    ]

    operations = [
        migrations.RunPython(withdraw_existing_alerts, migrations.RunPython.noop),
        migrations.AddField(
            model_name='alert',
            name='cho_review_confirmed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='alert',
            name='cho_review_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='alert',
            name='cho_reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='alert',
            name='cho_reviewed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reviewed_alerts',
                to='monitoring.useraccount',
            ),
        ),
        migrations.AddConstraint(
            model_name='alert',
            constraint=models.CheckConstraint(
                condition=models.Q(is_active=False) | models.Q(cho_review_confirmed=True),
                name='active_alert_requires_cho_review',
            ),
        ),
    ]
