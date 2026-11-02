from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0019_alter_systemnotification_notification_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyForecastSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('target_month', models.DateField(help_text='First day of the forecast target month.')),
                ('barangay', models.CharField(max_length=100)),
                ('predicted_cases', models.DecimalField(decimal_places=2, max_digits=10)),
                ('actual_cases', models.PositiveIntegerField(blank=True, null=True)),
                ('forecasted_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['target_month', 'barangay'],
                'constraints': [
                    models.UniqueConstraint(fields=('target_month', 'barangay'), name='unique_monthly_forecast_per_barangay'),
                ],
            },
        ),
    ]
