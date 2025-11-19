"""Tools for creating, updating, and monitoring GitHub pulse dashboards."""

import base64
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Union
import re

import requests
from dateutil import parser as dateparser
from croniter import croniter


class PulseOxError(Exception):
    """Base exception for PulseOx errors."""
    pass


class ValidationError(PulseOxError):
    """Exception raised for validation errors."""
    pass


class GitHubAPIError(PulseOxError):
    """Exception raised for GitHub API errors."""
    pass


class PulseOxSpec:
    """Specification for a monitored file in a GitHub repository.

    Args:
        path_to_file: Path to the file in the GitHub repository
        schedule: Either a datetime.timedelta or a cron string specifying
                  the expected update frequency

    Raises:
        ValidationError: If path_to_file is empty or schedule is invalid
    """

    def __init__(
        self,
        path_to_file: str,
        schedule: Union[timedelta, str]
    ):
        if not path_to_file or not path_to_file.strip():
            raise ValidationError("path_to_file cannot be empty")

        if not isinstance(schedule, (timedelta, str)):
            raise ValidationError(
                "schedule must be a timedelta or cron string"
            )

        if isinstance(schedule, str):
            if not schedule.strip():
                raise ValidationError("schedule string cannot be empty")
            # Validate cron string
            if not croniter.is_valid(schedule):
                raise ValidationError(
                    f"Invalid cron string: {schedule}"
                )

        self.path_to_file = path_to_file
        self.schedule = schedule


class PulseOxClient:
    """Client for posting content to GitHub repositories.

    Args:
        token: GitHub personal access token for API authentication

    Raises:
        ValidationError: If token is empty
    """

    VALID_STATUSES = {'OK', 'ERROR', 'WARNING'}

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
            status: Status code (must be 'OK', 'ERROR', or 'WARNING')
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
        if status not in self.VALID_STATUSES:
            raise ValidationError(
                f"status must be one of {self.VALID_STATUSES}, "
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


class PulseOxDashboard:
    """Dashboard for monitoring multiple GitHub files.

    Args:
        token: GitHub personal access token for API authentication

    Raises:
        ValidationError: If token is empty
    """

    VALID_MODES = {'md', 'org'}
    VALID_STATUSES = {'ERROR', 'MISSING', 'OK'}

    def __init__(self, token: str):
        if not token or not token.strip():
            raise ValidationError("token cannot be empty")

        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def make_summary(
        self,
        owner: str,
        repo: str,
        spec_list: List[PulseOxSpec],
        mode: str = 'md'
    ) -> str:
        """Create a summary of all monitored files.

        Args:
            owner: Repository owner
            repo: Repository name
            spec_list: List of PulseOxSpec objects to monitor
            mode: Output format ('md' for markdown, 'org' for org-mode)

        Returns:
            Formatted summary string

        Raises:
            ValidationError: If parameters are invalid
        """
        if not owner or not owner.strip():
            raise ValidationError("owner cannot be empty")
        if not repo or not repo.strip():
            raise ValidationError("repo cannot be empty")
        if mode not in self.VALID_MODES:
            raise ValidationError(
                f"mode must be one of {self.VALID_MODES}, got: {mode}"
            )
        if not isinstance(spec_list, list):
            raise ValidationError("spec_list must be a list")

        errors = []
        missing = []
        ok = []

        for spec in spec_list:
            if not isinstance(spec, PulseOxSpec):
                raise ValidationError(
                    "All items in spec_list must be PulseOxSpec"
                )

            entry = self._check_spec(owner, repo, spec, mode)
            if entry:
                status = entry['status']
                if status == 'ERROR':
                    errors.append(entry)
                elif status == 'MISSING':
                    missing.append(entry)
                elif status == 'OK':
                    ok.append(entry)
                else:
                    # This should not happen if _check_spec is correct
                    raise PulseOxError(
                        f"Unexpected status from _check_spec: {status}"
                    )

        return self._format_summary(errors, missing, ok, mode)

    def write_summary(
        self,
        owner: str,
        repo: str,
        summary: str,
        path_to_summary: str
    ) -> requests.Response:
        """Write summary to a file in GitHub repository.

        Args:
            owner: Repository owner
            repo: Repository name
            summary: Summary content to write
            path_to_summary: Path where summary should be written

        Returns:
            Response from GitHub API

        Raises:
            ValidationError: If parameters are invalid
            GitHubAPIError: If the API request fails
        """
        if not owner or not owner.strip():
            raise ValidationError("owner cannot be empty")
        if not repo or not repo.strip():
            raise ValidationError("repo cannot be empty")
        if summary is None:
            raise ValidationError("summary cannot be None")
        if not path_to_summary or not path_to_summary.strip():
            raise ValidationError("path_to_summary cannot be empty")

        url = (
            f"{self.base_url}/repos/{owner}/{repo}/contents/"
            f"{path_to_summary}"
        )

        # Get current file SHA if exists
        try:
            get_response = requests.get(
                url, headers=self.headers, timeout=30
            )
        except requests.RequestException as e:
            raise GitHubAPIError(
                f"Failed to fetch summary file info: {e}"
            )

        sha = None
        if get_response.status_code == 200:
            try:
                sha = get_response.json().get("sha")
            except (ValueError, KeyError) as e:
                raise GitHubAPIError(
                    f"Failed to parse GitHub response: {e}"
                )

        # Encode and prepare payload
        try:
            encoded_content = base64.b64encode(
                summary.encode('utf-8')
            ).decode('utf-8')
        except UnicodeEncodeError as e:
            raise ValidationError(f"Failed to encode summary: {e}")

        payload = {
            "message": f"Update summary at {path_to_summary}",
            "content": encoded_content,
        }

        if sha:
            payload["sha"] = sha

        try:
            response = requests.put(
                url, json=payload, headers=self.headers, timeout=30
            )
        except requests.RequestException as e:
            raise GitHubAPIError(
                f"Failed to write summary: {e}"
            )

        return response

    def _check_spec(
        self,
        owner: str,
        repo: str,
        spec: PulseOxSpec,
        mode: str
    ) -> Optional[dict]:
        """Check a single spec and determine its status.

        Args:
            owner: Repository owner
            repo: Repository name
            spec: PulseOxSpec to check
            mode: Output format

        Returns:
            Dictionary with status info or None
        """
        url = (
            f"{self.base_url}/repos/{owner}/{repo}/contents/"
            f"{spec.path_to_file}"
        )

        try:
            response = requests.get(
                url, headers=self.headers, timeout=30
            )
        except requests.RequestException:
            # Network error, treat as missing
            return {
                'status': 'MISSING',
                'path': spec.path_to_file,
                'note': '',
                'updated': None,
                'mode': mode,
            }

        if response.status_code != 200:
            return {
                'status': 'MISSING',
                'path': spec.path_to_file,
                'note': '',
                'updated': None,
                'mode': mode,
            }

        # Decode content
        try:
            response_data = response.json()
            if 'content' not in response_data:
                raise KeyError("No content in response")
            content = base64.b64decode(
                response_data['content']
            ).decode('utf-8')
        except (ValueError, KeyError, UnicodeDecodeError):
            # Failed to decode, treat as missing metadata
            return {
                'status': 'MISSING',
                'path': spec.path_to_file,
                'note': '',
                'updated': None,
                'mode': mode,
            }

        # Parse metadata
        metadata = self._parse_metadata(content)

        if not metadata:
            return {
                'status': 'MISSING',
                'path': spec.path_to_file,
                'note': '',
                'updated': None,
                'mode': mode,
            }

        # Determine status based on metadata and schedule
        metadata_status = metadata.get('status', '').upper()

        # ERROR status takes precedence
        if metadata_status == 'ERROR':
            status = 'ERROR'
        else:
            # Check if update is within schedule
            is_within = self._is_within_schedule(
                metadata.get('updated'), spec.schedule
            )

            if not is_within:
                status = 'MISSING'
            elif metadata_status == 'OK':
                status = 'OK'
            elif metadata_status == 'WARNING':
                # Treat WARNING as OK if within schedule
                status = 'OK'
            else:
                # Unknown status, treat as missing
                status = 'MISSING'

        return {
            'status': status,
            'path': spec.path_to_file,
            'note': metadata.get('note', ''),
            'updated': metadata.get('updated'),
            'mode': mode,
        }

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

    def _format_summary(
        self,
        errors: List[dict],
        missing: List[dict],
        ok: List[dict],
        mode: str
    ) -> str:
        """Format the summary output.

        Args:
            errors: List of error entries
            missing: List of missing entries
            ok: List of ok entries
            mode: Output format ('md' or 'org')

        Returns:
            Formatted summary string
        """
        sections = []

        if errors:
            sections.append(
                self._format_section("ERROR", errors, mode)
            )

        if missing:
            sections.append(
                self._format_section("MISSING", missing, mode)
            )

        if ok:
            sections.append(
                self._format_section("OK", ok, mode)
            )

        return "\n\n".join(sections)

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
        path = entry['path']
        note = entry['note']
        updated = entry['updated'] or 'N/A'

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
