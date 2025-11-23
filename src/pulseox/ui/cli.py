"""Command line interface for pulseox
"""

import os

import click


@click.group
def cli():
    """PulseOx Command Line Interface (CLI).
    """


@cli.group()
def check():
    """Commands to check various things.
    """


@check.command()
@click.option('--path', type=click.Path(), required=True)
def file(path):
    """Check if file exists and/or was modified recently.
    """
    if os.path.exists(path):
        click.echo(f'{path=} does exists')#FIXME
    else:
        click.echo(f'{path=} does not exit')#FIXME
    

if __name__ == '__main__':
    cli()
