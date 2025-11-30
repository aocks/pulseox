"""Tests for local git repository backend.
"""

import datetime
import os
import re
import subprocess
import tempfile
import shutil
from pathlib import Path

from pulseox.specs import PulseOxSpec
from pulseox.client import PulseOxClient
from pulseox.dashboard import PulseOxDashboard


class TestGit:

    _tmpdir = None
    _repo_path = None

    @classmethod
    def setup_class(cls):
        """Set up a temporary git repository for testing."""
        if not cls._tmpdir:
            cls._tmpdir = tempfile.mkdtemp()
            cls._repo_path = os.path.join(cls._tmpdir, 'test_repo')

            # Initialize git repo
            os.makedirs(cls._repo_path)
            subprocess.run(['git', 'init'], cwd=cls._repo_path, check=True,
                          capture_output=True)
            subprocess.run(['git', 'config', 'user.email', 'test@example.com'],
                          cwd=cls._repo_path, check=True, capture_output=True)
            subprocess.run(['git', 'config', 'user.name', 'Test User'],
                          cwd=cls._repo_path, check=True, capture_output=True)
            # Disable GPG signing for tests
            subprocess.run(['git', 'config', 'commit.gpgsign', 'false'],
                          cwd=cls._repo_path, check=True, capture_output=True)
            # Disable commit hooks
            subprocess.run(['git', 'config', 'core.hooksPath', '/dev/null'],
                          cwd=cls._repo_path, check=True, capture_output=True)

            # Create initial commit
            readme_path = os.path.join(cls._repo_path, 'README.md')
            Path(readme_path).write_text('# Test Repository\n')
            subprocess.run(['git', 'add', 'README.md'], cwd=cls._repo_path,
                          check=True, capture_output=True)
            subprocess.run(['git', 'commit', '-m', 'Initial commit'],
                          cwd=cls._repo_path, check=True, capture_output=True)

    @classmethod
    def teardown_class(cls):
        """Clean up temporary directory."""
        if cls._tmpdir:
            shutil.rmtree(cls._tmpdir)
            cls._tmpdir = None
            cls._repo_path = None

    @staticmethod
    def make_test_spec_list(repo_path):
        """Create test spec list for the git repository."""
        return [
            PulseOxSpec(
                owner=None,
                repo=f'file://{repo_path}',
                path='quick_example.md',
                schedule=datetime.timedelta(seconds=60)
            ),
            PulseOxSpec(
                owner=None,
                repo=f'file://{repo_path}',
                path='long_example.md',
                schedule=datetime.timedelta(minutes=60)
            )
        ]

    def do_client_update(self, path, repo_path):
        """Update a file using the client."""
        from datetime import datetime, timezone
        from pulseox.specs import make_dt_formatter

        # Get current timestamp
        timestamp = make_dt_formatter('US/Eastern')(
            datetime.now(timezone.utc).isoformat())

        # Create a backend temporarily to disable auto_push
        from pulseox.git import GitBackend
        backend = GitBackend(repo_path=repo_path, auto_push=False)
        backend.update_file(
            path,
            f'test update\n\n# Metadata\n- report: GOOD\n- updated: {timestamp}'
        )

    def test_basic_example(self):
        """Test basic dashboard functionality with local git."""
        spec_list = self.make_test_spec_list(self._repo_path)
        dashboard = PulseOxDashboard(
            owner=None,
            repo=f'file://{self._repo_path}',
            spec_list=spec_list
        )

        dashboard.compute_summary()
        # Both files should be missing initially
        assert len(dashboard.summary.status['MISSING']) == 2

        # Update one file
        self.do_client_update('quick_example.md', self._repo_path)

        dashboard.compute_summary()

        # Write summary (with auto_push disabled)
        from pulseox.git import GitBackend
        original_auto_push = GitBackend.model_fields['auto_push'].default
        GitBackend.model_fields['auto_push'].default = False

        try:
            dashboard.write_summary()
        finally:
            GitBackend.model_fields['auto_push'].default = original_auto_push

        # Check that quick_example is now OK
        assert list(dashboard.summary.status['OK']) == ['quick_example.md']

        # Verify summary text contains expected patterns
        change_pattern = (
            r'# Changes\s+'
            r'- \[quick_example\.md\]\(quick_example\.md\)'
            r' MISSING --> OK \d{4}-\d{2}-\d{2} \d{2}:\d{2} EST\s+')
        main_pattern = (
            r'# MISSING\s+'
            r'- \[long_example\.md\]\(long_example\.md\)'
            r' File not found: long_example\.md.*?\s+'
            r'# OK\s+'
            r'- \[quick_example\.md\]\(quick_example\.md\)'
            r' \d{4}-\d{2}-\d{2} \d{2}:\d{2} EST')

        mtch = re.search(change_pattern + main_pattern,
                         dashboard.summary.text, re.MULTILINE | re.DOTALL)
        assert mtch, f"Pattern not found in:\n{dashboard.summary.text}"

        # Recompute to verify change section is omitted
        dashboard.compute_summary()
        mtch = re.search('^' + main_pattern,
                         dashboard.summary.text, re.MULTILINE | re.DOTALL)
        assert mtch, f"Main pattern not found in:\n{dashboard.summary.text}"

    def test_client_post(self):
        """Test client post method with local git."""
        client = PulseOxClient()

        # Disable auto_push for test
        from pulseox.git import GitBackend
        original_auto_push = GitBackend.model_fields['auto_push'].default
        GitBackend.model_fields['auto_push'].default = False

        try:
            result = client.post(
                owner=None,
                repo=f'file://{self._repo_path}',
                path_to_file='test_post.md',
                content='This is a test',
                report='GOOD'
            )

            # For git backend, post returns None
            assert result is None

            # Verify file was created
            file_path = os.path.join(self._repo_path, 'test_post.md')
            assert os.path.exists(file_path)

            # Verify content
            content = Path(file_path).read_text()
            assert 'This is a test' in content
            assert '# Metadata' in content
            assert '- report: GOOD' in content

        finally:
            GitBackend.model_fields['auto_push'].default = original_auto_push

    def test_spec_update(self):
        """Test PulseOxSpec update with local git backend."""
        from datetime import datetime as dt, timezone, timedelta
        from pulseox.specs import make_dt_formatter
        from pulseox.git import GitBackend

        # Get current timestamp
        timestamp = make_dt_formatter('US/Eastern')(
            dt.now(timezone.utc).isoformat())

        # First, create a file with metadata
        backend = GitBackend(repo_path=self._repo_path, auto_push=False)

        content = f"""# Test Content

This is test content.

# Metadata
- report: GOOD
- updated: {timestamp}
- note: Test note
"""
        backend.update_file('spec_test.md', content)

        # Create spec and update it
        spec = PulseOxSpec(
            owner=None,
            repo=f'file://{self._repo_path}',
            path='spec_test.md',
            schedule=timedelta(hours=1)
        )

        spec.update()

        # Verify spec was updated correctly
        assert spec.report == 'GOOD'
        assert spec.note == 'Test note'
        assert spec.updated  # Just check it's not None
        assert 'EST' in spec.updated  # Check timezone is included

    def test_git_backend_validation(self):
        """Test GitBackend validation."""
        from pulseox.git import GitBackend
        from pulseox.specs import ValidationError
        import pytest

        # Test with non-existent path
        with pytest.raises(ValueError, match='does not exist'):
            GitBackend(repo_path='/nonexistent/path')

        # Test with non-git directory
        non_git_dir = os.path.join(self._tmpdir, 'non_git')
        os.makedirs(non_git_dir, exist_ok=True)
        with pytest.raises(ValueError, match='Not a git repository'):
            GitBackend(repo_path=non_git_dir)

    def test_write_multiple_files(self):
        """Test writing multiple files in one commit."""
        from pulseox.git import GitBackend

        backend = GitBackend(repo_path=self._repo_path, auto_push=False)

        files = [
            ('file1.md', '# File 1\nContent 1'),
            ('file2.md', '# File 2\nContent 2'),
            ('dir/file3.md', '# File 3\nContent 3')
        ]

        backend.write_tree(files, 'Add multiple files')

        # Verify all files exist
        for path, expected_content in files:
            file_path = os.path.join(self._repo_path, path)
            assert os.path.exists(file_path)
            content = Path(file_path).read_text()
            assert content == expected_content
