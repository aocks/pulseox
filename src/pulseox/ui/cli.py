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
@click.option('--path', type=click.Path(), required=True, multiple=True)
@click.option('--hc-path', required=True, type=str, help=(
    'Relative path on GitHub to health check file.'))
@click.option('--note', default=None, type=str, help=(
    'Optional note to include with status update.'))
@click.option('--content', default='# File Check\n{bad_list}\n{good_list}\n',
              help=('Optional content template for status report.'))
@common_options()
def exists(path, hc_path, note, content, owner, repo, token):
    """Check if files exists (OK) or not (ERROR).

You can provide the --path option multiple times to check multiple
paths for existence. We will report an OK condition only if all
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
        status = 'ERROR'
        bad_list = '\n## Bad Paths\n' + '\n  - '.join([''] + bad) + '\n'
    else:
        bad_list = ''
        note = 'all paths good'
        status = 'OK'
    good_list = '## Good Paths\n' + '\n  - '.join([''] + good) if good else ''

    content = content.format(bad=bad, good=good,
                             bad_list=bad_list, good_list=good_list)

    if token:
        PulseOxClient(token=token).post(
            owner=owner, repo=repo, path_to_file=hc_path,
            content=content, status=status, note=note)
    else:
        click.echo('No token provided so no status report submitted.')
        click.echo(f'Note: {note}')
        click.echo(f'Content:\n{content}')


if __name__ == '__main__':
    cli()
