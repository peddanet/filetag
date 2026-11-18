# filetag

Describe and tag files with AI models, then publish the result in a flat
view: one hardlink per file, named by a descriptive title, next to a
generated Markdown companion text, with tags in extended attributes of the
inode. Video is the first supported media type; others follow as
analysis modules of the worker.

Status: 0.1.0 - skeleton. Protocol, language rules, flat-view names,
provider profiles and the worker health report work; analysis follows.
Unreleased: `filetag scan` registers all files of a folder with their
provenance in the database; `filetag status` summarises it.

## Architecture

~~~text
packages/
  protocol/   filetag-protocol   job and result format (JSON), versioned
  core/       filetag-core       controller: scan, queue, database, language
                                 rules, flat view, backend selection  (CLI: filetag)
  worker/     filetag-worker     media analysis: frames, shots, speech,
                                 embeddings; calls a model backend    (CLI: filetag-worker)
  providers/  filetag-providers  model backends (local servers, cloud APIs),
                                 profiles with policy facts, setup assistant
deploy/                          configuration for a GPU host (inference server,
                                 RAM work area, service unit)
~~~

| Mode | controller | worker | model |
|---|---|---|---|
| remote GPU host (normal case) | archive host | GPU host | inference server on GPU host |
| local fallback | archive host | archive host | small model on archive host |
| cloud (explicit command only) | archive host | archive host | cloud provider |
| standalone GPU host | GPU host | GPU host | inference server on GPU host |

Principles:

* The archive is never changed; the flat view and companion texts are
  projections of the database and can be regenerated at any time.
* A worker receives files under pseudonymous ids only, in a RAM file
  system, and keeps nothing after the job.
* No cloud service is used without `--cloud <provider>` on the command
  line; each provider profile states its data use and content policy.

More: `docs/developer.md`.

## Folders

Everything of an installation lives in two places of the user's home
directory, following the XDG convention for user data and executables:

~~~text
~/.local/share/filetag/        one folder for all data of the tool
  venv/                        installed release
  config.toml                  settings (planned)
  filetag.db                   database (filetag scan, filetag status)
  logs/                        run logs (planned)
  privacy/denylist.txt         terms that must never enter the repository
  privacy/allowlist.txt        phrases in which a listed term is permitted
~/.local/bin/filetag           link to venv/bin/filetag
~/.local/bin/filetag-worker    link to venv/bin/filetag-worker
~/Projects/filetag/            source checkout for development (own .venv)
~~~

`$FILETAG_HOME` replaces `~/.local/share/filetag` when set.

## Installation

Only from release tags, into a venv of the normal user. All needed
packages are given in **one** pip call, so their mutual dependencies are
resolved from the same tag and never looked up on PyPI:

~~~bash
TAG=v0.1.0
URL="git+https://github.com/peddanet/filetag@$TAG"
python3 -m venv ~/.local/share/filetag/venv
~/.local/share/filetag/venv/bin/pip install \
  "filetag-protocol @ $URL#subdirectory=packages/protocol" \
  "filetag-providers @ $URL#subdirectory=packages/providers" \
  "filetag-core @ $URL#subdirectory=packages/core" \
  "filetag-worker @ $URL#subdirectory=packages/worker"
~~~

Links into `~/.local/bin` (on the `PATH` of a login shell):

~~~bash
mkdir -p ~/.local/bin
ln -sfn ~/.local/share/filetag/venv/bin/filetag ~/.local/bin/filetag
ln -sfn ~/.local/share/filetag/venv/bin/filetag-worker ~/.local/bin/filetag-worker
~~~

A GPU host that only runs the worker can leave out `filetag-core` and the
first link.

## Documentation

* `docs/user-guide.md` - installation and use, step by step
* `docs/developer.md` - architecture with UML diagrams, development workflow
* `CONTRIBUTING.md` - branching model and quality gates

## Licence

MIT, see `LICENSE`.
