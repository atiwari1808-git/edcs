# Generated migration — AutomationType model
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('adminconfig', '0002_meetingtemplate_tool'),
    ]

    operations = [
        migrations.CreateModel(
            name='AutomationType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('key', models.SlugField(max_length=32, unique=True,
                                        help_text='Short identifier used in code, e.g. HEALTHCHECK')),
                ('display_name', models.CharField(max_length=64)),
                ('requires_scheduling', models.BooleanField(
                    default=True,
                    help_text=(
                        'Tick = Execution flow (scan → schedule meeting). '
                        'Untick = Document-only flow (scan → email report, no meeting).'
                    ),
                )),
                ('notification_emails', models.TextField(
                    blank=True, default='',
                    help_text=(
                        'Comma-separated list of email addresses to CC on every scan '
                        'completion notification for this type.'
                    ),
                )),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Automation Type',
                'verbose_name_plural': 'Automation Types',
                'ordering': ['sort_order', 'key'],
            },
        ),
    ]

