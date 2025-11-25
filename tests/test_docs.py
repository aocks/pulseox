"""Tests for docs.
"""


import datetime
import doctest
import os
import random
import re
import tempfile
import time
import shutil

from pulseox.specs import PulseOxSpec
from pulseox.client import PulseOxClient
from pulseox.dashboard import PulseOxDashboard
from pulseox.test_tools.mock_github_server import MockGitHubServer


class TestDocs:

    _tokens = None
    _tmpdir = None
    _server = None
    _base_url = None
    _prev_base_urls = None

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
        cls._prev_base_url = {'client': PulseOxClient._base_url,
                              'dashboard': PulseOxDashboard._base_url}
        PulseOxClient._base_url = cls._base_url
        PulseOxDashboard._base_url = cls._base_url

    @classmethod
    def teardown_class(cls):
        cls._server.stop()
        shutil.rmtree(cls._tmpdir)
        cls._server = None
        cls._tmpdir = None

    def test_readme(self):
        fname = os.path.join(os.path.dirname(__file__), '..', 'README.md')
        doctest.testfile(fname, module_relative=False, globs={
            'YOUR_GITHUB_PAT': self._tokens[0],
            'owner': 'testowner', 'repo': 'testrepo'
        }, optionflags=(doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE))

