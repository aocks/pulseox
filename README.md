# Introduction

The `pulseox`{.verbatim} project provides python tools to create,
update, and monitor a system pulse and dashboard using GitHub.

# Usage

## Client

You can instantiate a `pulseox`{.verbatim} client and use it to update a
page in a GitHub project. The client will use the GitHub API and an
access token to post content as shown below:

``` python
from pulseox import tools

client = tools.PulseOxClient(token='my_token')
content = '''Some content

- data I want to keep track of
- for dashboard monitoring'''

result = client.post(owner, repo, path_to_file, content, status='OK',
                     optional_note='short text')
assert result.status_code == 200
```

The server will automatically include metadata at the bottom of the file
indicating the following:

-   status (as provided to the client)
-   updated (a UTC timestamp for when the last update occurred

This metadata will be automatically added at the end of the file and
will be preceded with the string \"# Metadata\" if the path to the file
ends in `.md`{.verbatim} or with \"\* Metadata\" if the path to the file
ends in `.org`{.verbatim}.

## Dashboard

You can then use a dashboard creation tool to collect together all the
posted content to get a summary using something like:

``` python
from pulseox import tools, specs

dashboard = tools.PulseOxDashboard(token='my_token')

example_spec = tools.PulseOxSpec(
    path_to_file,  # Path to file in GitHub repo
    schedule       # Either a datetime.timedelta or a cron string 
)

spec_list = ... # list of PulseOxSpec objects like above

summary = dashboard.make_summary(owner, repo, spec_list, mode='md')
result = dashboard.write_summary(  # Write input `summary` to GitHub
    owner, repo, summary, path_to_summary  # repo at `path_to_summary`
)
assert result.status_code == 200

```

The summary will have sections for the following status codes:

-   ERROR: This comes first and consists of all client posts with status
    of `ERROR`{.verbatim}.
-   MISSING: This comes second and consists of all PulseOxSpec instances
    where an update has not been provided within the given schedule.
-   OK: This comes last and consists of all PulseOxSpec instances which
    were posted with status OK within the required schedule.

The summary will be in markdown format if `mode`{.verbatim} was set to
`'md'`{.verbatim} and org-mode format if `mode`{.verbatim} was set to
`'org'`{.verbatim}. Empty sections will be omitted.

Within each section, there will be an entry like:

``` example
- <path_to_file> <note> <update_time>
```

with `<path_to_file>`{.verbatim} being both the (relative) path to the
posted file formatted as a link in either markdown or org format so if
the user clicks on it, they will be taken to the give file.

# Development Guidelines

The following are some development requirements.

-   Use click for any command line interface work.
-   Make sure to follow pep8 guidelines (especially keeping lines less
    than 79 characters).
-   Try not to repeat code; use functions.
-   It is good to keep lines less than 79 characters, but you do not
    need to go crazy. For example, not every function parameter needs to
    be on a separate line. Things are more readable if you keep
    functions to less than 40 lines. So put multiple parameters on the
    same line as long as that line is less than 79 characters.
-   Related to the above, try to break up long functions to have helper
    functions so that most functions are less than 40 lines unless there
    is a good reason to be longer.
