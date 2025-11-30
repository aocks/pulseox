"""Local git repository backend for PulseOx.

This module contains functionality for interacting with local git repositories
as an alternative to GitHub.
"""

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Annotated

from pydantic import BaseModel, Field, field_validator


LOGGER = logging.getLogger(__name__)


class GitBackend(BaseModel):
    """Backend for local git repository operations.

    This class encapsulates all git-specific operations for working with
    local git repositories as an alternative to GitHub.

    Args:
        repo_path: Path to the git repository
        git_executable: Path to git executable (default: /usr/bin/git)
        auto_push: Whether to automatically push after commits (default: True)
    """

    repo_path: Annotated[str, Field(description='Path to the git repository')]

    git_executable: Annotated[str, Field(
        default='/usr/bin/git',
        description='Path to git executable')]

    auto_push: Annotated[bool, Field(
        default=True,
        description='Whether to automatically push after commits')]

    @field_validator('repo_path')
    @classmethod
    def validate_repo_path(cls, v):
        """Validate that repo_path is an absolute path."""
        path = Path(v)
        if not path.is_absolute():
            raise ValueError(f"repo_path must be absolute, got: {v}")
        return str(path.resolve())

    def model_post_init(self, __context):
        """Validate repo after initialization."""
        self._check_repo()
        self._check_git_executable()

    def _check_git_executable(self):
        """Check that git executable exists and is executable.

        Raises:
            FileNotFoundError: If git executable is not found
        """
        git_path = Path(self.git_executable)
        if not git_path.exists():
            raise FileNotFoundError(
                f"Git executable not found at: {self.git_executable}")
        if not os.access(self.git_executable, os.X_OK):
            raise PermissionError(
                f"Git executable not executable: {self.git_executable}")

    def _check_repo(self):
        """Check that repo_path is a valid git repository.

        Raises:
            ValueError: If repo_path is not a valid git repository
        """
        repo_path = Path(self.repo_path)
        if not repo_path.exists():
            raise ValueError(f"Repository path does not exist: {self.repo_path}")

        git_dir = repo_path / '.git'
        if not git_dir.exists():
            raise ValueError(
                f"Not a git repository (no .git directory): {self.repo_path}")

    def _run_git(self, *args, check=True, capture_output=True, text=True):
        """Run a git command in the repository.

        Args:
            *args: Arguments to pass to git
            check: Whether to check return code
            capture_output: Whether to capture stdout/stderr
            text: Whether to decode output as text

        Returns:
            subprocess.CompletedProcess result

        Raises:
            subprocess.CalledProcessError: If command fails and check=True
        """
        from pulseox.specs import ValidationError

        cmd = [self.git_executable] + list(args)
        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_path,
                check=check,
                capture_output=capture_output,
                text=text
            )
            return result
        except subprocess.CalledProcessError as e:
            LOGGER.error(f"Git command failed: {' '.join(cmd)}")
            LOGGER.error(f"Exit code: {e.returncode}")
            LOGGER.error(f"Stderr: {e.stderr}")
            raise ValidationError(
                f"Git command failed: {' '.join(args)}\n{e.stderr}") from e
        except FileNotFoundError as e:
            raise ValidationError(
                f"Git executable not found: {self.git_executable}") from e

    def get_file_content(self, path: str) -> str:
        """Read file content from the repository.

        Args:
            path: Path to file relative to repo root

        Returns:
            File content as string

        Raises:
            FileNotFoundError: If file doesn't exist
            ValidationError: If file cannot be read
        """
        from pulseox.specs import ValidationError

        file_path = Path(self.repo_path) / path
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        try:
            return file_path.read_text()
        except Exception as e:
            raise ValidationError(f"Failed to read file {path}: {e}") from e

    def get_file_mtime(self, path: str) -> Optional[datetime]:
        """Get the last modification time of a file from git log.

        Args:
            path: Path to file relative to repo root

        Returns:
            Datetime of last modification, or None if file not in git history
        """
        try:
            # Get last commit time for this file
            result = self._run_git(
                'log', '--format=%ai', '-n', '1', '--', path)

            if result.stdout.strip():
                # Parse the datetime string
                from dateutil import parser as dateparser
                return dateparser.parse(result.stdout.strip())
            return None
        except Exception as e:
            LOGGER.warning(f"Failed to get mtime for {path}: {e}")
            return None

    def update_file(
        self,
        path: str,
        content: str,
        commit_message: Optional[str] = None
    ) -> None:
        """Update or create a file in the git repository.

        Args:
            path: File path relative to repository root
            content: File content
            commit_message: Optional commit message (default: "Update {path}")

        Raises:
            ValidationError: If the operation fails
        """
        from pulseox.specs import ValidationError

        commit_message = commit_message or f"Update {path}"

        file_path = Path(self.repo_path) / path

        # Create parent directories if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        try:
            file_path.write_text(content)
        except Exception as e:
            raise ValidationError(f"Failed to write file {path}: {e}") from e

        # Stage the file
        self._run_git('add', path)

        # Commit
        self._run_git('commit', '-m', commit_message)

        # Push if auto_push is enabled
        if self.auto_push:
            remotes = os.path.join(self.repo_path, '.git', 'refs', 'remotes')
            if os.path.exists(remotes):
                try:
                    self._run_git('push')
                except Exception as e:
                    LOGGER.exception(f"Failed to push: {e}")
                    raise
            else:
                logging.info('No push since no remotes in %s', remotes)


    def write_tree(
        self,
        files: List[Tuple[str, str]],
        commit_message: str = 'Update files'
    ) -> None:
        """Write multiple files to the repository in a single commit.

        Args:
            files: List of (path, content) tuples
            commit_message: Commit message for the update

        Raises:
            ValidationError: If the operation fails
        """
        from pulseox.specs import ValidationError

        if not files:
            raise ValidationError("files list cannot be empty")

        # Write all files
        for path, content in files:
            file_path = Path(self.repo_path) / path
            file_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                file_path.write_text(content)
            except Exception as e:
                raise ValidationError(
                    f"Failed to write file {path}: {e}") from e

            # Stage the file
            self._run_git('add', path)

        # Commit all changes
        self._run_git('commit', '-m', commit_message)

        # Push if auto_push is enabled
        if self.auto_push:
            try:
                self._run_git('push')
            except Exception as e:
                LOGGER.warning(f"Failed to push: {e}")


def update_git_spec(spec, repo_path: str, git_executable: str = '/usr/bin/git'):
    """Update a PulseOxSpec by reading from a local git repository.

    This function reads a file from a local git repository and updates the
    spec's report status based on the metadata found in the file.

    Args:
        spec: PulseOxSpec instance to update
        repo_path: Path to the git repository
        git_executable: Path to git executable
    """
    import logging
    from pulseox.specs import JOB_REPORT

    backend = GitBackend(repo_path=repo_path, git_executable=git_executable)

    spec.report = 'NOT_REPORTED'
    spec.note = None

    try:
        content = backend.get_file_content(spec.path)
    except FileNotFoundError:
        spec.note = f'File not found: {spec.path}'
        logging.error(spec.note)
        return
    except Exception as e:
        spec.note = f'Error reading file: {e}'
        logging.exception(spec.note)
        return

    # Parse metadata from content
    metadata = spec._parse_metadata(content)

    if not metadata:
        spec.note = 'Failed to parse metadata'
        logging.error(spec.note)
        return

    # Determine report based on metadata
    metadata_report = metadata.get('report', '').upper()

    if metadata_report in JOB_REPORT:
        spec.report = metadata_report
    else:
        spec.report = 'BAD'
        spec.note = f'report {metadata_report=} treated as bad'
        logging.error(spec.note)

    if metadata.get('note'):
        spec.note = metadata.get('note')

    spec.updated = metadata.get('updated')
