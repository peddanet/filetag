# User guide

Version 0.1.0 contains the building blocks; analysis of files follows in
later versions. This guide grows with every release.

## Install

Follow "Installation" in `README.md`: one venv below `~/.local/share/filetag/`,
all packages from one release tag in one `pip` call.

## Use case: check a worker

1. On the machine that will analyse files, run `filetag-worker health`.
2. Read the JSON report: `ok` is `true` when ffmpeg and ffprobe were found;
   `programs` shows their paths, `null` for a missing program.
3. Exit code 0 means ready, 1 means a program is missing.

## Use case: see which model backends may be used

1. Run `filetag-worker providers`.
2. Each line shows the provider id, `local` or `cloud`, the verdict for
   adult content (`permitted`, `risk`, `not_permitted`) and the date the
   provider's policy was last read.
3. A line ending in `STALE: check policy again` means the facts are older
   than 90 days; the exit code is then 1.

## Use case: preview the flat-view name of a file

1. Run `filetag name "Street food tour in Lisbon" --lang pt --id a3f9e1 --ext .mp4`.
2. The output is the name the file will get in the flat view:
   `Street food tour in Lisbon [pt-Portuguese] [a3f9].mp4`.
3. Rules: English or no speech gives no language tag; German gives
   `[de-German]`; a code without a known name gives `[<code>]`.
