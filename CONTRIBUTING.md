# Contributing

## Branching model

History is strictly linear: **no merge commits**, neither `--no-ff` nor a
regular merge, neither locally nor on GitHub. Branches are integrated by
rebase and fast-forward only.

| Branch        | Purpose                                         | Created from | Integrated into |
|---------------|-------------------------------------------------|--------------|-----------------|
| `main`        | releases only; every release commit is tagged   | -            | -               |
| `develop`     | integration of finished features                | `main`       | `main` (fast-forward) |
| `feature/<x>` | one change, finishable in about 8 hours         | `develop`    | `develop` (rebase + fast-forward) |

Closing a feature branch (integrator, normal user):

~~~bash
git switch feature/NAME && git rebase develop && tools/check.sh
git push --force-with-lease origin feature/NAME     # CI runs on the rebased head
gh pr create --base develop --fill                  # pull request only for the CI run
gh pr checks --watch                                # wait for green
git switch develop && git merge --ff-only feature/NAME && git push origin develop
git branch -d feature/NAME && git push origin --delete feature/NAME
~~~

GitHub marks the pull request as merged when its commits arrive on
`develop` by the push. The merge buttons on GitHub are not used: "Rebase and
merge" always writes new commits, which would make `develop` and `main`
diverge.

A release fast-forwards `main` to `develop` and tags it:

~~~bash
git switch main && git merge --ff-only develop && git push origin main
git tag -a vX.Y.Z -m "filetag X.Y.Z" && git push origin vX.Y.Z
~~~

Rules:

1. Rebase feature branches regularly onto `develop`.
2. Every push of a branch runs the quality gates locally (pre-push hook);
   CI runs them for every pull request. Branch protection requires the CI
   checks on the pushed commit, a linear history, and forbids force pushes
   to `main` and `develop`.
3. One version covers all four packages: `__version__` in each
   `packages/*/src/filetag_*/__init__.py` must be equal (test
   `tests/test_versions.py`) and equal to the tag (CI job `release-check`).

## Quality gates

One script, used locally and in CI:

~~~bash
python3 -m venv .venv && . .venv/bin/activate   # normal user
pip install -r requirements-dev.txt             # all packages editable + tools
git config core.hooksPath .githooks             # once per clone: pre-push hook
tools/check.sh                                  # all gates
tools/check.sh --fast                           # without tests, while editing
~~~

| Gate     | Tool         | Pass criterion                                          |
|----------|--------------|---------------------------------------------------------|
| privacy  | privacy_scan | no locally listed term in files, paths, commit messages |
| format   | pycodestyle  | no finding, max line length 100                         |
| lint     | pylint       | 10.00/10 incl. Google-style docstring checks            |
| types    | mypy         | no error (`check_untyped_defs`)                         |
| security | bandit       | no finding                                              |
| tests    | pytest       | all pass, no resource leak, branch coverage >= 90 %     |

The privacy gate reads `~/.local/share/filetag/privacy/denylist.txt` (and
`allowlist.txt`); without a list it is skipped, so it is neutral in CI.

## Coding rules

1. One class per module; Google-style docstring on every module, class,
   method and function.
2. `filetag-protocol` and `filetag-core` use the standard library only.
   Heavy dependencies (speech recognition, embeddings) belong to the worker,
   as optional extras.
3. External programs are called with argument lists via `shutil.which`,
   never through a shell.
4. Collaborators are injected through the constructor; tests replace model
   backends by fakes. No test uses real archive material: test media are
   generated (`ffmpeg -f lavfi -i testsrc`).
5. Never delete user data: clean-up paths move files into a subfolder
   `geloescht` instead of removing them.
6. User guide (`docs/user-guide.md`) and developer guide
   (`docs/developer.md`, with UML) are updated with every change.
7. The repository never contains names of platforms, creators, folders,
   files or hosts of a real collection; such values live in local
   configuration below `~/.local/share/filetag/`.
