"""Tools for creating, updating, and monitoring GitHub pulse dashboards."""

import base64
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Union, Annotated, Dict
import re

import requests
from dateutil import parser as dateparser
from croniter import croniter
from pydantic import BaseModel, Field


VALID_MODES = {'md', 'org'}
VALID_STATUSES = ('ERROR', 'MISSING', 'OK')


def make_headers(token):
    "Make GitHub API headers"
    if not token:
        raise ValueError('Must set token before interacting with GitHub')
    return {"Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"}


class PulseOxError(Exception):
    """Base exception for PulseOx errors."""
    pass


class ValidationError(PulseOxError):
    """Exception raised for validation errors."""
    pass


class GitHubAPIError(PulseOxError):
    """Exception raised for GitHub API errors."""
    pass


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
    status: Optional[str] = None
    updated: Optional[str] = None

    def update(self, token: str, base_url="https://api.github.com"):
        """Query GitHub to update status.
        """
        url = (f"{base_url}/repos/{self.owner}/{self.repo}/contents/"
               f"{self.path}")

        self.status = 'MISSING'
        self.note = 'unknown problem trying to update spec'

        try:
            response = requests.get(
                url, headers=make_headers(token=token), timeout=30)
        except requests.RequestException as problem:
            # Network error, treat as missing
            logging.exception('Problem try to get status.')
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
            self.note = 'Problem decoding GitHub response'
            logging.exception(self.note)
            # Failed to decode, treat as missing metadata
            return

        # Parse metadata
        metadata = self._parse_metadata(content)

        if not metadata:
            self.note = 'Failed to parse metadata'
            logging.error(self.note)
            return

        # Determine status based on metadata and schedule
        metadata_status = metadata.get('status', '').upper()

        # ERROR status takes precedence
        if metadata_status == 'ERROR':
            self.status = 'ERROR'
        else:
            # Check if update is within schedule
            is_within = self._is_within_schedule(
                metadata.get('updated'), self.schedule
            )

            if not is_within:
                self.status = 'MISSING'
            elif metadata_status == 'OK':
                self.status = 'OK'
            else: # Unknown status, treat as error
                self.status = 'ERROR'
                self.note = ' status {metadata_status=} treated as error'
                logging.error(self.note)

        if metadata.get('note', None):
            self.note = metadata['note']
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

    def _is_within_schedule(
        self,
        updated_str: Optional[str],
        schedule: Union[timedelta, str]
    ) -> bool:
        """Check if update time is within the schedule.

        Args:
            updated_str: ISO format timestamp string
            schedule: timedelta or cron string

        Returns:
            True if within schedule, False otherwise
        """
        if not updated_str:
            return False

        try:
            updated = dateparser.isoparse(updated_str)
        except (ValueError, TypeError):
            return False

        # Make sure we have a timezone-aware datetime
        if updated.tzinfo is None:
            # Assume UTC if no timezone
            updated = updated.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)

        # For timedelta schedules
        if isinstance(schedule, timedelta):
            return (now - updated) <= schedule
        elif isinstance(schedule, str):
            # For cron strings, calculate next expected run time
            # based on the last update
            try:
                cron = croniter(schedule, updated)
                next_run = cron.get_next(datetime)
                # If we're past the next expected run, it's missing
                return now <= next_run
            except (ValueError, KeyError) as e:
                # Invalid cron or other error, be conservative
                raise ValidationError(
                    f"Failed to parse cron schedule: {e}"
                )
        else:
            # This should not happen if PulseOxSpec validates
            raise ValidationError(
                f"Invalid schedule type: {type(schedule)}"
            )
    



class PulseOxClient:
    """Client for posting content to GitHub repositories.

    Args:
        token: GitHub personal access token for API authentication

    Raises:
        ValidationError: If token is empty
    """

    def __init__(self, token: str):
        if not token or not token.strip():
            raise ValidationError("token cannot be empty")

        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def post(
        self,
        owner: str,
        repo: str,
        path_to_file: str,
        content: str,
        status: str = "OK",
        optional_note: str = ""
    ) -> requests.Response:
        """Post content to a file in a GitHub repository.

        Args:
            owner: Repository owner
            repo: Repository name
            path_to_file: Path to the file in the repository
            content: Content to write to the file
            status: Status code (must be 'OK', 'ERROR')
            optional_note: Optional short text note

        Returns:
            Response object from the GitHub API

        Raises:
            ValidationError: If parameters are invalid
            GitHubAPIError: If GitHub API request fails
        """
        self._validate_post_params(
            owner, repo, path_to_file, content, status
        )

        metadata = self._create_metadata(
            path_to_file, status, optional_note
        )
        full_content = f"{content}\n\n{metadata}"

        return self._update_file(
            owner, repo, path_to_file, full_content
        )

    def _validate_post_params(
        self,
        owner: str,
        repo: str,
        path_to_file: str,
        content: str,
        status: str
    ) -> None:
        """Validate post parameters.

        Raises:
            ValidationError: If any parameter is invalid
        """
        if not owner or not owner.strip():
            raise ValidationError("owner cannot be empty")
        if not repo or not repo.strip():
            raise ValidationError("repo cannot be empty")
        if not path_to_file or not path_to_file.strip():
            raise ValidationError("path_to_file cannot be empty")
        if content is None:
            raise ValidationError("content cannot be None")
        if status not in VALID_STATUSES:
            raise ValidationError(
                f"status must be one of {VALID_STATUSES}, "
                f"got: {status}"
            )

    def _create_metadata(
        self,
        path_to_file: str,
        status: str,
        optional_note: str
    ) -> str:
        """Create metadata section for the file.

        Args:
            path_to_file: Path to determine file format
            status: Status code
            optional_note: Optional note

        Returns:
            Formatted metadata string
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        if path_to_file.endswith('.md'):
            header = "# Metadata"
        elif path_to_file.endswith('.org'):
            header = "* Metadata"
        else:
            # Default to markdown for unknown extensions
            header = "# Metadata"

        metadata_lines = [
            header,
            f"- status: {status}",
            f"- updated: {timestamp}",
        ]

        if optional_note:
            metadata_lines.append(f"- note: {optional_note}")

        return "\n".join(metadata_lines)

    def _update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str
    ) -> requests.Response:
        """Update or create a file in GitHub repository.

        Args:
            owner: Repository owner
            repo: Repository name
            path: File path in repository
            content: File content

        Returns:
            Response from GitHub API

        Raises:
            GitHubAPIError: If the API request fails
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"

        # Get current file SHA if it exists
        try:
            get_response = requests.get(
                url, headers=self.headers, timeout=30
            )
        except requests.RequestException as e:
            raise GitHubAPIError(
                f"Failed to fetch file info: {e}"
            )

        sha = None
        if get_response.status_code == 200:
            try:
                sha = get_response.json().get("sha")
            except (ValueError, KeyError) as e:
                raise GitHubAPIError(
                    f"Failed to parse GitHub response: {e}"
                )

        # Prepare update payload
        try:
            encoded_content = base64.b64encode(
                content.encode('utf-8')
            ).decode('utf-8')
        except UnicodeEncodeError as e:
            raise ValidationError(f"Failed to encode content: {e}")

        payload = {
            "message": f"Update {path}",
            "content": encoded_content,
        }

        if sha:
            payload["sha"] = sha

        try:
            response = requests.put(
                url, json=payload, headers=self.headers, timeout=30
            )
        except requests.RequestException as e:
            raise GitHubAPIError(f"Failed to update file: {e}")

        return response


class PulseOxSummary(BaseModel):
    """Summary of dashboard status.
    """

    status: Annotated[Dict[str, List[PulseOxSpec]], Field(description=(
        'Dictionary where keys are status types from VALID_STATUSES'
        ' and each value is a PulseOxSpec with that status.'),
                                                          default={})]
    text: Annotated[str, Field(default='', description=(
        'Text summary contents for the dashboard'))]

    
    def fill(self, mode: str = 'md') -> str:
        """Format the summary output.
        """
        unknown = set(VALID_STATUSES) - set(self.status)
        if unknown:
            raise ValueError(f'Unknown status fields: {unknown}')
        sections = [self._format_section(n, self.status.get(n, []), mode)
                    for n in VALID_STATUSES]
        self.text = '\n\n'.join(sections)

    def _format_section(
        self,
        title: str,
        entries: List[dict],
        mode: str
    ) -> str:
        """Format a single section of the summary.

        Args:
            title: Section title
            entries: List of entries for this section
            mode: Output format

        Returns:
            Formatted section string
        """
        if mode == 'md':
            header = f"# {title}"
        elif mode == 'org':
            header = f"* {title}"
        else:
            # Should not happen if mode is validated
            raise ValidationError(
                f"Invalid mode in _format_section: {mode}"
            )

        lines = [header, ""]

        for entry in entries:
            lines.append(self._format_entry(entry, mode))

        return "\n".join(lines)

    def _format_entry(self, entry: dict, mode: str) -> str:
        """Format a single entry in the summary.

        Args:
            entry: Entry dictionary
            mode: Output format

        Returns:
            Formatted entry string
        """
        path = entry.path
        note = entry.note
        updated = entry.updated or 'N/A'

        # Create link based on mode
        if mode == 'md':
            link = f"[{path}]({path})"
        elif mode == 'org':
            link = f"[[{path}][{path}]]"
        else:
            # Should not happen if mode is validated
            raise ValidationError(
                f"Invalid mode in _format_entry: {mode}"
            )

        parts = [f"- {link}"]
        if note:
            parts.append(note)
        parts.append(updated)

        return " ".join(parts)
    

class PulseOxDashboard(BaseModel):
    """Dashboard for monitoring multiple GitHub files.

    Args:
        token: GitHub personal access token for API authentication

    Raises:
        ValidationError: If token is empty
    """

    owner: str
    repo: str
    spec_list: List[PulseOxSpec]
    token: Annotated[str, Field(exclude=True, default='', description=(
        'GitHub personal access token to access repo. Only required'
        ' if you call methods which interact with GitHub.'))]
    summary: Optional[PulseOxSummary] = None
    base_url: str = "https://api.github.com"

    def fill_summary(
        self,
        mode: str = 'md'
    ) -> str:
        """Fill summary field with summary of all monitored files.

        Args:
            mode: Output format ('md' for markdown, 'org' for org-mode)

        Raises:
            ValidationError: If parameters are invalid
        """
        if not self.owner or not self.owner.strip():
            raise ValidationError("owner cannot be empty")
        if not self.repo or not self.repo.strip():
            raise ValidationError("repo cannot be empty")
        if mode not in VALID_MODES:
            raise ValidationError(
                f"mode must be one of {VALID_MODES}, got: {mode}"
            )
        if not isinstance(self.spec_list, list):
            raise ValidationError("spec_list must be a list")

        status = {n: [] for n in VALID_STATUSES}

        for spec in self.spec_list:
            spec.update(token=self.token)
            if spec.status not in VALID_STATUSES:
                raise ValueError(f'Bad status in {spec=}')
            status[spec.status].append(spec)

        self.summary = PulseOxSummary(status=status)
        self.summary.fill()

    def write_summary(
        self,
        path_to_summary: str
    ) -> requests.Response:
        """Write summary to a file in GitHub repository.

        Args:
            path_to_summary: Path where summary should be written

        Returns:
            Response from GitHub API

        Raises:
            ValidationError: If parameters are invalid
            GitHubAPIError: If the API request fails
        """
        if not self.summary:
            self.fill_summary()
        if not self.summary:
            raise ValidationError("unable to generate summary")
        if not path_to_summary or not path_to_summary.strip():
            raise ValidationError("path_to_summary cannot be empty")
        jresp = self._write_github_file(self.model_dump_json(indent=2),
                                        path_to_summary + '.json',
                                        'updated JSON summary')
        sresp = self._write_github_file(self.summary.text, path_to_summary,
                                       'updated summary')
        
        return sresp, jresp

    def _write_github_file(self, content: str, path: str,
                           commit_message: str = '') -> requests.Response:
        """Helper to write given content to path on GitHub.
        """
        commit_message = commit_message or f"Update {path}"
        if not self.owner or not self.owner.strip():
            raise ValidationError("owner cannot be empty")
        if not self.repo or not self.repo.strip():
            raise ValidationError("repo cannot be empty")
        if not path or not path.strip():
            raise ValidationError("path cannot be empty")

        url = (
            f"{self.base_url}/repos/{self.owner}/{self.repo}/contents/"
            f"{path}"
        )

        try:  # Get current file SHA if exists
            get_response = requests.get(
                url, headers=make_headers(token=self.token), timeout=30)
        except requests.RequestException as e:
            raise GitHubAPIError(
                f"Failed to fetch summary file info: {e}")

        sha = None
        if get_response.status_code == 200:
            try:
                sha = get_response.json().get("sha")
            except (ValueError, KeyError) as e:
                raise GitHubAPIError(
                    f"Failed to parse GitHub response: {e}")

        try:  # Encode and prepare payload
            encoded_content = base64.b64encode(
                content.encode('utf-8')).decode('utf-8')
        except UnicodeEncodeError as e:
            raise ValidationError(f"Failed to encode summary: {e}")

        payload = {"message": commit_message, "content": encoded_content}

        if sha:
            payload["sha"] = sha

        try:
            response = requests.put(
                url, json=payload, headers=make_headers(
                    token=self.token), timeout=30)
        except requests.RequestException as e:
            raise GitHubAPIError(f"Failed to write summary: {e}")

        return response
    

