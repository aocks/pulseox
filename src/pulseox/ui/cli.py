"""Command line interface for pulseox
"""

import os
import click

from pulseox.tools import PulseOxClient


def common_options(required=False):
    def decorator(f):
        f = click.option('--owner', type=str, required=required,
                         help='Repository owner')(f)
        f = click.option('--repo', type=str, required=required,
                         help='Repository name')(f)
        f = click.option('--token', type=str, required=required, help=(
            'GitHub personal access token to access repo'))(f)
        return f
    return decorator


@click.group()
def cli():
    """PulseOx Command Line Interface (CLI).
    """


@cli.group()
def check():
    """Commands to check various things.
    """


@check.command()
@click.option('--path', type=click.Path(), required=True)
@click.option('--hc-path', required=True, type=str, help=(
    'Relative path on GitHub to health check file.'))
@click.option('--note', default=None, type=str, help=(
    'Optional note to include with status update.'))
@click.option('--content', default=None, type=str, help=(
    'Optional content to include in status report.'))
@common_options()
def exists(path, hc_path, note, content, owner, repo, token):
    """Check if file exists (OK) or not (ERROR).
    """
    if os.path.exists(path):
        note = note or 'file exists'
        content = content or f'File {path=} exists.'
        status = 'OK'
    else:
        note = note or 'file does not exist'
        content = content or f'File {path=} does not exist.'
        status = 'ERROR'

    if token:
        PulseOxClient(token=token).post(
            owner=owner, repo=repo, path_to_file=hc_path,
            content=content, status=status, note=note)
    else:
        click.echo('No token provided so no status report submitted.'
                   f'\n{note=}\n{content=}')


if __name__ == '__main__':
    cli()
