Use the existing per-tool member email configuration as the single source of truth.
When a doc-only verification PASSES, send a completion email to:
- configured member mail IDs for that tool
- requested_by.email
- doc_scrum_master_email (if present)
Deduplicate recipients before sending.
