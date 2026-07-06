"""Dashboard for PulseOx.
"""

import logging as rawLogger
from datetime import datetime, UTC
import os
from typing import List, Optional, Annotated, Dict, Union, Tuple, Any

import notifiers
import requests
from pydantic import BaseModel, Field, SkipValidation, PrivateAttr


from pulseox.specs import (VALID_MODES, VALID_STATUSES, JOB_REPORT,
                           ValidationError, GitHubAPIError, PulseOxSpec,
                           make_dt_formatter, create_metadata,
                           format_response_error, DEFAULT_BASE_URL)
from pulseox.github import download_github_file
from pulseox.generic_backend import make_backend


LOGGER = rawLogger.getLogger(__name__)


class PulseOxSpecChange(BaseModel):

    current_item: PulseOxSpec
    current_status: str
    previous_item: Optional[PulseOxSpec] = None
    previous_status: Optional[str] = None


class PulseOxSummary(BaseModel):
    """Summary of dashboard status.
    """

    status: Annotated[Dict[str, Dict[str, PulseOxSpec]], Field(description=(
        'Dictionary where keys are status types from VALID_STATUSES'
        ' and each value is a PulseOxSpec with that status.'),
                                                          default={})]
    text: Annotated[str, Field(default='', description=(
        'Text summary contents for the dashboard'))]

    updated: Annotated[datetime, Field(description=(
        'UTC time when summary was updated.'), default_factory=lambda: (
            datetime.now(UTC)))]

    show_tz: Annotated[str, Field(default='US/Eastern', description=(
        'String name of timezone to display for datetimes'))]

    def format_text(self, change_dict, mode: str = 'md') -> str:
        """Format the summary and fill the `text` field of self..
        """
        unknown = set(VALID_STATUSES) - set(self.status)
        if unknown:
            raise ValueError(f'Unknown status fields: {unknown}')
        section_info = [(n, self.status.get(n, {})) for n in VALID_STATUSES]
        sections = [self._format_section(n, s.values(), mode)
                    for n, s in section_info if s]
        change_text = self.format_changes(change_dict, mode)
        if change_text:
            sections.insert(0, change_text)

        self.text = '\n\n'.join(sections)

    def format_changes(self, change_dict, mode='md', project_root='',
                       title='Changes'):
        if not change_dict:
            return None

        lines = []
        format_dt = make_dt_formatter(self.show_tz)
        for _stat, idict in change_dict.items():
            for path, change in idict.items():
                if change.current_status != change.previous_status:
                    lines.append(self._format_entry(
                        path, (f'{change.previous_status}'
                               f' --> {change.current_status}'),
                        format_dt(change.current_item.updated), mode,
                        project_root=project_root))

        if not lines:
            return None

        if mode == 'md':
            header = [f'# {title}', '']
        elif mode == 'org':
            header = [f'* {title}', '']
        else:
            raise ValueError(f'Invalid {mode=}')

        return "\n".join(header + lines)

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

        format_dt = make_dt_formatter(self.show_tz)
        for entry in entries:
            lines.append(self._format_entry(entry.path, entry.note,
                                            format_dt(entry.updated),
                                            mode))

        return "\n".join(lines)

    @classmethod
    def _format_entry(cls, path, note, updated, mode: str,
                      project_root='') -> str:
        """Format a single entry in the summary.

        Args:
            entry: Entry dictionary
            mode: Output format

        Returns:
            Formatted entry string
        """
        link = cls.format_link(path, project_root+path, mode)

        parts = [f"- {link}"]
        if note:
            parts.append(note)
        parts.append(updated)

        return " ".join(parts)

    @staticmethod
    def format_link(text, url, mode='md'):
        if mode == 'md':
            link = f"[{text}]({url})"
        elif mode == 'org':
            link = f"[[{url}][{text}]]"
        else:
            raise ValidationError(f"Invalid mode in format_link: {mode}")
        return link


class PulseOxDashboard(BaseModel):
    """Dashboard for monitoring files in repositories (GitHub or local git).

    Args:
        owner: Repository owner (None for local git repos)
        repo: Repository name (or file:// path for local git repos)
        token: GitHub personal access token for API authentication

    Raises:
        ValidationError: If parameters are invalid
    """

    owner: Optional[str]
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
    previous_summary: Optional[PulseOxSummary] = None
    changes: Annotated[Optional[
        Dict[str, Dict[str, PulseOxSpecChange]]], Field(
            default=None, description=(
                'Dictionary of changes computed by compute_summary_changes.'
                ))]

    # e.g., {'telegram': {'token': TELEGRAM_TOKEN, 'chat_id': CHAT_ID,
    #                     'parse_mode': 'markdown'}}
    notify: Annotated[Optional[Dict[str, Any]], Field(
        exclude=True, default=None, description=(
            'Dictionary where keys are providers and values are'
            ' dictionaries of keyword args for that notifier.'))]

    _base_url: str = PrivateAttr(default_factory=lambda: (
        os.environ.get('DEFAULT_PULSEOX_URL', DEFAULT_BASE_URL)))

    _latest_response: Annotated[
        Optional[SkipValidation[requests.Response]], Field(
            description=('Latest response object from interacting with'
                         ' GitHub. This is just a convenience to help'
                         ' verify or investigate response from the'
                         ' GitHub API.'), default=None, exclude=True)]

    def get_remote_data(self, github_file='summary.md.json', ref='main'):
        """Fill `spec_list` and `summary by downloading from GitHub.

        :param github_file='summary.md.json':  Path to GitHub file
                                               to download.

        :param ref='main':   Branch to reference in download.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  Returns `self` to help in chaning.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  This will read the `spec_list` and `summary`
                  properties from GitHub.  By default it reads the
                  JSON version of the dashboard written by
                  `write_summary`. This makes it easy to do something
                  like

          response = PulseOxDashboard(token=token,owner=owner,repo=repo
                     ).get_remote_data.write_summary()

        """
        content = download_github_file(self.token, self.owner,
                                       self.repo, github_file, ref,
                                       base_url=self._base_url)
        content = content.decode('utf8')
        parsed = self.__class__.model_validate_json(content)
        self.spec_list = parsed.spec_list
        self.summary = parsed.summary
        self.previous_summary = parsed.previous_summary
        return self

    def compute_summary(
        self,
        mode: str = 'md',
        extra_text: str = None,
        show_tz: str = 'US/Eastern') -> str:
        """Compute summary field with summary of all monitored files.

        Args:
            mode: Output format ('md' for markdown, 'org' for org-mode)

        Returns:
            A copy of self to help in chaining.

        Raises:
            ValidationError: If parameters are invalid
        """
        # For local git repos, owner can be None
        if self.owner is not None and (not self.owner or not self.owner.strip()):
            raise ValidationError("owner cannot be empty string")
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

        status = {n: {} for n in VALID_STATUSES}

        for spec in self.spec_list:
            spec.update(token=self.token, base_url=self._base_url)
            if spec.report == 'BAD':
                status['ERROR'][spec.path] = spec
            else:
                if spec.is_within_schedule():
                    if spec.report == 'GOOD':  # within schedule and GOOD
                        status['OK'][spec.path] = spec
                else:  # within schedule but not GOOD or ERROR
                    status['MISSING'][spec.path] = spec

        self.previous_summary = self.summary
        self.summary = PulseOxSummary(status=status)
        self.changes = self.compute_summary_changes(
            self.previous_summary, self.summary)
        self.summary.format_text(change_dict=self.changes)
        if extra_text:
            self.summary.text += extra_text
        self.summary.text += '\n\n' + create_metadata(
            '.' + mode, show_tz=show_tz)
        return self

    def maybe_notify_changes(self, title=None, project_root=''):
        title = title or f'Changes for {self.owner}/{self.repo}'
        if not self.notify:
            return
        change_text = self.summary.format_changes(
            self.changes, title=title, project_root=project_root)
        if not change_text:
            return
        for provider, kwargs in self.notify.items():
            my_notifier = notifiers.get_notifier(provider)
            my_notifier.notify(message=change_text, **kwargs)

    @staticmethod
    def compute_summary_changes(previous_summary: PulseOxSummary,
                                new_summary: PulseOxSummary
                                ) -> Dict[str, PulseOxSpecChange]:
        """Compute changes between a previous and new summary.

        :param previous_summary:  Previous PulseOxSummary.

        :param new_summary:       New PulseOxSummary.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  Dictionary of changes.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Compute the changes between summaries. This is a bit
                  **TRICKY** because an item might be reported 'OK' but
                  was late and so it was in the 'MISSING' section of
                  the previous summary because it was late. If that now
                  is reported 'OK' in the new summary it can be confusing
                  in both the case when the item is late or on time.
                  Basically the problem is that we are using 'OK' to
                  mean that the job reported OK and that it was on time.

        """
        previous_summary_status = (previous_summary.status
                                   if previous_summary else {})
        if not new_summary:
            raise ValueError('Must provide non-empty new_summary')

        prev_stat = {item.path: {'previous_status': p_stat,
                                 'previous_item': item}
                     for p_stat, idict in previous_summary_status.items()
                     for item in idict.values()}
        change_dict = {}
        for stat, idict in new_summary.status.items():
            sdict = {}
            change_dict[stat] = sdict
            for item in idict.values():
                prev_info = prev_stat.get(item.path, {})
                change = PulseOxSpecChange(current_item=item,
                                           current_status=stat, **prev_info)
                sdict[item.path] = change

        return change_dict

    def write_summary(self, path_to_summary: str = 'summary.md',
                      path_to_summary_json: Optional[str] = None,
                      force_refresh=False,
                      allow_notify_change=True):
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
        if force_refresh or not self.summary:
            self.compute_summary()
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

        backend = make_backend(
            self.owner, self.repo,
            token=self.token,
            base_url=self._base_url
        )
        backend.write_tree(files, 'Update summary files')
        self._latest_response = backend.get_latest_response()

        mode = path_to_summary.split('.')[-1]
        project_root = backend.get_project_root(path_to_summary)
        link = backend.format_summary_link(path_to_summary, mode=mode)

        if allow_notify_change:
            self.maybe_notify_changes(title=f'Changes for {link}',
                                      project_root=project_root)
        return self

    def format_response_error(self, response=None) -> Optional[str]:
        """Format an error response as text.

        :param response=None:  Optional response object (we use
                               self._latest_response if not provided).

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  None if there is no error indicated by response or
                  a string description of the error.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Format error information for the user.

        """
        response = response or getattr(self, '_latest_response', None)
        return format_response_error(response)
