# Add to ValidationRun model
# Doc-only Scrum Master / Go Live support
from django.conf import settings
from django.db import models

doc_scrum_master_email = models.EmailField(blank=True, default="")
go_live_done = models.BooleanField(default=False)
go_live_done_at = models.DateTimeField(null=True, blank=True)
go_live_done_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
