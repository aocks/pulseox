"""Tools for creating, updating, and monitoring GitHub pulse dashboards."""

import base64
from datetime import datetime, timedelta
from typing import List, Optional, Union
import re

import requests
from dateutil import parser as dateparser


class PulseOxSpec:
    """Specification for a monitored file in a GitHub repository.

    Args:
        path_to_file: Path to the file in the GitHub repository
        schedule: Either a datetime.timedelta or a cron string specifying
                  the expected update frequency
    """

    def __init__(
        self,
        path_to_file: str,
        schedule: Union[timedelta, str]
    ):
        self.path_to_file = path_to_file
        self.schedule = schedule


class PulseOxClient:
    """Client for posting content to GitHub repositories.

    Args:
        token: GitHub personal access token for API authentication
    """

    def __init__(self, token: str):
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
            status: Status code (e.g., 'OK', 'ERROR')
            optional_note: Optional short text note

        Returns:
            Response object from the GitHub API
        """
        metadata = self._create_metadata(
            path_to_file, status, optional_note
        )
        full_content = f"{content}\n\n{metadata}"

        return self._update_file(
            owner, repo, path_to_file, full_content
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
        timestamp = datetime.utcnow().isoformat() + "Z"

        if path_to_file.endswith('.md'):
            header = "# Metadata"
        elif path_to_file.endswith('.org'):
            header = "* Metadata"
        else:
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
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"

        # Get current file SHA if it exists
        get_response = requests.get(url, headers=self.headers)
        sha = None
        if get_response.status_code == 200:
            sha = get_response.json().get("sha")

        # Prepare update payload
        encoded_content = base64.b64encode(
            content.encode('utf-8')
        ).decode('utf-8')

        payload = {
            "message": f"Update {path}",
            "content": encoded_content,
        }

        if sha:
            payload["sha"] = sha

        return requests.put(url, json=payload, headers=self.headers)


class PulseOxDashboard:
    """Dashboard for monitoring multiple GitHub files.

    Args:
        token: GitHub personal access token for API authentication
    """

    def __init__(self, token: str):
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
        """
        errors = []
        missing = []
        ok = []

        for spec in spec_list:
            entry = self._check_spec(owner, repo, spec, mode)
            if entry:
                status = entry['status']
                if status == 'ERROR':
                    errors.append(entry)
                elif status == 'MISSING':
                    missing.append(entry)
                elif status == 'OK':
                    ok.append(entry)

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
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/"
        url += path_to_summary

        # Get current file SHA if exists
        get_response = requests.get(url, headers=self.headers)
        sha = None
        if get_response.status_code == 200:
            sha = get_response.json().get("sha")

        # Encode and prepare payload
        encoded_content = base64.b64encode(
            summary.encode('utf-8')
        ).decode('utf-8')

        payload = {
            "message": f"Update summary at {path_to_summary}",
            "content": encoded_content,
        }

        if sha:
            payload["sha"] = sha

        return requests.put(url, json=payload, headers=self.headers)

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
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/"
        url += spec.path_to_file
        response = requests.get(url, headers=self.headers)

        if response.status_code != 200:
            return {
                'status': 'MISSING',
                'path': spec.path_to_file,
                'note': '',
                'updated': None,
                'mode': mode,
            }

        # Decode content
        content = base64.b64decode(
            response.json()['content']
        ).decode('utf-8')

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

        # Check if update is within schedule
        is_within_schedule = self._is_within_schedule(
            metadata.get('updated'), spec.schedule
        )

        if metadata.get('status') == 'ERROR':
            status = 'ERROR'
        elif not is_within_schedule:
            status = 'MISSING'
        else:
            status = 'OK'

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

        now = datetime.utcnow()

        # For timedelta schedules
        if isinstance(schedule, timedelta):
            return (now - updated.replace(tzinfo=None)) <= schedule

        # For cron strings, we'd need a cron parser
        # For now, return True (would need croniter package)
        return True

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
        else:  # org
            header = f"* {title}"

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
        else:  # org
            link = f"[[{path}][{path}]]"

        parts = [f"- {link}"]
        if note:
            parts.append(note)
        parts.append(updated)

        return " ".join(parts)
