import re
from datetime import datetime, timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from sysreptor.notifications import querysets
from sysreptor.pentests.rendering.error_messages import format_path
from sysreptor.users.models import PentestUser
from sysreptor.utils.crypto.fields import EncryptedField
from sysreptor.utils.models import BaseModel
from sysreptor.utils.utils import copy_keys, datetime_from_date


class RemoteNotificationSpec(BaseModel):
    """
    Specification for a remote notification that gets assigned to users.
    """
    active_until = models.DateField(null=True, blank=True, db_index=True)
    user_conditions = models.JSONField(default=dict, blank=True)
    visible_for_days = models.IntegerField(null=True, blank=True)

    title = models.CharField(max_length=255)
    text = models.TextField()
    link_url = models.TextField(null=True, blank=True)

    objects = querysets.RemoteNotificationSpecManager()

    def __str__(self) -> str:
        return self.title

    @property
    def visible_until(self) -> datetime|None:
        out = None
        if self.visible_for_days:
            out = timezone.now() + timedelta(days=self.visible_for_days)
        if self.active_until:
            active_until_datetime = datetime_from_date(self.active_until)
            if not out or active_until_datetime < out:
                out = active_until_datetime
        return out


class NotificationType(models.TextChoices):
    REMOTE = 'remote'

    MEMBER = 'member'
    FINISHED = 'finished'
    ARCHIVED = 'archived'
    DELETED = 'deleted'
    COMMENTED = 'commented'
    ASSIGNED = 'assigned'
    BACKUP_MISSING = 'backup_missing'


class UserNotification(BaseModel):
    """
    Notification assigned to a specific user. Can marked as resolved.
    """

    MENTION_USERNAME_PATTERN = re.compile(r'(^|(?<=\s))@(?P<username>[\w\-.@]*\w)((?=[\s.:,;!?])|$)')

    user = models.ForeignKey(to=PentestUser, on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(max_length=50, choices=NotificationType.choices, db_index=True)
    read = models.BooleanField(default=False, db_index=True)
    visible_until = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(to=PentestUser, on_delete=models.SET_NULL, null=True, blank=True)
    additional_content = EncryptedField(models.JSONField(encoder=DjangoJSONEncoder, default=dict, blank=True))

    # Links to related objects
    remotenotificationspec = models.ForeignKey(to=RemoteNotificationSpec, on_delete=models.CASCADE, null=True, blank=True)
    project = models.ForeignKey(to='pentests.PentestProject', on_delete=models.CASCADE, null=True, blank=True)
    finding = models.ForeignKey(to='pentests.PentestFinding', on_delete=models.CASCADE, null=True, blank=True)
    section = models.ForeignKey(to='pentests.ReportSection', on_delete=models.CASCADE, null=True, blank=True)
    note = models.ForeignKey(to='pentests.ProjectNotebookPage', on_delete=models.CASCADE, null=True, blank=True)
    comment = models.ForeignKey(to='pentests.Comment', on_delete=models.CASCADE, null=True, blank=True)
    backuplog = models.ForeignKey(to='api_utils.BackupLog', on_delete=models.CASCADE, null=True, blank=True)

    objects = querysets.UserNotificationManager()

    @property
    def content(self) -> dict:
        content = self.additional_content.copy()

        # Format username
        created_by_name = 'Someone'
        if self.created_by:
            created_by_name = '@' + self.created_by.username
            if self.created_by.name:
                created_by_name += f' ({self.created_by.name})'

        # Add ID of referenced project
        if self.project_id:
            content['project_id'] = self.project_id

        if self.type == NotificationType.REMOTE and self.remotenotificationspec:
            content = copy_keys(self.remotenotificationspec, ['title', 'text', 'link_url'])
        elif self.type == NotificationType.MEMBER and self.project:
            content |= {
                'title': 'Added as member',
                'text': f'{created_by_name} added you as member to project "{self.additional_content.get("project_name")}"',
                'link_url': f'/projects/{self.project.id}/',
            }
        elif self.type == NotificationType.ASSIGNED:
            if self.finding:
                finding_title = self.additional_content.get("finding_title") or ''
                content |= {
                    'title': f'Assigned finding {finding_title}',
                    'text': f'{created_by_name} assigned you finding "{finding_title}"',
                    'link_url': f'/projects/{self.finding.project_id}/reporting/findings/{self.finding.finding_id}/',
                }
            elif self.section:
                section_title = self.additional_content.get("section_title") or ''
                content |= {
                    'title': f'Assigned section {section_title}',
                    'text': f'{created_by_name} assigned you section "{section_title}"',
                    'link_url': f'/projects/{self.section.project_id}/reporting/sections/{self.section.section_id}/',
                }
            elif self.note:
                note_title = self.additional_content.get("note_title") or ''
                content |= {
                    'title': f'Assigned note {note_title}',
                    'text': f'{created_by_name} assigned you note "{note_title}"',
                    'link_url': f'/projects/{self.note.project_id}/notes/{self.note.note_id}/',
                }
        elif self.type == NotificationType.COMMENTED and self.comment:
            comment_path = format_path(self.comment.path.removeprefix('data.'))
            if self.comment.text_range:
                comment_path += f':offset={self.comment.text_range.from_}'

            if self.comment.finding:
                finding_title = self.additional_content.get("finding_title") or ''
                content |= {
                    'title': f'New comment in finding {finding_title}',
                    'text': f'{created_by_name} commented on finding "{finding_title}"',
                    'link_url': f'/projects/{self.comment.finding.project_id}/reporting/findings/{self.comment.finding.finding_id}/#{comment_path}',
                }
            elif self.comment.section:
                section_title = self.additional_content.get("section_title") or ''
                content |= {
                    'title': f'New comment in section {section_title}',
                    'text': f'{created_by_name} commented on section "{self.additional_content.get("section_title")}"',
                    'link_url': f'/projects/{self.comment.section.project_id}/reporting/sections/{self.comment.section.section_id}/#{comment_path}',
                }
        elif self.type == NotificationType.FINISHED and self.project:
            content |= {
                'title': 'Project finished',
                'text': f'{created_by_name} finished project "{self.additional_content.get("project_name")}"',
                'link_url': f'/projects/{self.project.id}/',
                'project_id': self.project.id,
            }
        elif self.type == NotificationType.ARCHIVED:
            content |= {
                'title': 'Project archived. Delete all remaining evidence files',
                'text': f'{created_by_name} has archived the project "{self.additional_content.get("project_name")}". Ensure you delete all evidence files related to this project.',
            }
        elif self.type == NotificationType.DELETED:
            content |= {
                'title': 'Project deleted. Delete all remaining evidence files',
                'text': f'{created_by_name} deleted project "{self.additional_content.get("project_name")}". Ensure you delete all evidence files related to this project.',
            }
        elif self.type == NotificationType.BACKUP_MISSING:
            content |= {
                'title': 'Backup missing',
                'text': 'No backup was created in the last 30 days.',
                'link_url': 'https://docs.sysreptor.com/setup/backups/',
            }

        return content

