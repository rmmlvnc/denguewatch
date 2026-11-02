from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0021_denguedatasetrecordoverride'),
    ]

    operations = [
        migrations.AlterField(
            model_name='reportauditlog',
            name='action',
            field=models.CharField(
                choices=[
                    ('CREATED', 'Created'),
                    ('EDITED', 'Edited'),
                    ('SUBMITTED', 'Submitted to CHO'),
                    ('FORWARDED', 'Verified and forwarded'),
                    ('VERIFIED', 'Verified'),
                    ('REJECTED', 'Rejected'),
                    ('DELETED', 'Deleted'),
                ],
                max_length=20,
            ),
        ),
    ]
