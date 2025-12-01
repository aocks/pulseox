# Introduction

The `pulseox` project provides python tools to create,
update, and monitor a system pulse and dashboard using GitHub.

You can have your clients update a project page on GitHub with current
status and have a unified dashboard which collects together the status
of all projects (including projects which should have reported but
have not).

PulseOx can use the `notifier` package to automatically notify you
when project status changes.

# Install

You can install as usual via something like
```
pip install pulseox
```
or
```
uv add pulseox
```
or if you want to develop in a fresh environment you can do something like
```
python3 -m venv .venv       # Create venv to get pip.
source .venv/bin/activate   # Activate venv.
pip install uv              # Install uv
uv venv --seed --clear      # Recreate venv since uv likes that
source .venv/bin/activate   # Source new venv
pip install uv              # Add uv to venv if you don't have global uv
uv sync                     # Sync dependencies.
```

# Usage

## Client

You can instantiate a `pulseox` client and use it to update a
page in a GitHub project. The client will use the GitHub API and an
access token to post content.

You can run the client either using the pulseox command line interface:
```
pulseox client post --owner owner --repo repo --report GOOD \
  --content "some exampe content"
```

or using python:

``` python
>>> from pulseox.client import PulseOxClient
>>> client = PulseOxClient(token=YOUR_GITHUB_PAT)
>>> content = ('Some content\n'
...            '- data I want to keep track of\n'
...            '- for dashboard monitoring\n')
>>> result = client.post(
...   owner, repo, 'example_project_page.md', content,  # required arguments
...   report='GOOD', note='')  #  these can be omitted and have defaults
>>> result.status_code in (200, 201)
True
>>> _ = client.post(owner, repo, 'alt_example.md', content, report='BAD',
...       note='We can report BAD runs as well')

```

The client will automatically include metadata at the bottom of the file
indicating the following:

- report: (as provided to the client)
- updated: (timestamp for when the last update occurred)
- note:  (note provided to client)


## Dashboard

You can then use a dashboard creation tool to collect together all the
posted content to get a summary using something like:

``` python
>>> import datetime
>>> from pulseox.specs import PulseOxSpec
>>> from pulseox.dashboard import PulseOxDashboard
>>> spec_list = [  # Example of job specifications we are tracking
...     PulseOxSpec(owner=owner, repo=repo, path='example_project_page.md',
...	      schedule=datetime.timedelta(minutes=10)),
...     PulseOxSpec(owner=owner, repo=repo, path='alt_example.md',
...	      schedule=datetime.timedelta(hours=10)),
...     PulseOxSpec(owner=owner, repo=repo, path='missing.md',
...       schedule='* * * * *')]  # can use cron string for schedule
>>> dashboard = PulseOxDashboard(
...     token=YOUR_GITHUB_PAT, owner=owner, repo=repo, spec_list=spec_list
... ).write_summary(force_refresh=True)  # Write summary to github
>>> print(dashboard.summary.text)  # Get text summary for local view
# Changes
- [alt_example.md](alt_example.md) None --> ERROR ...
- [missing.md](missing.md) None --> MISSING None
- [example_project_page.md](example_project_page.md) None --> OK ...
# ERROR
- [alt_example.md](alt_example.md) We can report BAD runs as well ...
# MISSING
- [missing.md](missing.md) error: (status_code=404) NOT FOUND None
# OK
- [example_project_page.md](example_project_page.md) ...

```

The specification list is also saved on GitHub. So after you have
written the summary at least once, you can read the summary remotely
using the pulseox command line interface:
```
pulseox check rdashboard \
  --token YOUR_GITHUB_PAT --owner owner --repo repo
```

or in python via:

``` python
>>> dashboard = PulseOxDashboard(
...     token=YOUR_GITHUB_PAT, owner=owner, repo=repo).get_remote_data(
... ).write_summary(force_refresh=True)
>>> print(dashboard.summary.text)  # Get text summary for local view
# ERROR
- [alt_example.md](alt_example.md) We can report BAD runs as well ...
# MISSING
- [missing.md](missing.md) error: (status_code=404) NOT FOUND None
# OK
- [example_project_page.md](example_project_page.md) ...

```

## Notification

You can use the [notifiers](https://github.com/liiight/notifiers)
package to send you notifications on status changes by providing a
dictionary of keyword arguments when creating your dashboard. For
example you could do something like:
```
dashboard = PulseOxDashboard(... notify={'telegram': {
    'token': YOUR_TELEGRAM_TOKEN, 'chat_id': YOUR_CHAT_ID}})
```
when creating your dashboard. See [docs for
notifiers](https://notifiers.readthedocs.io/en/latest/) for details on
available providers and keyword arguments accepted by each notifier.

## Summary Details

The summary will have sections for the following:

-   ERROR: This comes first and consists of all client posts with status
    of `BAD` or posts which were reported but had problems..
-   MISSING: This comes second and consists of all PulseOxSpec instances
    where an update has not been provided within the given schedule.
-   OK: This comes last and consists of all PulseOxSpec instances which
    were posted with status OK within the required schedule.

The summary will be in markdown format if `mode` was set to
`'md'` and org-mode format if `mode` was set to
`'org'`. Empty sections will be omitted.

Within each section, there will be an entry like:

``` example
- <path_to_file> <note> <update_time>
```

with `<path_to_file>` being both the (relative) path to the
posted file formatted as a link in either markdown or org format so if
the user clicks on it, they will be taken to the give file.
