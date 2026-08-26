# Generated migration — adds automation_type FK to ValidationRun
import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('adminconfig', '0003_automationtype'),
        ('validation',  '0005_validationrun_automation_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='validationrun',
            name='automation_type',
            field=models.ForeignKey(
                blank=True,
                help_text='Controls post-scan behaviour and who is notified.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='validation_runs',
                to='adminconfig.automationtype',
            ),
        ),
    ]

