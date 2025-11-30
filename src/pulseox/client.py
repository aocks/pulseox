"""Dashboard for PulseOx.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal

import requests
from pydantic import BaseModel, Field

from pulseox.specs import (ValidationError, GitHubAPIError,
                           JOB_REPORT, make_dt_formatter)
from pulseox.github import GitHubBackend


class PulseOxClient(BaseModel):
    """Client for posting content to GitHub repositories.
    """

    token: Annotated[str, Field(exclude=True, default='', description=(
        'GitHub personal access token to access repo.'))]

    show_tz: Annotated[str, Field(default='US/Eastern', description=(
        'String name of timezone to display for datetimes'))]

    _base_url: str = "https://api.github.com"

    def post(
        self,
        owner: str,
        repo: str,
        path_to_file: str,
        content: str,
        report: Literal[JOB_REPORT] = "GOOD",
        note: str = ""
    ) -> requests.Response:
        """Post content to a file in a GitHub repository.

        Args:
            owner: Repository owner
            repo: Repository name
            path_to_file: Path to the file in the repository
            content: Content to write to the file
            report: Report code (must be 'GOOD', 'BAD')
            note: Optional short text note

        Returns:
            Response object from the GitHub API

        Raises:
            ValidationError: If parameters are invalid
            GitHubAPIError: If GitHub API request fails
        """
        self._validate_post_params(
            owner, repo, path_to_file, content, report)

        metadata = self._create_metadata(
            path_to_file, report, note)
        full_content = f"{content}\n\n{metadata}"

        backend = GitHubBackend(token=self.token, base_url=self._base_url)
        return backend.update_file(
            owner, repo, path_to_file, full_content
        )

    def _validate_post_params(
        self,
        owner: str,
        repo: str,
        path_to_file: str,
        content: str,
        report: str
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
        if report not in JOB_REPORT:
            raise ValidationError(
                f"report must be one of {JOB_REPORT}, "
                f"got: {report}"
            )

    def _create_metadata(
        self,
        path_to_file: str,
        report: Literal[JOB_REPORT],
        note: str
    ) -> str:
        """Create metadata section for the file.

        Args:
            path_to_file: Path to determine file format
            report: Report code
            note: Optional note

        Returns:
            Formatted metadata string
        """
        timestamp = make_dt_formatter(self.show_tz)(
            datetime.now(timezone.utc).isoformat())

        if path_to_file.endswith('.md'):
            header = "# Metadata"
        elif path_to_file.endswith('.org'):
            header = "* Metadata"
        else:
            # Default to markdown for unknown extensions
            header = "# Metadata"

        metadata_lines = [
            header,
            f"- report: {report}",
            f"- updated: {timestamp}",
        ]

        if note:
            metadata_lines.append(f"- note: {note}")

        return "\n".join(metadata_lines)
