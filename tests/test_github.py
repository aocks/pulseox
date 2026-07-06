"""Tests for github interactions using mock github server.
"""


import datetime
import os
import random
import re
import tempfile
import time
import shutil

from click.testing import CliRunner

from pulseox.specs import PulseOxSpec
from pulseox.client import PulseOxClient
from pulseox.dashboard import PulseOxDashboard
from pulseox.ui.cli import cli as po_cli
from pulseox.test_tools.mock_github_server import MockGitHubServer
from pulseox.test_tools import patches


class GenericGitHubTester:

    _tokens = None
    _tmpdir = None
    _server = None

    @classmethod
    def generic_setup_class(cls):
        if not cls._tokens:
            cls._tokens = [''.join([random.choice(
                'abcdefghijklmnopqrst_123ABCDEFG') for _i in range(20)])]
        if not cls._tmpdir:
            cls._tmpdir = tempfile.mkdtemp()
        if not cls._server:
            cls._server = MockGitHubServer(
                acceptable_tokens=cls._tokens,
                repo_root=cls._tmpdir)
            cls._server.start(threaded=True)
            time.sleep(0.5)  # Give server time to start            
            print('Start test GitHub server at: '
                  + str(cls._server.get_base_url()))
        patches.EnvPatcher.patch('DEFAULT_PULSEOX_URL',
                                 str(cls._server.get_base_url()))

    @classmethod
    def generic_teardown_class(cls):
        cls._server.stop()
        shutil.rmtree(cls._tmpdir)
        cls._server = None
        cls._tmpdir = None
        patches.EnvPatcher.unpatch()

    @staticmethod
    def make_test_spec_list(rinfo):
        return [
            PulseOxSpec(path='quick_example.md',
                        schedule=datetime.timedelta(seconds=300), **rinfo),
            PulseOxSpec(path='long_example.md',
                        schedule=datetime.timedelta(minutes=60), **rinfo)
            ]

    def do_client_update(self, path, rinfo):
        """Sub-classes should override with their client update.
        """
        raise NotImplementedError
    
        client = PulseOxClient(token=self._tokens[0])
        resp = client.post(path_to_file=path,
                           content='test update', **rinfo)
        assert resp.status_code in (200, 201)

    def check_basic_example(self):
        rinfo = {'owner': 'testowner', 'repo': 'testrepo'}
        spec_list = self.make_test_spec_list(rinfo)

        # Use python to setup spec list since CLI not good for that
        dashboard = PulseOxDashboard(
            token=self._tokens[0], spec_list=spec_list, **rinfo)
        dashboard.compute_summary()
        assert len(dashboard.summary.status['MISSING']) == 2
        dashboard.write_summary()
        
        self.do_client_update('quick_example.md', rinfo)
        text = self.do_dashboard_update(rinfo)

        change_pattern = (
            r'# Changes\s+'
            r'- \[quick_example\.md\]\(quick_example\.md\)'
            r' MISSING --> OK \d{4}-\d{2}-\d{2} \d{2}:\d{2} EST\s+')
        main_pattern = (
            r'# MISSING\s+'
            r'- \[long_example\.md\]\(long_example\.md\)'
            r' error: \(status_code=404\) NOT FOUND None\s+'
            r'# OK\s+'
            r'- \[quick_example\.md\]\(quick_example\.md\)'
            r' \d{4}-\d{2}-\d{2} \d{2}:\d{2} EST')

        mtch = re.search(change_pattern + main_pattern,
                         text, re.MULTILINE)
        assert mtch

        # Recompute to verify that change section is now omitted
        text = self.do_dashboard_update(rinfo)
        mtch = re.search('^' + main_pattern, text, re.MULTILINE)
        assert mtch

    def check_lookup(self):
        """Now run a test where we lookup spec_list from GitHub.
        """

        rinfo = {'owner': 'testowner', 'repo': 'testrepo'}
        text = self.do_dashboard_update(rinfo)
        assert 'OK\n\n- [quick_example.md](quick_example.md)' in text
        assert ('# MISSING\n\n- [long_example.md](long_example.md)'
                ' error: (status_code=404) NOT FOUND') in text


class TestGitHubWithPyClient(GenericGitHubTester):
    """Do tests on mock GitHub with python client.
    """

    @classmethod
    def setup_class(cls):
        cls.generic_setup_class()

    @classmethod
    def teardown_class(cls):
        cls.generic_teardown_class()
        
    def do_client_update(self, path, rinfo):
        client = PulseOxClient(token=self._tokens[0])
        resp = client.post(path_to_file=path,
                           content='test update', **rinfo)
        assert resp.status_code in (200, 201)

    def do_dashboard_update(self, rinfo):
        dashboard = PulseOxDashboard(token=self._tokens[0], **rinfo)
        dashboard.get_remote_data()
        dashboard.compute_summary()
        return dashboard.summary.text

    def test_basic_example(self):
        return self.check_basic_example()

    def test_lookup(self):
        return self.check_lookup()


class TestGitHubWithCLI(GenericGitHubTester):
    """Do tests on mock GitHub with cli.
    """

    @classmethod
    def setup_class(cls):
        cls.generic_setup_class()

    @classmethod
    def teardown_class(cls):
        cls.generic_teardown_class()
        
    def do_client_update(self, path, rinfo):
        runner = CliRunner()
        cmd_line = ['client', 'post', '--report', 'GOOD',
                    '--token', self._tokens[0], '--path', path,
                    '--content', 'test_update']
        for name, value in rinfo.items():
            cmd_line.append(f'--{name}')
            cmd_line.append(value)
        result = runner.invoke(po_cli, cmd_line)
        assert result.exit_code == 0
        assert result.stdout.strip() == 'OK'

    def do_dashboard_update(self, rinfo):
        runner = CliRunner()
        cmd_line = ['check', 'rdashboard', '--token', self._tokens[0]]
        for name, value in rinfo.items():
            cmd_line.append(f'--{name}')
            cmd_line.append(value)
        result = runner.invoke(po_cli, cmd_line)
        assert result.exit_code == 0
        return result.stdout
        
    def test_basic_example(self):
        return self.check_basic_example()

    def test_lookup(self):
        return self.check_lookup()
    
