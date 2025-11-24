"""Dashboard for PulseOx.
"""

import base64
from datetime import datetime, timezone
from typing import Annotated

import requests
from pydantic import BaseModel, Field

from pulseox.specs import (ValidationError, GitHubAPIError,
                           make_headers, VALID_STATUSES)


class PulseOxClient(BaseModel):
    """Client for posting content to GitHub repositories.
    """

    token: Annotated[str, Field(exclude=True, default='', description=(
        'GitHub personal access token to access repo.'))]

    _base_url: str = "https://api.github.com"

    def post(
        self,
        owner: str,
        repo: str,
        path_to_file: str,
        content: str,
        status: str = "OK",
        note: str = ""
    ) -> requests.Response:
        """Post content to a file in a GitHub repository.

        Args:
            owner: Repository owner
            repo: Repository name
            path_to_file: Path to the file in the repository
            content: Content to write to the file
            status: Status code (must be 'OK', 'ERROR')
            note: Optional short text note

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
            path_to_file, status, note
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
        note: str
    ) -> str:
        """Create metadata section for the file.

        Args:
            path_to_file: Path to determine file format
            status: Status code
            note: Optional note

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

        if note:
            metadata_lines.append(f"- note: {note}")

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
        url = f"{self._base_url}/repos/{owner}/{repo}/contents/{path}"

        # Get current file SHA if it exists
        try:
            get_response = requests.get(
                url, headers=make_headers(self.token), timeout=30
            )
        except requests.RequestException as e:
            raise GitHubAPIError(f"Failed to fetch file info: {e}") from e

        sha = None
        if get_response.status_code == 200:
            try:
                sha = get_response.json().get("sha")
            except (ValueError, KeyError) as e:
                raise GitHubAPIError(f"Failed to parse GitHub response: {e}"
                                     ) from e

        # Prepare update payload
        try:
            encoded_content = base64.b64encode(
                content.encode('utf-8')
            ).decode('utf-8')
        except UnicodeEncodeError as e:
            raise ValidationError(f"Failed to encode content: {e}") from e

        payload = {
            "message": f"Update {path}",
            "content": encoded_content,
        }

        if sha:
            payload["sha"] = sha

        try:
            response = requests.put(
                url, json=payload, headers=make_headers(self.token),
                timeout=30)
        except requests.RequestException as e:
            raise GitHubAPIError(f"Failed to update file: {e}") from e

        return response
