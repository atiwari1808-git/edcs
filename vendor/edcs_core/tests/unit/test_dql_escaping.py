import pytest

from edcs.eridoc_client.dql import folder_query, validate_jira_id
from edcs.exceptions import SecurityError


def test_valid_jira_id():
    assert validate_jira_id("abcd-1234") == "ABCD-1234"


@pytest.mark.parametrize("bad", [
    "ABCD-1234' OR '1'='1", "1234", "ABCD_1234", "A-1; DROP TABLE", "", "ABCD-",
])
def test_injection_attempts_rejected(bad):
    with pytest.raises(SecurityError):
        validate_jira_id(bad)


def test_folder_query_contains_only_validated_id():
    q = folder_query("ABCD-1234")
    assert "'ABCD-1234'" in q and ";" not in q
