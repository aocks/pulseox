"""Basic specifications and common classes for PulseOx.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Annotated, Literal
import re

from dateutil import parser as dateparser
from croniter import croniter
from pydantic import BaseModel, Field
import pytz

from pulseox.generic_backend import make_backend

VALID_MODES = {'md', 'org'}
VALID_STATUSES = ('ERROR', 'MISSING', 'OK')

JOB_REPORT = ('GOOD', 'BAD', 'NOT_REPORTED')

COMMON_TIMEZONES = {
    tz: timezone(timedelta(hours=offset))
    for tz, offset in [
        ('PST', -8), ('PDT', -7), ('EST', -5), ('EDT', -4),
        ('MST', -7), ('MDT', -6), ('CST', -6), ('CDT', -5),
    ]
}


def parse_dt(value):
    dt = dateparser.parse(value, tzinfos=COMMON_TIMEZONES)
    return dt
    

def make_dt_formatter(show_tz, fmt='%Y-%m-%d %H:%M %Z') -> str:
    tzinfo = pytz.timezone(show_tz)

    def format_dt(value: Union[str, datetime]):
        if value in (None, '', 'N/A', 'NA'):
            return str(value)
        if isinstance(value, str):
            value = dateparser.parse(value)
        elif isinstance(value, datetime):
            pass
        else:
            raise ValueError(f'Bad type for {value=}')
        return value.astimezone(tzinfo).strftime(fmt)
    return format_dt


class PulseOxError(Exception):
    """Base exception for PulseOx errors."""


class ValidationError(PulseOxError):
    """Exception raised for validation errors."""


class GitHubAPIError(PulseOxError):
    """Exception raised for GitHub API errors."""


class PulseOxSpec(BaseModel):
    """Specification for a monitored file in a repository.

    Args:
        owner:    Repository owner (None for local git repos)
        repo:     Repository name (or file:// path for local git repos)
        path:     Path to the file in the repository
        schedule: Either a datetime.timedelta or a cron string specifying
                  the expected update frequency

    Raises:
        ValidationError: If path is empty or schedule is invalid
    """

    owner: Optional[str]
    repo: str
    path: str
    schedule: Union[timedelta, str]
    note: Optional[str] = None
    report: Annotated[Literal[JOB_REPORT], Field(
        default='NOT_REPORTED', description=(
            'What the job reports as its state.'))]
    updated: Optional[str] = None

    def update(self, token: Optional[str] = None,
               base_url: str = "https://api.github.com",
               git_executable: str = "/usr/bin/git"):
        """Update report from backend (GitHub or local git).

        Args:
            token: GitHub personal access token (required for GitHub backend)
            base_url: GitHub API base URL
            git_executable: Path to git executable (for local git backend)
        """
        backend = make_backend(
            self.owner, self.repo,
            token=token or '',
            base_url=base_url,
            git_executable=git_executable
        )
        backend.update_spec(self)

    def _parse_metadata(self, content: str) -> Optional[dict]:
        """Parse metadata from file content.

        Args:
            content: File content

        Returns:
            Dictionary of metadata or None
        """
        metadata = {}

        # Look for metadata section
        md_match = re.search(
            r'(?:^|\n)(?:#|\*) Metadata\n(.*?)(?:\n(?:#|\*)|$)',
            content,
            re.DOTALL
        )

        if not md_match:
            return None

        metadata_text = md_match.group(1)

        # Parse metadata fields
        for line in metadata_text.split('\n'):
            line = line.strip()
            if line.startswith('- '):
                line = line[2:]
                if ': ' in line:
                    key, value = line.split(': ', 1)
                    metadata[key] = value

        return metadata if metadata else None

    def is_within_schedule(
        self,
        updated_str: Optional[str] = None,
        schedule: Optional[Union[timedelta, str]] = None,
    ) -> bool:
        """Check if update time is within the schedule.

        Args:
            updated_str: ISO format timestamp string
            schedule: timedelta or cron string

        Returns:
            True if within schedule, False otherwise
        """
        updated_str = updated_str or self.updated
        schedule = schedule or self.schedule
        
        if not updated_str:
            return False

        updated = parse_dt(updated_str)

        # Make sure we have a timezone-aware datetime
        if updated.tzinfo is None:
            # Assume UTC if no timezone
            updated = updated.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)

        # For timedelta schedules
        if isinstance(schedule, timedelta):
            return (now - updated) <= schedule
        if isinstance(schedule, str):
            # For cron strings, calculate next expected run time
            # based on the last update
            try:
                cron = croniter(schedule, updated)
                next_run = cron.get_next(datetime)
                # If we're past the next expected run, it's missing
                return now <= next_run
            except (ValueError, KeyError) as e:
                # Invalid cron or other error, be conservative
                raise ValidationError(f"Failed to parse cron schedule: {e}"
                                      ) from e
        else:
            # This should not happen if PulseOxSpec validates
            raise ValidationError(
                f"Invalid schedule type: {type(schedule)}"
            )
