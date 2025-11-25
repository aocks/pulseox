"""Tests for github interactions using mock github server.
"""


import datetime
import random
import re
import tempfile
import time
import shutil

from pulseox.specs import PulseOxSpec
from pulseox.client import PulseOxClient
from pulseox.dashboard import PulseOxDashboard
from pulseox.test_tools.mock_github_server import MockGitHubServer


class TestGitHub:

    _tokens = None
    _tmpdir = None
    _server = None
    _base_url = None
    
    @classmethod
    def setup_class(cls):
        if not cls._tokens:
            cls._tokens = [''.join([random.choice(
                'abcdefghijklmnopqrst_123ABCDEFG') for _i in range(20)])]
        if not cls._tmpdir:
            cls._tmpdir = tempfile.mkdtemp()
        if not cls._server:
            cls._server = MockGitHubServer(
                acceptable_tokens=cls._tokens,
                repo_root=cls._tmpdir)
            cls._server.start(host='127.0.0.1', port=5001,
                              threaded=True)
            time.sleep(0.5)  # Give server time to start
            cls._base_url = cls._server.get_base_url()
            print(f'Start test GitHub server at {cls._base_url}')

    @classmethod
    def teardown_class(cls):
        cls._server.stop()
        shutil.rmtree(cls._tmpdir)
        cls._server = None
        cls._tmpdir = None

    @staticmethod
    def make_test_spec_list(rinfo):
        return [
            PulseOxSpec(path='quick_example.md',
                        schedule=datetime.timedelta(seconds=60), **rinfo),
            PulseOxSpec(path='long_example.md',
                        schedule=datetime.timedelta(minutes=60), **rinfo)
            ]

    def do_client_update(self, path, rinfo):
        client = PulseOxClient(token=self._tokens[0])
        client._base_url = self._base_url
        resp = client.post(path_to_file=path,
                           content='test update', **rinfo)
        assert resp.status_code in (200, 201)
        
    def test_basic_example(self):
        rinfo = {'owner': 'testowner', 'repo': 'testrepo'}
        spec_list = self.make_test_spec_list(rinfo)
        dashboard = PulseOxDashboard(
            token=self._tokens[0], spec_list=spec_list, **rinfo)
        dashboard._base_url = self._base_url
        dashboard.compute_summary()
        assert len(dashboard.summary.status['MISSING']) == 2

        self.do_client_update('quick_example.md', rinfo)
        dashboard.compute_summary()
        dashboard.write_summary()
        assert list(dashboard.summary.status['OK']) == ['quick_example.md']

        change_pattern = (
            r'^# Changes\s+- \[quick_example\.md\]\(quick_example\.md\)'
            r' MISSING --> OK \d{4}-\d{2}-\d{2} \d{2}:\d{2} EST\s+')
        main_pattern = (
            r'# OK\s+- \[quick_example\.md\]\(quick_example\.md\)'
            r' \d{4}-\d{2}-\d{2} \d{2}:\d{2} EST\s+'
            r'# MISSING\s+- \[long_example\.md\]\(long_example\.md\)'
            r' error: \(status_code=404\) NOT FOUND None')
        mtch = re.search(change_pattern + main_pattern,
                         dashboard.summary.text, re.MULTILINE)
        assert mtch
        
        dashboard.compute_summary()  # Recompute to verify that
        mtch = re.search('^' + main_pattern,  # Change section omitted
                         dashboard.summary.text, re.MULTILINE)
        assert mtch

    def test_lookup(self):
        """Now run a test where we lookup spec_list from GitHub.
        """

        rinfo = {'owner': 'testowner', 'repo': 'testrepo'}        
        dashboard = PulseOxDashboard(token=self._tokens[0], **rinfo)
        dashboard._base_url = self._base_url
        dashboard.get_remote_data()
        dashboard.compute_summary()
        assert list(dashboard.summary.status['OK']) == ['quick_example.md']
        assert list(dashboard.summary.status['MISSING']) == [
            'long_example.md']        
        
        
