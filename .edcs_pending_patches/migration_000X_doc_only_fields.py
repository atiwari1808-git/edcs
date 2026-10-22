# Create a migration adding these ValidationRun fields:
# - doc_scrum_master_email (EmailField, blank=True, default="")
# - go_live_done (BooleanField, default=False)
# - go_live_done_at (DateTimeField, null=True, blank=True)
# - go_live_done_by (FK AUTH_USER_MODEL, null=True, blank=True, SET_NULL, related_name="+")
