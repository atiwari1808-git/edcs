from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('validation', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='validationrun',
            name='doc_scrum_master_email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='validationrun',
            name='go_live_done',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='validationrun',
            name='go_live_done_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='validationrun',
            name='go_live_done_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
    ]
