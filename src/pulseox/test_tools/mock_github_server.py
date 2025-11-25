"""Mock GitHub API Server for testing.

This module provides a MockGitHubServer class that implements a subset of the
GitHub API v3, allowing local testing without making real API calls to GitHub.
"""

import base64
import hashlib
import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any
from wsgiref.simple_server import make_server, WSGIServer

from flask import Flask, request, jsonify


class MockGitHubServer:
    """A mock GitHub API server for testing.

    This server implements the GitHub API v3 endpoints used by pulseox,
    allowing you to test GitHub interactions without hitting the real API.

    Attributes:
        acceptable_tokens: List of valid authentication tokens.
        repo_root: Path to the git repository to manage.
        app: Flask application instance.
        server: WSGI server instance (when running).
        server_thread: Thread running the server (when running).
    """

    def __init__(self, acceptable_tokens: List[str], repo_root: str):
        """Initialize the mock GitHub server.

        Args:
            acceptable_tokens: List of valid authentication tokens.
            repo_root: Path to the root directory of the git repository.
        """
        self.acceptable_tokens = set(acceptable_tokens)
        self.repo_root = Path(repo_root).resolve()
        self.app = Flask(__name__)
        self.server: Optional[WSGIServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self._setup_routes()

        # Ensure repo exists and is initialized
        if not self.repo_root.exists():
            raise ValueError(f"Repository root does not exist: {self.repo_root}")

        if not (self.repo_root / ".git").exists():
            self._git_init()

    def _git_init(self):
        """Initialize a git repository if it doesn't exist."""
        subprocess.run(
            ["git", "init"],
            cwd=self.repo_root,
            check=True,
            capture_output=True
        )
        # Configure git user
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=self.repo_root,
            check=True,
            capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.repo_root,
            check=True,
            capture_output=True
        )
        # Disable commit signing to avoid interference from hooks
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=self.repo_root,
            check=True,
            capture_output=True
        )
        # Disable other signing mechanisms
        subprocess.run(
            ["git", "config", "gpg.format", "openpgp"],
            cwd=self.repo_root,
            check=True,
            capture_output=True
        )
        # Set default branch to main
        subprocess.run(
            ["git", "checkout", "-b", "main"],
            cwd=self.repo_root,
            check=True,
            capture_output=True
        )
        # Create an initial empty commit so the branch exists
        # This is needed for git tree API operations
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "Initial commit"],
            cwd=self.repo_root,
            check=True,
            capture_output=True
        )

    def _git(self, *args, check=True, **kwargs) -> subprocess.CompletedProcess:
        """Run a git command in the repository.

        Args:
            *args: Arguments to pass to git.
            check: Whether to check return code (raises CalledProcessError on failure).
            **kwargs: Additional arguments for subprocess.run.

        Returns:
            CompletedProcess instance.

        Raises:
            subprocess.CalledProcessError: If check=True and command fails.
        """
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=self.repo_root,
                check=check,
                capture_output=True,
                text=True,
                **kwargs
            )
            return result
        except subprocess.CalledProcessError as e:
            # Add more context to git errors for easier debugging
            error_msg = f"Git command failed: git {' '.join(args)}\n"
            error_msg += f"Working directory: {self.repo_root}\n"
            error_msg += f"Return code: {e.returncode}\n"
            if e.stdout:
                error_msg += f"Stdout: {e.stdout}\n"
            if e.stderr:
                error_msg += f"Stderr: {e.stderr}"
            raise RuntimeError(error_msg) from e

    def _compute_sha(self, content: bytes, obj_type: str = "blob") -> str:
        """Compute git SHA-1 hash for content.

        Args:
            content: The content bytes to hash.
            obj_type: Git object type (blob, tree, commit).

        Returns:
            SHA-1 hash as hex string.
        """
        header = f"{obj_type} {len(content)}\0".encode()
        return hashlib.sha1(header + content).hexdigest()

    def _validate_token(self) -> bool:
        """Validate the authorization token from the request.

        Returns:
            True if token is valid, False otherwise.
        """
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("token "):
            return False
        token = auth_header[6:]  # Remove "token " prefix
        return token in self.acceptable_tokens

    def _setup_routes(self):
        """Set up Flask routes for GitHub API endpoints."""

        @self.app.before_request
        def check_auth():
            """Check authentication before processing requests."""
            if not self._validate_token():
                return jsonify({
                    "message": "Bad credentials",
                    "documentation_url": "https://docs.github.com/rest"
                }), 401

        # Route: GET /repos/{owner}/{repo}/contents/{path:path}
        @self.app.route("/repos/<owner>/<repo>/contents/<path:path>", methods=["GET"])
        def get_contents(owner, repo, path):
            """Get file contents from the repository."""
            return self._handle_get_contents(owner, repo, path)

        # Route: PUT /repos/{owner}/{repo}/contents/{path:path}
        @self.app.route("/repos/<owner>/<repo>/contents/<path:path>", methods=["PUT"])
        def put_contents(owner, repo, path):
            """Create or update file contents in the repository."""
            return self._handle_put_contents(owner, repo, path)

        # Route: GET /repos/{owner}/{repo}/git/refs/heads/{branch}
        @self.app.route("/repos/<owner>/<repo>/git/refs/heads/<branch>", methods=["GET"])
        def get_ref(owner, repo, branch):
            """Get a branch reference."""
            return self._handle_get_ref(owner, repo, branch)

        # Route: PATCH /repos/{owner}/{repo}/git/refs/heads/{branch}
        @self.app.route("/repos/<owner>/<repo>/git/refs/heads/<branch>", methods=["PATCH"])
        def patch_ref(owner, repo, branch):
            """Update a branch reference."""
            return self._handle_patch_ref(owner, repo, branch)

        # Route: GET /repos/{owner}/{repo}/git/commits/{sha}
        @self.app.route("/repos/<owner>/<repo>/git/commits/<sha>", methods=["GET"])
        def get_commit(owner, repo, sha):
            """Get a commit object."""
            return self._handle_get_commit(owner, repo, sha)

        # Route: POST /repos/{owner}/{repo}/git/blobs
        @self.app.route("/repos/<owner>/<repo>/git/blobs", methods=["POST"])
        def create_blob(owner, repo):
            """Create a blob object."""
            return self._handle_create_blob(owner, repo)

        # Route: POST /repos/{owner}/{repo}/git/trees
        @self.app.route("/repos/<owner>/<repo>/git/trees", methods=["POST"])
        def create_tree(owner, repo):
            """Create a tree object."""
            return self._handle_create_tree(owner, repo)

        # Route: POST /repos/{owner}/{repo}/git/commits
        @self.app.route("/repos/<owner>/<repo>/git/commits", methods=["POST"])
        def create_commit(owner, repo):
            """Create a commit object."""
            return self._handle_create_commit(owner, repo)

    def _handle_get_contents(self, owner: str, repo: str, path: str):
        """Handle GET /repos/{owner}/{repo}/contents/{path}.

        Args:
            owner: Repository owner.
            repo: Repository name.
            path: Path to the file in the repository.
        """
        ref = request.args.get("ref", "main")

        # Check if file exists in the specified ref
        result = self._git(
            "show", f"{ref}:{path}",
            check=False
        )

        if result.returncode != 0:
            return jsonify({
                "message": "Not Found",
                "documentation_url": "https://docs.github.com/rest/reference/repos#get-repository-content"
            }), 404

        content = result.stdout.encode()
        encoded_content = base64.b64encode(content).decode()
        sha = self._compute_sha(content)

        return jsonify({
            "name": os.path.basename(path),
            "path": path,
            "sha": sha,
            "size": len(content),
            "type": "file",
            "content": encoded_content,
            "encoding": "base64",
            "url": f"http://localhost/repos/{owner}/{repo}/contents/{path}",
            "html_url": f"http://localhost/{owner}/{repo}/blob/main/{path}",
            "download_url": f"http://localhost/{owner}/{repo}/raw/main/{path}"
        }), 200

    def _handle_put_contents(self, owner: str, repo: str, path: str):
        """Handle PUT /repos/{owner}/{repo}/contents/{path}.

        Args:
            owner: Repository owner.
            repo: Repository name.
            path: Path to the file in the repository.
        """
        data = request.get_json()

        if not data or "content" not in data or "message" not in data:
            return jsonify({
                "message": "Invalid request: missing required fields"
            }), 400

        # Decode content
        try:
            content = base64.b64decode(data["content"])
        except Exception as e:
            return jsonify({
                "message": f"Invalid base64 content: {str(e)}"
            }), 400

        try:
            # Write file to disk
            absolute_file_path = self.repo_root / path
            absolute_file_path.parent.mkdir(parents=True, exist_ok=True)
            absolute_file_path.write_bytes(content)

            # Stage and commit the file
            self._git("add", path)
            self._git("commit", "-m", data["message"])

            # Get the new commit SHA
            commit_sha = self._git("rev-parse", "HEAD").stdout.strip()

            # Calculate file SHA
            file_sha = self._compute_sha(content)

            # Get tree SHA
            tree_sha = self._git("rev-parse", "HEAD^{tree}").stdout.strip()

            return jsonify({
                "content": {
                    "name": os.path.basename(path),
                    "path": path,
                    "sha": file_sha,
                    "size": len(content),
                    "type": "file",
                    "url": f"http://localhost/repos/{owner}/{repo}/contents/{path}",
                    "html_url": f"http://localhost/{owner}/{repo}/blob/main/{path}",
                    "download_url": f"http://localhost/{owner}/{repo}/raw/main/{path}"
                },
                "commit": {
                    "sha": commit_sha,
                    "url": f"http://localhost/repos/{owner}/{repo}/git/commits/{commit_sha}",
                    "html_url": f"http://localhost/{owner}/{repo}/commit/{commit_sha}",
                    "author": {
                        "date": datetime.now(timezone.utc).isoformat(),
                        "name": "Test User",
                        "email": "test@example.com"
                    },
                    "committer": {
                        "date": datetime.now(timezone.utc).isoformat(),
                        "name": "Test User",
                        "email": "test@example.com"
                    },
                    "message": data["message"],
                    "tree": {
                        "sha": tree_sha,
                        "url": f"http://localhost/repos/{owner}/{repo}/git/trees/{tree_sha}"
                    }
                }
            }), 201 if "sha" not in data else 200
        except RuntimeError as e:
            # Git command failed
            return jsonify({
                "message": f"Failed to update file: {str(e)}"
            }), 500

    def _handle_get_ref(self, owner: str, repo: str, branch: str):
        """Handle GET /repos/{owner}/{repo}/git/refs/heads/{branch}."""
        result = self._git(
            "rev-parse", f"refs/heads/{branch}",
            check=False
        )

        if result.returncode != 0:
            return jsonify({
                "message": "Not Found",
                "documentation_url": "https://docs.github.com/rest/reference/git#get-a-reference"
            }), 404

        commit_sha = result.stdout.strip()

        return jsonify({
            "ref": f"refs/heads/{branch}",
            "node_id": "mock_node_id",
            "url": f"http://localhost/repos/{owner}/{repo}/git/refs/heads/{branch}",
            "object": {
                "sha": commit_sha,
                "type": "commit",
                "url": f"http://localhost/repos/{owner}/{repo}/git/commits/{commit_sha}"
            }
        }), 200

    def _handle_patch_ref(self, owner: str, repo: str, branch: str):
        """Handle PATCH /repos/{owner}/{repo}/git/refs/heads/{branch}."""
        data = request.get_json()

        if not data or "sha" not in data:
            return jsonify({
                "message": "Invalid request: missing sha field"
            }), 400

        new_sha = data["sha"]
        force = data.get("force", False)

        # Update the branch reference
        cmd = ["update-ref", f"refs/heads/{branch}", new_sha]
        result = self._git(*cmd, check=False)

        if result.returncode != 0:
            return jsonify({
                "message": f"Failed to update reference: {result.stderr}"
            }), 422

        return jsonify({
            "ref": f"refs/heads/{branch}",
            "node_id": "mock_node_id",
            "url": f"http://localhost/repos/{owner}/{repo}/git/refs/heads/{branch}",
            "object": {
                "sha": new_sha,
                "type": "commit",
                "url": f"http://localhost/repos/{owner}/{repo}/git/commits/{new_sha}"
            }
        }), 200

    def _handle_get_commit(self, owner: str, repo: str, sha: str):
        """Handle GET /repos/{owner}/{repo}/git/commits/{sha}."""
        # Get commit details
        result = self._git("cat-file", "-p", sha, check=False)

        if result.returncode != 0:
            return jsonify({
                "message": "Not Found",
                "documentation_url": "https://docs.github.com/rest/reference/git#get-a-commit"
            }), 404

        # Parse commit object
        commit_data = result.stdout
        lines = commit_data.split('\n')

        tree_sha = None
        parents = []
        message_lines = []
        in_message = False

        for line in lines:
            if line.startswith('tree '):
                tree_sha = line.split()[1]
            elif line.startswith('parent '):
                parents.append(line.split()[1])
            elif line == '':
                in_message = True
            elif in_message:
                message_lines.append(line)

        message = '\n'.join(message_lines).strip()

        parent_objects = [
            {
                "sha": parent,
                "url": f"http://localhost/repos/{owner}/{repo}/git/commits/{parent}"
            }
            for parent in parents
        ]

        return jsonify({
            "sha": sha,
            "url": f"http://localhost/repos/{owner}/{repo}/git/commits/{sha}",
            "author": {
                "date": datetime.now(timezone.utc).isoformat(),
                "name": "Test User",
                "email": "test@example.com"
            },
            "committer": {
                "date": datetime.now(timezone.utc).isoformat(),
                "name": "Test User",
                "email": "test@example.com"
            },
            "message": message,
            "tree": {
                "sha": tree_sha,
                "url": f"http://localhost/repos/{owner}/{repo}/git/trees/{tree_sha}"
            },
            "parents": parent_objects
        }), 200

    def _handle_create_blob(self, owner: str, repo: str):
        """Handle POST /repos/{owner}/{repo}/git/blobs."""
        data = request.get_json()

        if not data or "content" not in data:
            return jsonify({
                "message": "Invalid request: missing content field"
            }), 400

        encoding = data.get("encoding", "utf-8")

        if encoding == "base64":
            try:
                content = base64.b64decode(data["content"])
            except Exception as e:
                return jsonify({
                    "message": f"Invalid base64 content: {str(e)}"
                }), 400
        else:
            content = data["content"].encode()

        try:
            # Create blob using git hash-object
            # Note: We override text=False here because we're passing binary data
            result = subprocess.run(
                ["git", "hash-object", "-w", "--stdin"],
                cwd=self.repo_root,
                input=content,
                check=True,
                capture_output=True,
                text=False
            )

            blob_sha = result.stdout.decode().strip()

            return jsonify({
                "url": f"http://localhost/repos/{owner}/{repo}/git/blobs/{blob_sha}",
                "sha": blob_sha,
                "size": len(content),
                "node_id": "mock_node_id"
            }), 201
        except subprocess.CalledProcessError as e:
            error_msg = f"Git command failed: git hash-object -w --stdin\n"
            error_msg += f"Working directory: {self.repo_root}\n"
            error_msg += f"Return code: {e.returncode}\n"
            if e.stderr:
                error_msg += f"Stderr: {e.stderr.decode()}"
            return jsonify({
                "message": f"Failed to create blob: {error_msg}"
            }), 500
        except Exception as e:
            return jsonify({
                "message": f"Failed to create blob: {str(e)}"
            }), 500

    def _handle_create_tree(self, owner: str, repo: str):
        """Handle POST /repos/{owner}/{repo}/git/trees."""
        data = request.get_json()

        if not data or "tree" not in data:
            return jsonify({
                "message": "Invalid request: missing tree field"
            }), 400

        base_tree = data.get("base_tree")
        tree_entries = data["tree"]

        try:
            # Build tree using git mktree
            # Format: <mode> <type> <sha>\t<path>
            tree_input = []
            for entry in tree_entries:
                mode = entry.get("mode", "100644")
                obj_type = entry.get("type", "blob")
                sha = entry["sha"]
                path = entry["path"]
                tree_input.append(f"{mode} {obj_type} {sha}\t{path}")

            # If base_tree is provided, we need to read it first and merge
            if base_tree:
                base_result = self._git("ls-tree", base_tree, check=False)
                if base_result.returncode == 0:
                    base_entries = {}
                    for line in base_result.stdout.strip().split('\n'):
                        if line:
                            parts = line.split('\t')
                            if len(parts) == 2:
                                base_entries[parts[1]] = parts[0]

                    # Merge: new entries override base entries
                    new_paths = {entry["path"] for entry in tree_entries}
                    for path, info in base_entries.items():
                        if path not in new_paths:
                            tree_input.append(f"{info}\t{path}")

            # Create the tree
            result = self._git(
                "mktree",
                input='\n'.join(tree_input) + '\n',
                check=True
            )

            tree_sha = result.stdout.strip()

            # Build response tree entries
            response_entries = []
            for entry in tree_entries:
                response_entries.append({
                    "path": entry["path"],
                    "mode": entry.get("mode", "100644"),
                    "type": entry.get("type", "blob"),
                    "sha": entry["sha"],
                    "url": f"http://localhost/repos/{owner}/{repo}/git/blobs/{entry['sha']}"
                })

            return jsonify({
                "sha": tree_sha,
                "url": f"http://localhost/repos/{owner}/{repo}/git/trees/{tree_sha}",
                "tree": response_entries,
                "truncated": False
            }), 201
        except RuntimeError as e:
            return jsonify({
                "message": f"Failed to create tree: {str(e)}"
            }), 500

    def _handle_create_commit(self, owner: str, repo: str):
        """Handle POST /repos/{owner}/{repo}/git/commits."""
        data = request.get_json()

        if not data or "message" not in data or "tree" not in data:
            return jsonify({
                "message": "Invalid request: missing required fields"
            }), 400

        message = data["message"]
        tree_sha = data["tree"]
        parents = data.get("parents", [])

        try:
            # Build commit command
            env = os.environ.copy()
            env["GIT_AUTHOR_NAME"] = "Test User"
            env["GIT_AUTHOR_EMAIL"] = "test@example.com"
            env["GIT_COMMITTER_NAME"] = "Test User"
            env["GIT_COMMITTER_EMAIL"] = "test@example.com"

            cmd = ["commit-tree", tree_sha, "-m", message]
            for parent in parents:
                cmd.extend(["-p", parent])

            result = self._git(*cmd, env=env, check=True)
            commit_sha = result.stdout.strip()

            parent_objects = [
                {
                    "sha": parent,
                    "url": f"http://localhost/repos/{owner}/{repo}/git/commits/{parent}"
                }
                for parent in parents
            ]

            return jsonify({
                "sha": commit_sha,
                "url": f"http://localhost/repos/{owner}/{repo}/git/commits/{commit_sha}",
                "author": {
                    "date": datetime.now(timezone.utc).isoformat(),
                    "name": "Test User",
                    "email": "test@example.com"
                },
                "committer": {
                    "date": datetime.now(timezone.utc).isoformat(),
                    "name": "Test User",
                    "email": "test@example.com"
                },
                "message": message,
                "tree": {
                    "sha": tree_sha,
                    "url": f"http://localhost/repos/{owner}/{repo}/git/trees/{tree_sha}"
                },
                "parents": parent_objects,
                "verification": {
                    "verified": False,
                    "reason": "unsigned"
                }
            }), 201
        except RuntimeError as e:
            return jsonify({
                "message": f"Failed to create commit: {str(e)}"
            }), 500

    def start(self, host: str = "127.0.0.1", port: int = 5000, threaded: bool = True):
        """Start the mock GitHub server.

        Args:
            host: Host to bind to.
            port: Port to bind to.
            threaded: If True, run in a separate thread (non-blocking).
                     If False, run in the main thread (blocking).
        """
        if self.server is not None:
            raise RuntimeError("Server is already running")

        self.server = make_server(host, port, self.app)

        if threaded:
            self.server_thread = threading.Thread(
                target=self.server.serve_forever,
                daemon=True
            )
            self.server_thread.start()
            print(f"Mock GitHub server started at http://{host}:{port}")
        else:
            print(f"Mock GitHub server starting at http://{host}:{port}")
            self.server.serve_forever()

    def stop(self):
        """Stop the mock GitHub server."""
        if self.server is None:
            return

        self.server.shutdown()

        if self.server_thread is not None:
            self.server_thread.join(timeout=5)
            self.server_thread = None

        self.server = None
        print("\nMock GitHub server stopped\n")

    def get_base_url(self) -> str:
        """Get the base URL for the server.

        Returns:
            Base URL string (e.g., "http://127.0.0.1:5000").
        """
        if self.server is None:
            raise RuntimeError("Server is not running")

        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self):
        """Context manager entry."""
        self.start(threaded=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
