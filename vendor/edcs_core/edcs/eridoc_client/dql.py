"""DQL builder with strict escaping - the Jira ID comes from an email body
(untrusted input), so this module is DQL-injection prevention."""
from __future__ import annotations

import re

from edcs.exceptions import SecurityError

JIRA_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{1,7}$")


def validate_jira_id(jira_id: str) -> str:
    jira_id = jira_id.strip().upper()
    if not JIRA_ID_RE.match(jira_id):
        raise SecurityError(f"Jira ID fails pattern validation: {jira_id!r}")
    return jira_id


def esc(value: str) -> str:
    """Escape single quotes for DQL string literals."""
    return value.replace("'", "''")


def folder_query(jira_id: str, root_path: str = "") -> str:
    jira_id = validate_jira_id(jira_id)
    scope = f" AND FOLDER('{esc(root_path)}', DESCEND)" if root_path else ""
    return (
        "SELECT r_object_id, object_name, r_creation_date, r_modify_date "
        f"FROM dm_folder WHERE object_name = '{jira_id}'{scope}"
    )


def documents_query(folder_id: str) -> str:
    if not re.match(r"^[0-9a-fA-F]{16}$", folder_id):
        raise SecurityError(f"Invalid object id: {folder_id!r}")
    return (
        "SELECT d.r_object_id, d.object_name, d.r_version_label, d.owner_name, "
        "d.r_creation_date, d.r_modify_date, d.a_content_type, d.r_content_size, "
        "d.i_chronicle_id "
        f"FROM dm_document d WHERE FOLDER(ID('{folder_id}')) AND d.i_has_folder = TRUE "
        "ORDER BY d.object_name"
    )


def versions_query(chronicle_id: str) -> str:
    if not re.match(r"^[0-9a-fA-F]{16}$", chronicle_id):
        raise SecurityError(f"Invalid chronicle id: {chronicle_id!r}")
    return (
        "SELECT r_object_id, r_version_label, r_modify_date FROM dm_document (ALL) "
        f"WHERE i_chronicle_id = '{chronicle_id}' ORDER BY r_modify_date DESC"
    )
