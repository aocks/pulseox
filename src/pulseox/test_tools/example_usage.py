"""Example usage of MockGitHubServer.

This script demonstrates how to use the MockGitHubServer for testing
pulseox code without hitting the real GitHub API.
"""

import base64
import tempfile
import time
from pathlib import Path

import requests

from pulseox.test_tools.mock_github_server import MockGitHubServer


def example_basic_usage():
    """Example: Basic server usage with context manager."""
    # Create a temporary directory for the test repo
    with tempfile.TemporaryDirectory() as temp_dir:
        print("=" * 60)
        print("Example 1: Basic Usage")
        print("=" * 60)

        # Start the mock server
        with MockGitHubServer(
            acceptable_tokens=["test-token-123"],
            repo_root=temp_dir
        ) as server:
            base_url = server.get_base_url()
            print(f"Server running at: {base_url}")

            headers = {
                "Authorization": "token test-token-123",
                "Accept": "application/vnd.github.v3+json"
            }

            # Example 1: Create a file
            print("\n1. Creating a file...")
            content = "Hello, World!".encode()
            encoded = base64.b64encode(content).decode()

            response = requests.put(
                f"{base_url}/repos/owner/repo/contents/hello.txt",
                headers=headers,
                json={
                    "message": "Add hello.txt",
                    "content": encoded
                }
            )
            print(f"   Status: {response.status_code}")
            print(f"   File SHA: {response.json()['content']['sha']}")

            # Example 2: Read the file back
            print("\n2. Reading the file...")
            response = requests.get(
                f"{base_url}/repos/owner/repo/contents/hello.txt",
                headers=headers
            )
            print(f"   Status: {response.status_code}")
            retrieved_content = base64.b64decode(
                response.json()["content"]
            ).decode()
            print(f"   Content: {retrieved_content}")

            # Example 3: Update the file
            print("\n3. Updating the file...")
            new_content = "Hello, Updated World!".encode()
            new_encoded = base64.b64encode(new_content).decode()
            file_sha = response.json()["sha"]

            response = requests.put(
                f"{base_url}/repos/owner/repo/contents/hello.txt",
                headers=headers,
                json={
                    "message": "Update hello.txt",
                    "content": new_encoded,
                    "sha": file_sha
                }
            )
            print(f"   Status: {response.status_code}")
            print(f"   New SHA: {response.json()['content']['sha']}")

        print("\nServer stopped automatically (context manager)\n")


def example_with_pulseox_client():
    """Example: Using with pulseox client code."""
    with tempfile.TemporaryDirectory() as temp_dir:
        print("=" * 60)
        print("Example 2: Using with PulseOx Client")
        print("=" * 60)

        # Start the mock server
        server = MockGitHubServer(
            acceptable_tokens=["my-test-token"],
            repo_root=temp_dir
        )
        server.start(host="127.0.0.1", port=5001, threaded=True)
        time.sleep(0.5)  # Give server time to start

        try:
            base_url = server.get_base_url()
            print(f"Server running at: {base_url}")

            # Now you can use this base_url with your pulseox code
            # For example, modify the GitHub API base URL in your client
            print(f"\nTo use with pulseox client:")
            print(f"  1. Set base_url = '{base_url}'")
            print(f"  2. Set token = 'my-test-token'")
            print(f"  3. Use owner/repo as usual (e.g., 'testowner/testrepo')")
            print(f"\nExample API endpoint:")
            print(f"  {base_url}/repos/testowner/testrepo/contents/myfile.txt")

        finally:
            server.stop()


def example_git_tree_api():
    """Example: Using the Git Tree API (for batch updates)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        print("=" * 60)
        print("Example 3: Git Tree API (Batch Updates)")
        print("=" * 60)

        with MockGitHubServer(
            acceptable_tokens=["test-token"],
            repo_root=temp_dir
        ) as server:
            base_url = server.get_base_url()
            headers = {
                "Authorization": "token test-token",
                "Accept": "application/vnd.github.v3+json"
            }

            # Step 1: Get current branch ref
            print("\n1. Getting branch reference...")
            response = requests.get(
                f"{base_url}/repos/owner/repo/git/refs/heads/main",
                headers=headers
            )
            print(f"   Status: {response.status_code}")
            current_commit = response.json()["object"]["sha"]
            print(f"   Current commit: {current_commit}")

            # Step 2: Get commit to get base tree
            print("\n2. Getting commit details...")
            response = requests.get(
                f"{base_url}/repos/owner/repo/git/commits/{current_commit}",
                headers=headers
            )
            base_tree = response.json()["tree"]["sha"]
            print(f"   Base tree: {base_tree}")

            # Step 3: Create blobs for new files
            print("\n3. Creating blobs...")
            blobs = {}
            for filename, content in [
                ("file1.txt", "Content 1"),
                ("file2.txt", "Content 2"),
                ("dir/file3.txt", "Content 3")
            ]:
                encoded = base64.b64encode(content.encode()).decode()
                response = requests.post(
                    f"{base_url}/repos/owner/repo/git/blobs",
                    headers=headers,
                    json={
                        "content": encoded,
                        "encoding": "base64"
                    }
                )
                blobs[filename] = response.json()["sha"]
                print(f"   {filename}: {blobs[filename]}")

            # Step 4: Create new tree
            print("\n4. Creating tree...")
            tree_entries = [
                {
                    "path": filename,
                    "mode": "100644",
                    "type": "blob",
                    "sha": sha
                }
                for filename, sha in blobs.items()
            ]
            response = requests.post(
                f"{base_url}/repos/owner/repo/git/trees",
                headers=headers,
                json={
                    "base_tree": base_tree,
                    "tree": tree_entries
                }
            )
            new_tree = response.json()["sha"]
            print(f"   New tree: {new_tree}")

            # Step 5: Create commit
            print("\n5. Creating commit...")
            response = requests.post(
                f"{base_url}/repos/owner/repo/git/commits",
                headers=headers,
                json={
                    "message": "Add multiple files",
                    "tree": new_tree,
                    "parents": [current_commit]
                }
            )
            new_commit = response.json()["sha"]
            print(f"   New commit: {new_commit}")

            # Step 6: Update branch reference
            print("\n6. Updating branch reference...")
            response = requests.patch(
                f"{base_url}/repos/owner/repo/git/refs/heads/main",
                headers=headers,
                json={
                    "sha": new_commit,
                    "force": False
                }
            )
            print(f"   Status: {response.status_code}")
            print(f"   Branch now points to: {response.json()['object']['sha']}")

            # Verify files exist
            print("\n7. Verifying files exist...")
            for filename in blobs.keys():
                response = requests.get(
                    f"{base_url}/repos/owner/repo/contents/{filename}",
                    headers=headers
                )
                if response.status_code == 200:
                    print(f"   ✓ {filename} exists")
                else:
                    print(f"   ✗ {filename} NOT found")


if __name__ == "__main__":
    example_basic_usage()
    print("\n")
    example_with_pulseox_client()
    print("\n")
    example_git_tree_api()
