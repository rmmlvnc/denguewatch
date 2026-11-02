from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0016_communityreport_photo'),
    ]

    operations = [
        migrations.AddField(
            model_name='communityreport',
            name='location_details',
            field=models.CharField(blank=True, max_length=250),
        ),
    ]
