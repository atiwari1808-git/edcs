"""
Post-handover GO-live follow-up + escalation configuration.

Additive module — imported from apps/adminconfig/models.py so Django registers
these models under the `adminconfig` app. Nothing in the existing models file
is changed except one import line (see APPLY_GUIDE.md).

Design (confirmed with product owner):
  * Per-tool team recipients + a "GO-live reminder" day offset (e.g. 10).
  * A single GLOBAL escalation matrix (manager recipients + escalation day,
    e.g. 15) shared across every tool.
Both day-offsets are counted from the day AFTER the handover date has passed.
"""
from django.db import models


def _clean_email_list(raw: str) -> list[str]:
    """De-duped, stripped, lower-cased address list from a comma/semicolon/newline string."""
    if not raw:
        return []
    parts = raw.replace(";", ",").replace("\n", ",").split(",")
    return list(dict.fromkeys(p.strip() for p in parts if p.strip()))


class HandoverFollowupConfig(models.Model):
    """Per-tool GO-live follow-up recipients + day offset.

    When a handover meeting's date has passed and the JIRA has not yet been
    marked GO-live, a reminder is emailed to `team_emails` on day
    `go_live_day` (default 10) after the handover date.
    """
    tool = models.OneToOneField(
        "adminconfig.ToolConfig", on_delete=models.CASCADE,
        related_name="followup_config",
        help_text="The automation tool this follow-up rule applies to.")
    team_emails = models.TextField(
        blank=True, default="",
        help_text=("Comma-separated team recipients for the GO-live reminder. "
                   "Example: team-lead@ericsson.com, squad@ericsson.com"))
    go_live_day = models.PositiveSmallIntegerField(
        default=10,
        help_text=("Days after the handover date to send the 'move JIRA to "
                   "GO live' reminder to the team. Default 10."))
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["tool__sort_order", "tool__key"]
        verbose_name = "Handover follow-up config (per tool)"
        verbose_name_plural = "Handover follow-up configs (per tool)"

    def __str__(self):
        return f"{self.tool.key} · GO-live reminder day {self.go_live_day}"

    def team_email_list(self) -> list[str]:
        return _clean_email_list(self.team_emails)

    @classmethod
    def for_tool_key(cls, tool_key: str):
        return (cls.objects.filter(tool__key=tool_key, is_active=True)
                .select_related("tool").first())


class EscalationPolicy(models.Model):
    """GLOBAL escalation matrix — a single active row shared by all tools.

    If the JIRA is still not GO-live by `escalation_day` (default 15) after
    the handover date, the manager recipients are emailed.
    """
    name = models.CharField(max_length=64, default="Default escalation policy")
    manager_emails = models.TextField(
        blank=True, default="",
        help_text=("Comma-separated manager/escalation recipients. "
                   "Example: delivery-manager@ericsson.com"))
    escalation_day = models.PositiveSmallIntegerField(
        default=15,
        help_text=("Days after the handover date to escalate to managers "
                   "if the JIRA is still not GO-live. Default 15."))
    cc_team = models.BooleanField(
        default=True,
        help_text="Also CC the per-tool team + organizer on the escalation email.")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Escalation policy (global)"
        verbose_name_plural = "Escalation policy (global)"

    def __str__(self):
        return f"{self.name} · escalate on day {self.escalation_day}"

    def manager_email_list(self) -> list[str]:
        return _clean_email_list(self.manager_emails)

    @classmethod
    def current(cls):
        """Return the single active escalation policy, or None if unconfigured."""
        return cls.objects.filter(is_active=True).order_by("id").first()
