"""Generic backend abstraction for PulseOx.

This module provides a unified interface for working with both GitHub
and local git repositories, abstracting away the differences between
the two backends.
"""

from typing import Optional, List, Tuple, Annotated
from pydantic import BaseModel, Field

from pulseox.github import GitHubBackend
from pulseox.git import GitBackend


class GenericBackend(BaseModel):
    """Generic backend that wraps either GitHub or Git backend.

    This class provides a unified interface for operations that works
    with both GitHub and local git repositories.

    Args:
        owner: Repository owner (None for local git repos)
        repo: Repository name (or file:// path for local git repos)
        backend_type: Type of backend ('github' or 'git')
        token: GitHub personal access token (for GitHub backend)
        base_url: GitHub API base URL (for GitHub backend)
        git_executable: Path to git executable (for git backend)
        auto_push: Whether to auto-push commits (for git backend)
    """

    owner: Optional[str]
    repo: str
    backend_type: Annotated[str, Field(description="Backend type: 'github' or 'git'")]

    token: Annotated[str, Field(exclude=True, default='', description=(
        'GitHub personal access token (for GitHub backend)'))]

    base_url: Annotated[str, Field(default="https://api.github.com",
                                   description='GitHub API base URL')]

    git_executable: Annotated[str, Field(default='/usr/bin/git',
                                        description='Path to git executable')]

    auto_push: Annotated[bool, Field(default=True,
                                    description='Auto-push for git backend')]

    _backend: Optional[object] = None

    def model_post_init(self, __context):
        """Initialize the appropriate backend after model initialization."""
        if self.backend_type == 'git':
            repo_path = self.repo[7:]  # Remove 'file://' prefix
            self._backend = GitBackend(
                repo_path=repo_path,
                git_executable=self.git_executable,
                auto_push=self.auto_push
            )
        elif self.backend_type == 'github':
            self._backend = GitHubBackend(
                token=self.token,
                base_url=self.base_url
            )
        else:
            raise ValueError(f"Invalid backend_type: {self.backend_type}")

    def update_file(self, path: str, content: str, commit_message: Optional[str] = None):
        """Update or create a file in the repository.

        Args:
            path: File path relative to repository root
            content: File content
            commit_message: Optional commit message

        Returns:
            Response object from GitHub API, or None for git backend
        """
        if self.backend_type == 'git':
            self._backend.update_file(path, content, commit_message)
            return None
        else:  # github
            return self._backend.update_file(self.owner, self.repo, path, content)

    def write_tree(self, files: List[Tuple[str, str]], commit_message: str = 'Update files'):
        """Write multiple files to the repository in a single commit.

        Args:
            files: List of (path, content) tuples
            commit_message: Commit message for the update

        Returns:
            None for git backend, or the latest response from GitHub backend
        """
        if self.backend_type == 'git':
            self._backend.write_tree(files, commit_message)
            return None
        else:  # github
            self._backend.write_github_tree(
                self.owner, self.repo, files, commit_message
            )
            return self._backend._latest_response

    def update_spec(self, spec):
        """Update a PulseOxSpec by querying the backend.

        Args:
            spec: PulseOxSpec instance to update
        """
        if self.backend_type == 'git':
            from pulseox.git import update_git_spec
            repo_path = self.repo[7:]  # Remove 'file://' prefix
            update_git_spec(spec, repo_path=repo_path, git_executable=self.git_executable)
        else:  # github
            from pulseox.github import update_github_spec
            update_github_spec(spec, token=self.token, base_url=self.base_url)

    def get_project_root(self, path_to_summary: str = 'summary.md') -> str:
        """Get the project root URL/path for creating links.

        Args:
            path_to_summary: Path to summary file (used to determine format)

        Returns:
            URL or file path prefix for creating links
        """
        if self.backend_type == 'git':
            repo_path = self.repo[7:]  # Remove 'file://' prefix
            return f'file://{repo_path}/'
        else:  # github
            return f'https://github.com/{self.owner}/{self.repo}/blob/main/'

    def format_summary_link(self, path_to_summary: str, mode: str = 'md'):
        """Format a link to the summary file.

        Args:
            path_to_summary: Path to the summary file
            mode: Output format ('md' for markdown, 'org' for org-mode)

        Returns:
            Formatted link string
        """
        from pulseox.specs import ValidationError

        project_root = self.get_project_root(path_to_summary)

        if self.backend_type == 'git':
            repo_path = self.repo[7:]  # Remove 'file://' prefix
            text = repo_path
        else:  # github
            text = f'{self.owner}/{self.repo}'

        url = project_root + path_to_summary

        if mode == 'md':
            return f"[{text}]({url})"
        elif mode == 'org':
            return f"[[{url}][{text}]]"
        else:
            raise ValidationError(f"Invalid mode in format_summary_link: {mode}")

    def get_latest_response(self):
        """Get the latest response from the backend (GitHub only).

        Returns:
            Response object for GitHub backend, None for git backend
        """
        if self.backend_type == 'github':
            return self._backend._latest_response
        return None


def make_backend(
    owner: Optional[str],
    repo: str,
    token: str = '',
    base_url: str = "https://api.github.com",
    git_executable: str = '/usr/bin/git',
    auto_push: bool = True
) -> GenericBackend:
    """Factory function to create the appropriate backend.

    Args:
        owner: Repository owner (None for local git repos)
        repo: Repository name (or file:// path for local git repos)
        token: GitHub personal access token (for GitHub backend)
        base_url: GitHub API base URL (for GitHub backend)
        git_executable: Path to git executable (for git backend)
        auto_push: Whether to auto-push commits (for git backend)

    Returns:
        GenericBackend instance configured with the appropriate backend
    """
    # Determine backend type based on owner and repo
    if owner is None and repo.startswith('file://'):
        backend_type = 'git'
    else:
        backend_type = 'github'

    return GenericBackend(
        owner=owner,
        repo=repo,
        backend_type=backend_type,
        token=token,
        base_url=base_url,
        git_executable=git_executable,
        auto_push=auto_push
    )
