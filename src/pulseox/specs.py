"""Basic specifications and common classes for PulseOx.
"""

import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Annotated, Literal
import re

import requests
from dateutil import parser as dateparser
from croniter import croniter
from pydantic import BaseModel, Field
import pytz

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



def make_headers(token):
    "Make GitHub API headers"
    if not token:
        raise ValueError('Must set token before interacting with GitHub')
    return {"Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"}


def download_github_file(token: str, owner: str, repo: str, path: str,
                         ref: str = "main", timeout: int = 30,
                         base_url = "https://api.github.com") -> bytes:
    """Download a file from a GitHub repository.

    Args:
        token: Github token.
        owner: Repository owner (username or organization)
        repo: Repository name
        path: Path to the file within the repository
        ref: Branch, tag, or commit SHA (default: "main")

    Returns:
        File contents as bytes

    Raises:
        requests.HTTPError: If the request fails (e.g., file not found,
                            auth issues)
        ValueError: If the response doesn't contain expected content
    """    
    url = f"{base_url}/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": ref}

    headers = make_headers(token)
    response = requests.get(url, headers=headers, params=params,
                            timeout=timeout)
    response.raise_for_status()

    data = response.json()

    # GitHub API returns file content as base64-encoded string
    if "content" not in data:
        raise ValueError(f"No content found for file: {path}")

    # Decode the base64 content
    content = base64.b64decode(data["content"])
    return content


class PulseOxError(Exception):
    """Base exception for PulseOx errors."""


class ValidationError(PulseOxError):
    """Exception raised for validation errors."""


class GitHubAPIError(PulseOxError):
    """Exception raised for GitHub API errors."""


class PulseOxSpec(BaseModel):
    """Specification for a monitored file in a GitHub repository.

    Args:
        path:     Path to the file in the GitHub repository
        schedule: Either a datetime.timedelta or a cron string specifying
                  the expected update frequency

    Raises:
        ValidationError: If path is empty or schedule is invalid
    """

    owner: str
    repo: str
    path: str
    schedule: Union[timedelta, str]
    note: Optional[str] = None
    report: Annotated[Literal[JOB_REPORT], Field(
        default='NOT_REPORTED', description=(
            'What the job reports as its state.'))]
    updated: Optional[str] = None

    def update(self, token: str, base_url="https://api.github.com"):
        """Query GitHub to update report.
        """
        url = (f"{base_url}/repos/{self.owner}/{self.repo}/contents/"
               f"{self.path}")

        self.report = 'NOT_REPORTED'
        self.note = None

        try:
            response = requests.get(
                url, headers=make_headers(token=token), timeout=30)
        except requests.RequestException as problem:
            # Network error, treat as missing
            logging.exception('Problem try to get report.')
            self.note = 'network error: ' + str(problem)
            return

        status_code = getattr(response, 'status_code', -1)
        if status_code != 200:
            self.note = f'error: ({status_code=}) ' + getattr(
                response, 'reason', 'unknown')
            return

        try:  # Decode content
            response_data = response.json()
            if 'content' not in response_data:
                logging.exception("No content in response")
                self.note = "No content in GitHub response"
                return
            content = base64.b64decode(response_data['content']).decode(
                'utf-8')
        except (ValueError, KeyError, UnicodeDecodeError) as problem:
            self.note = f'Problem decoding GitHub response: {problem}'
            logging.exception(self.note)
            # Failed to decode, treat as missing metadata
            return

        # Parse metadata
        metadata = self._parse_metadata(content)

        if not metadata:
            self.note = 'Failed to parse metadata'
            logging.error(self.note)
            return

        # Determine report based on metadata and schedule
        metadata_report = metadata.get('report', '').upper()

        if metadata_report in JOB_REPORT:
            self.report = metadata_report
        else:  # Unknown report, treat as BAD
            self.report = 'BAD'
            self.note = f' report {metadata_report=} treated as bad'
            logging.error(self.note)

        if metadata.get('note', None):
            self.note = metadata.get('note')
        self.updated = metadata.get('updated')

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
