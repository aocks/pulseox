"""Command line interface for pulseox
"""

import click
import datetime
import json
import os
import socket

from pulseox import __version__, specs
from pulseox.client import PulseOxClient
from pulseox.dashboard import PulseOxDashboard


def common_options(required=False):
    def decorator(f):
        f = click.option('--owner', type=str, required=required,
                         help='Repository owner')(f)
        f = click.option('--repo', type=str, required=True,
                         help='Repository name')(f)
        f = click.option('--token', type=str, required=required, help=(
            'GitHub personal access token to access repo'))(f)
        return f
    return decorator


def client_options(required=False):
    def decorator(f):
        f = common_options(required)(f)
        return f
    return decorator


@click.group()
def cli():
    """PulseOx Command Line Interface (CLI).
    """

@cli.command()
def version():
    "Report current version."
    click.echo(__version__)
    return __version__


@cli.group()
def check():
    """Commands to check various things.
    """


@cli.group()
def client():
    """Commands to check various things.
    """

@client.command()
@click.option('--path', type=str, required=True, help=(
    'Path to file in repository to update with post.'))
@click.option('--content', type=str, required=True, help=(
    'Content to include in post.'))
@click.option('--report', type=click.Choice(specs.JOB_REPORT),
              help=('Job report status.'))
@click.option('--note', type=str, default='', help=('Optional note.'))
@client_options()
def post(path, content, report, note, owner, repo, token):
    po_client = PulseOxClient(token=token)
    result = po_client.post(owner=owner, repo=repo, path_to_file=path,
                            content=content, report=report, note=note)
    result = specs.format_response_error(result)
    if result:
        raise ValueError(result)
    click.echo('OK')
    

@check.command()
@click.option('--path', type=click.Path(), required=True, multiple=True)
@click.option('--hc-path', required=True, type=str, help=(
    'Relative path on GitHub to health check file.'))
@click.option('--note', default=None, type=str, help=(
    'Optional note to include with status update.'))
@click.option('--content', default='# File Check\n{bad_list}\n{good_list}\n',
              help=('Optional content template for status report.'))
@common_options()
def exists(path, hc_path, note, content, owner, repo, token):
    """Check if files exists (GOOD) or not (BAD).

You can provide the --path option multiple times to check multiple
paths for existence. We will report a GOOD condition only if all
paths provided exist.
    """
    good, bad = [], []
    for name in path:
        if os.path.exists(name):
            good.append(name)
        else:
            bad.append(name)

    if any(bad):
        note = f'{len(bad)} bad paths'
        status = 'BAD'
        bad_list = '\n## Bad Paths\n' + '\n  - '.join([''] + bad) + '\n'
    else:
        bad_list = ''
        note = 'all paths good'
        status = 'GOOD'
    good_list = '## Good Paths\n' + '\n  - '.join([''] + good) if good else ''

    content = content.format(bad=bad, good=good,
                             bad_list=bad_list, good_list=good_list)

    if token:
        PulseOxClient(token=token).post(
            owner=owner, repo=repo, path_to_file=hc_path,
            content=content, report=status, note=note)
    else:
        click.echo('No token provided so no status report submitted.')
        click.echo(f'Note: {note}')
        click.echo(f'Content:\n{content}')


@check.command()
@click.option('--dpath', default='summary.md', help=(
    'Path to dashboard file.'))
@click.option('--refresh/--no-refresh', default=True, help=(
    'Whether to refresh status of specs in the dashboard.'))
@click.option('--write/--no-write', default=True, help=(
    'Whether to write the dashboard to the remote.'))
@click.option('--extra-text', default=None, type=str, help=(
    'Optional extra text to append to summary if --refresh.'))
@click.option('--notify', default=None, help=(
    'JSON string for notify dictionary (e.g., `{"telegram": {'
    '"token": YOUR_TOKEN, "chat_id": YOUR_CID}})`'))
@common_options()
def rdashboard(dpath, refresh, write, extra_text,
               notify, owner, repo, token):
    """Update remote dashboard.

This command does the following:

    1. Connects to the summary in the remote repo.
    2. Downloads the JSON representation of the dashboard specification.
    3. Optionally updates the status of items in the specification.
       - Update happens if --refresh is passed in (which is the default).
    4. Writes the dashboard to the remote repo at given --dpath.
       - Write happens if --write is passed in (which is the default).
    5. Notify user of changes (depending on --notify parameter).
    6. Prints the summary to stdout.
    """
    if notify:
        try:
            notify = json.loads(notify)
        except Exception as problem:
            raise click.BadParameter(f'Unable to parse --notify: {problem}')
    
        
    dbrd = PulseOxDashboard(owner=owner, repo=repo, token=token,
                            notify=notify)
    dbrd.get_remote_data()
    if refresh:
        click.echo('Refreshing summary information.')
        dbrd.compute_summary(extra_text=extra_text)
        error_info = dbrd.format_response_error()
        if error_info:
            raise ValueError(error_info)
    if write:
        if not refresh:
            raise click.BadParameter(
                'Refusing to --write since no --refresh')
        click.echo('Writing summary information to repo.')
        dbrd.write_summary(force_refresh=False, path_to_summary=dpath)
        error_info = dbrd.format_response_error()
        if error_info:
            raise ValueError(error_info)        
    click.echo(dbrd.summary.text)


if __name__ == '__main__':
    cli()
