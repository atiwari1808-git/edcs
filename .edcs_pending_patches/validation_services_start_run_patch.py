# In apps/validation/services.py -> start_run(...), read the new payload key and persist it:
#   doc_scrum_master_email=payload.get("doc_scrum_master_email", "").strip().lower(),
#
# Also, after a doc-only run reaches PASSED, resolve/store the user ID for dashboard display if desired,
# then trigger a notification to the configured tool members plus the doc scrum master email.
