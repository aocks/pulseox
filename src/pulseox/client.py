"""Dashboard for PulseOx.
"""

from datetime import datetime, timezone
import os
from typing import Annotated, Literal

import requests
from pydantic import BaseModel, Field, PrivateAttr

from pulseox.specs import (ValidationError, GitHubAPIError,
                           JOB_REPORT, make_dt_formatter, create_metadata,
                           DEFAULT_BASE_URL)
from pulseox.generic_backend import make_backend


class PulseOxClient(BaseModel):
    """Client for posting content to repositories (GitHub or local git).
    """

    token: Annotated[str, Field(exclude=True, default='', description=(
        'GitHub personal access token to access repo.'))]

    show_tz: Annotated[str, Field(default=os.environ.get(
        'TZ', 'US/Eastern'), description=(
        'String name of timezone to display for datetimes'))]

    git_executable: Annotated[str, Field(default='/usr/bin/git', description=(
        'Path to git executable for local git repos'))]

    _base_url: str = PrivateAttr(default_factory=lambda: (
        os.environ.get('DEFAULT_PULSEOX_URL', DEFAULT_BASE_URL)))

    def post(
        self,
        owner: str,
        repo: str,
        path_to_file: str,
        content: str,
        report: Literal[JOB_REPORT] = "GOOD",
        note: str = ""
    ):
        """Post content to a file in a repository (GitHub or local git).

        Args:
            owner: Repository owner (or None for local git repos)
            repo: Repository name (or file:// path for local git repos)
            path_to_file: Path to the file in the repository
            content: Content to write to the file
            report: Report code (must be 'GOOD', 'BAD')
            note: Optional short text note

        Returns:
            Response object from the GitHub API, or None for local git

        Raises:
            ValidationError: If parameters are invalid
            GitHubAPIError: If GitHub API request fails
        """
        self._validate_post_params(
            owner, repo, path_to_file, content, report)

        metadata = create_metadata(path_to_file, report, note, self.show_tz)
        full_content = f"{content}\n\n{metadata}"

        backend = make_backend(
            owner, repo,
            token=self.token,
            base_url=self._base_url,
            git_executable=self.git_executable
        )
        return backend.update_file(path_to_file, full_content)

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
        # For local git repos, owner can be None
        if owner is not None and (not owner or not owner.strip()):
            raise ValidationError("owner cannot be empty string")
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
