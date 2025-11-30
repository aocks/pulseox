"""GitHub backend for PulseOx.

This module contains all GitHub-specific functionality for interacting with
GitHub repositories via the GitHub API.
"""

import base64
import logging as rawLogger
from typing import Optional, List, Tuple, Annotated

import requests
from pydantic import BaseModel, Field, SkipValidation


LOGGER = rawLogger.getLogger(__name__)


def make_headers(token):
    """Make GitHub API headers.

    Args:
        token: GitHub personal access token

    Returns:
        Dictionary of headers for GitHub API requests

    Raises:
        ValueError: If token is empty
    """
    if not token:
        raise ValueError('Must set token before interacting with GitHub')
    return {"Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"}


def download_github_file(token: str, owner: str, repo: str, path: str,
                         ref: str = "main", timeout: int = 30,
                         base_url: str = "https://api.github.com") -> bytes:
    """Download a file from a GitHub repository.

    Args:
        token: Github token.
        owner: Repository owner (username or organization)
        repo: Repository name
        path: Path to the file within the repository
        ref: Branch, tag, or commit SHA (default: "main")
        timeout: Request timeout in seconds
        base_url: GitHub API base URL

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


class GitHubBackend(BaseModel):
    """Backend for GitHub API operations.

    This class encapsulates all GitHub-specific operations including
    updating files, writing trees, and fetching remote data.

    Args:
        token: GitHub personal access token
        base_url: GitHub API base URL (default: https://api.github.com)
    """

    token: Annotated[str, Field(exclude=True, default='', description=(
        'GitHub personal access token to access repo.'))]

    base_url: Annotated[str, Field(default="https://api.github.com",
                                   description='GitHub API base URL')]

    _latest_response: Annotated[
        Optional[SkipValidation[requests.Response]], Field(
            description=('Latest response object from interacting with'
                         ' GitHub. This is just a convenience to help'
                         ' verify or investigate response from the'
                         ' GitHub API.'), default=None, exclude=True)]

    def update_file(
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
        from pulseox.specs import GitHubAPIError, ValidationError

        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"

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

        self._latest_response = response
        return response

    def write_github_file(
        self,
        owner: str,
        repo: str,
        content: str,
        path: str,
        commit_message: str = ''
    ) -> None:
        """Write given content to path on GitHub.

        Args:
            owner: Repository owner
            repo: Repository name
            content: File content
            path: File path in repository
            commit_message: Commit message (default: "Update {path}")

        Raises:
            ValidationError: If parameters are invalid
            GitHubAPIError: If the API request fails
        """
        from pulseox.specs import ValidationError, GitHubAPIError

        commit_message = commit_message or f"Update {path}"
        if not owner or not owner.strip():
            raise ValidationError("owner cannot be empty")
        if not repo or not repo.strip():
            raise ValidationError("repo cannot be empty")
        if not path or not path.strip():
            raise ValidationError("path cannot be empty")

        url = (
            f"{self.base_url}/repos/{owner}/{repo}/contents/"
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

    def write_github_tree(
        self,
        owner: str,
        repo: str,
        files: List[Tuple[str, str]],
        commit_message: str = 'Update files',
        branch: str = 'main'
    ) -> None:
        """Write multiple files to GitHub in a single commit.

        Args:
            owner: Repository owner
            repo: Repository name
            files: List of (path, content) tuples
            commit_message: Commit message for the update
            branch: Branch name to commit to (default: 'main')

        Raises:
            ValidationError: If parameters are invalid
            GitHubAPIError: If the API request fails
        """
        from pulseox.specs import ValidationError, GitHubAPIError

        if not owner or not owner.strip():
            raise ValidationError("owner cannot be empty")
        if not repo or not repo.strip():
            raise ValidationError("repo cannot be empty")
        if not files:
            raise ValidationError("files list cannot be empty")

        LOGGER.debug(f"Starting write_github_tree for {len(files)} files to {owner}/{repo} branch {branch}")

        # Get reference to branch
        ref_url = f"{self.base_url}/repos/{owner}/{repo}/git/refs/heads/{branch}"
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
        commit_url = f"{self.base_url}/repos/{owner}/{repo}/git/commits/{base_commit_sha}"
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
            blob_url = f"{self.base_url}/repos/{owner}/{repo}/git/blobs"
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
        tree_url = f"{self.base_url}/repos/{owner}/{repo}/git/trees"
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
        commit_url = f"{self.base_url}/repos/{owner}/{repo}/git/commits"
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

        LOGGER.debug("Successfully completed write_github_tree")
        self._latest_response = update_response


def update_github_spec(spec, token: str, base_url: str = "https://api.github.com"):
    """Update a PulseOxSpec by querying GitHub.

    This function queries GitHub to update the report status of a spec.

    Args:
        spec: PulseOxSpec instance to update
        token: GitHub personal access token
        base_url: GitHub API base URL
    """
    import logging
    from pulseox.specs import JOB_REPORT

    url = (f"{base_url}/repos/{spec.owner}/{spec.repo}/contents/"
           f"{spec.path}")

    spec.report = 'NOT_REPORTED'
    spec.note = None

    try:
        response = requests.get(
            url, headers=make_headers(token=token), timeout=30)
    except requests.RequestException as problem:
        # Network error, treat as missing
        logging.exception('Problem try to get report.')
        spec.note = 'network error: ' + str(problem)
        return

    status_code = getattr(response, 'status_code', -1)
    if status_code != 200:
        spec.note = f'error: ({status_code=}) ' + getattr(
            response, 'reason', 'unknown')
        return

    try:  # Decode content
        response_data = response.json()
        if 'content' not in response_data:
            logging.exception("No content in response")
            spec.note = "No content in GitHub response"
            return
        content = base64.b64decode(response_data['content']).decode(
            'utf-8')
    except (ValueError, KeyError, UnicodeDecodeError) as problem:
        spec.note = f'Problem decoding GitHub response: {problem}'
        logging.exception(spec.note)
        # Failed to decode, treat as missing metadata
        return

    # Parse metadata
    metadata = spec._parse_metadata(content)

    if not metadata:
        spec.note = 'Failed to parse metadata'
        logging.error(spec.note)
        return

    # Determine report based on metadata and schedule
    metadata_report = metadata.get('report', '').upper()

    if metadata_report in JOB_REPORT:
        spec.report = metadata_report
    else:  # Unknown report, treat as BAD
        spec.report = 'BAD'
        spec.note = f' report {metadata_report=} treated as bad'
        logging.error(spec.note)

    if metadata.get('note', None):
        spec.note = metadata.get('note')
    spec.updated = metadata.get('updated')
