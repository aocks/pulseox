"""Dashboard for PulseOx.
"""

import base64
import logging as rawLogger
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Annotated, Dict


import requests
from pydantic import BaseModel, Field, SkipValidation

from pulseox.specs import (VALID_MODES, VALID_STATUSES, make_headers,
                           download_github_file, ValidationError,
                           GitHubAPIError, PulseOxSpec)


LOGGER = rawLogger.getLogger(__name__)


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
        section_info = [(n, self.status.get(n, [])) for n in VALID_STATUSES]
        sections = [self._format_section(n, s, mode)
                    for n, s in section_info if s]
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
    spec_list: Annotated[Optional[List[PulseOxSpec]], Field(description=(
        'Optional list of PulseOxSpec instances to describe what the'
        ' dashboard will monitor. You can provide `spec_list` at init'
        ' or use the `fill_spec_list` method to read from GitHub'),
                                                            default=None)]

    token: Annotated[str, Field(exclude=True, default='', description=(
        'GitHub personal access token to access repo. Only required'
        ' if you call methods which interact with GitHub.'))]
    summary: Optional[PulseOxSummary] = None

    _base_url: str = "https://api.github.com"
    _latest_response: Annotated[
        Optional[SkipValidation[requests.Response]], Field(
            description=('Latest response object from interacting with'
                     ' GitHub. This is just a convenience to help verify or'
                     ' investigate response from the GitHub API.'),
            default=None, exclude=True)]


    def fill_spec_list(self, github_file='summary.md.json', ref='main'):
        """Fill the `spec_list` property by downloading from GitHub.

        :param github_file='summary.md.json':  Path to GitHub file
                                               to download.

        :param ref='main':   Branch to reference in download.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  Returns `self` to help in chaning.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  This will read the `spec_list` property from GitHub.
                  By default it reads the JSON version of the dashboard
                  written by `write_summary`. This makes it easy to do
                  something like

          response = PulseOxDashboard(token=token,owner=owner,repo=repo
                     ).fill_spec_list().write_summary()

        """
        content = download_github_file(self.token, self.owner,
                                       self.repo, github_file, ref)
        content = content.decode('utf8')
        parsed = self.__class__.model_validate_json(content)
        self.spec_list = parsed.spec_list
        return self

    def fill_summary(
        self,
        mode: str = 'md'
    ) -> str:
        """Fill summary field with summary of all monitored files.

        Args:
            mode: Output format ('md' for markdown, 'org' for org-mode)

        Returns:
            A copy of self to help in chaining.

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
        if not self.spec_list:
            LOGGER.info('Empty spec_list; calling fill_spec_list')
            self.fill_spec_list()
        if not self.spec_list or not isinstance(self.spec_list, list):
            raise ValidationError("spec_list must be non-empty list")

        status = {n: [] for n in VALID_STATUSES}

        for spec in self.spec_list:
            spec.update(token=self.token)
            if spec.status not in VALID_STATUSES:
                raise ValueError(f'Bad status in {spec=}')
            status[spec.status].append(spec)

        self.summary = PulseOxSummary(status=status)
        self.summary.fill()
        return self

    def write_summary(
        self,
        path_to_summary: str = 'summary.md',
        path_to_summary_json: Optional[str] = None):
        """Write summary to a file in GitHub repository.

        Args:
            path_to_summary: Path where summary should be written
            path_to_summary_json: Optional path to where to write a JSON
                                  version of the summary. If not provided
                                  we use `path_to_summary + '.json'`.

        Returns:
            A copy of self to help in chaining. See the _latest_response
            property to get the response from the GitHub API when
            writing the summary data.

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
        if not path_to_summary_json:
            path_to_summary_json = path_to_summary + '.json'
        files = [
            (path_to_summary_json, self.model_dump_json(indent=2)),
            (path_to_summary, self.summary.text)
        ]

        self._write_github_tree(files, 'Update summary files')
        return self

    def _write_github_tree(self, files: List[tuple],
                           commit_message: str = 'Update files',
                           branch: str = 'main'):
        """Helper to write multiple files to GitHub in a single commit.

        Args:
            files: List of (path, content) tuples
            commit_message: Commit message for the update
            branch: Branch name to commit to (default: 'main')

        Raises:
            ValidationError: If parameters are invalid
            GitHubAPIError: If the API request fails
        """
        if not self.owner or not self.owner.strip():
            raise ValidationError("owner cannot be empty")
        if not self.repo or not self.repo.strip():
            raise ValidationError("repo cannot be empty")
        if not files:
            raise ValidationError("files list cannot be empty")

        LOGGER.debug(f"Starting _write_github_tree for {len(files)} files to {self.owner}/{self.repo} branch {branch}")

        # Get reference to branch
        ref_url = f"{self._base_url}/repos/{self.owner}/{self.repo}/git/refs/heads/{branch}"
        LOGGER.debug(f"Fetching branch reference from {ref_url}")

        try:
            ref_response = requests.get(
                ref_url, headers=make_headers(token=self.token), timeout=30)
        except requests.RequestException as e:
            LOGGER.error(f"Request exception getting branch reference: {e}")
            raise GitHubAPIError(f"Failed to get branch reference: {e}")

        LOGGER.debug(f"Branch reference response: status={ref_response.status_code}")
        if ref_response.status_code != 200:
            LOGGER.error(f"Failed to get branch reference: {ref_response.text}")
            raise GitHubAPIError(
                f"Failed to get branch reference (status {ref_response.status_code}): {ref_response.text}")

        try:
            base_commit_sha = ref_response.json()['object']['sha']
            LOGGER.debug(f"Base commit SHA: {base_commit_sha}")
        except (ValueError, KeyError) as e:
            LOGGER.error(f"Failed to parse branch reference: {e}, response: {ref_response.text}")
            raise GitHubAPIError(f"Failed to parse branch reference: {e}")

        # Get base commit to find base tree
        commit_url = f"{self._base_url}/repos/{self.owner}/{self.repo}/git/commits/{base_commit_sha}"
        LOGGER.debug(f"Fetching base commit from {commit_url}")

        try:
            commit_response = requests.get(
                commit_url, headers=make_headers(token=self.token), timeout=30)
        except requests.RequestException as e:
            LOGGER.error(f"Request exception getting base commit: {e}")
            raise GitHubAPIError(f"Failed to get base commit: {e}")

        LOGGER.debug(f"Base commit response: status={commit_response.status_code}")
        if commit_response.status_code != 200:
            LOGGER.error(f"Failed to get base commit: {commit_response.text}")
            raise GitHubAPIError(
                f"Failed to get base commit (status {commit_response.status_code}): {commit_response.text}")

        try:
            base_tree_sha = commit_response.json()['tree']['sha']
            LOGGER.debug(f"Base tree SHA: {base_tree_sha}")
        except (ValueError, KeyError) as e:
            LOGGER.error(f"Failed to parse commit response: {e}, response: {commit_response.text}")
            raise GitHubAPIError(f"Failed to parse commit response: {e}")

        # Create blobs for each file
        tree_items = []
        for path, content in files:
            if not path or not path.strip():
                raise ValidationError("file path cannot be empty")

            LOGGER.debug(f"Creating blob for {path} ({len(content)} bytes)")

            # Create blob
            blob_url = f"{self._base_url}/repos/{self.owner}/{self.repo}/git/blobs"
            try:
                encoded_content = base64.b64encode(
                    content.encode('utf-8')).decode('utf-8')
            except UnicodeEncodeError as e:
                LOGGER.error(f"Failed to encode content for {path}: {e}")
                raise ValidationError(f"Failed to encode content for {path}: {e}")

            blob_payload = {
                "content": encoded_content,
                "encoding": "base64"
            }

            try:
                blob_response = requests.post(
                    blob_url, json=blob_payload,
                    headers=make_headers(token=self.token), timeout=30)
            except requests.RequestException as e:
                LOGGER.error(f"Request exception creating blob for {path}: {e}")
                raise GitHubAPIError(f"Failed to create blob for {path}: {e}")

            LOGGER.debug(f"Blob response for {path}: status={blob_response.status_code}")
            if blob_response.status_code != 201:
                LOGGER.error(f"Failed to create blob for {path}: {blob_response.text}")
                raise GitHubAPIError(
                    f"Failed to create blob for {path} (status {blob_response.status_code}): {blob_response.text}")

            try:
                blob_sha = blob_response.json()['sha']
                LOGGER.debug(f"Blob SHA for {path}: {blob_sha}")
            except (ValueError, KeyError) as e:
                LOGGER.error(f"Failed to parse blob response for {path}: {e}, response: {blob_response.text}")
                raise GitHubAPIError(f"Failed to parse blob response for {path}: {e}")

            tree_items.append({
                "path": path,
                "mode": "100644",
                "type": "blob",
                "sha": blob_sha
            })

        # Create tree
        tree_url = f"{self._base_url}/repos/{self.owner}/{self.repo}/git/trees"
        tree_payload = {
            "base_tree": base_tree_sha,
            "tree": tree_items
        }

        LOGGER.debug(f"Creating tree with {len(tree_items)} items")

        try:
            tree_response = requests.post(
                tree_url, json=tree_payload,
                headers=make_headers(token=self.token), timeout=30)
        except requests.RequestException as e:
            LOGGER.error(f"Request exception creating tree: {e}")
            raise GitHubAPIError(f"Failed to create tree: {e}")

        LOGGER.debug(f"Tree response: status={tree_response.status_code}")
        if tree_response.status_code != 201:
            LOGGER.error(f"Failed to create tree: {tree_response.text}")
            raise GitHubAPIError(
                f"Failed to create tree (status {tree_response.status_code}): {tree_response.text}")

        try:
            new_tree_sha = tree_response.json()['sha']
            LOGGER.debug(f"New tree SHA: {new_tree_sha}")
        except (ValueError, KeyError) as e:
            LOGGER.error(f"Failed to parse tree response: {e}, response: {tree_response.text}")
            raise GitHubAPIError(f"Failed to parse tree response: {e}")

        # Create commit
        commit_url = f"{self._base_url}/repos/{self.owner}/{self.repo}/git/commits"
        commit_payload = {
            "message": commit_message,
            "tree": new_tree_sha,
            "parents": [base_commit_sha]
        }

        LOGGER.debug(f"Creating commit with message: {commit_message}")

        try:
            new_commit_response = requests.post(
                commit_url, json=commit_payload,
                headers=make_headers(token=self.token), timeout=30)
        except requests.RequestException as e:
            LOGGER.error(f"Request exception creating commit: {e}")
            raise GitHubAPIError(f"Failed to create commit: {e}")

        LOGGER.debug(f"Commit response: status={new_commit_response.status_code}")
        if new_commit_response.status_code != 201:
            LOGGER.error(f"Failed to create commit: {new_commit_response.text}")
            raise GitHubAPIError(
                f"Failed to create commit (status {new_commit_response.status_code}): {new_commit_response.text}")

        try:
            new_commit_sha = new_commit_response.json()['sha']
            LOGGER.debug(f"New commit SHA: {new_commit_sha}")
        except (ValueError, KeyError) as e:
            LOGGER.error(f"Failed to parse commit response: {e}, response: {new_commit_response.text}")
            raise GitHubAPIError(f"Failed to parse commit response: {e}")

        # Update reference
        update_ref_payload = {
            "sha": new_commit_sha,
            "force": False
        }

        LOGGER.debug(f"Updating branch reference to {new_commit_sha}")

        try:
            update_response = requests.patch(
                ref_url, json=update_ref_payload,
                headers=make_headers(token=self.token), timeout=30)
        except requests.RequestException as e:
            LOGGER.error(f"Request exception updating reference: {e}")
            raise GitHubAPIError(f"Failed to update reference: {e}")

        LOGGER.debug(f"Update reference response: status={update_response.status_code}")
        if update_response.status_code not in (200, 201):
            LOGGER.error(f"Failed to update reference: {update_response.text}")
            raise GitHubAPIError(
                f"Failed to update reference (status {update_response.status_code}): {update_response.text}")

        LOGGER.debug("Successfully completed _write_github_tree")
        self._latest_response = update_response

    def _write_github_file(self, content: str, path: str,
                           commit_message: str = ''):
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
            f"{self._base_url}/repos/{self.owner}/{self.repo}/contents/"
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

        self._latest_response = response
