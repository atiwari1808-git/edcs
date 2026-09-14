from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="role",
            name="max_meetings_per_day",
            field=models.PositiveIntegerField(
                blank=True, null=True,
                help_text="Max handover meetings a holder may book per day. "
                          "Blank = unlimited, 0 = not allowed."),
        ),
        migrations.AddField(
            model_name="role",
            name="max_nmn_verifications_per_day",
            field=models.PositiveIntegerField(
                blank=True, null=True,
                help_text="Max 'no-meeting-needed' (doc-only) verifications a "
                          "holder may run per day. Blank = unlimited, 0 = not allowed."),
        ),
    ]
