from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0015_alert_cho_review_gate'),
    ]

    operations = [
        migrations.AddField(
            model_name='communityreport',
            name='photo',
            field=models.ImageField(blank=True, null=True, upload_to='community_reports/'),
        ),
    ]
