from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0013_systemnotification_alert_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='useraccount',
            name='email_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='useraccount',
            name='email_verification_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
