# User guide

Version 0.1.0 contains the building blocks; the unreleased version adds
the scan of a folder into the database. Analysis of files follows in later
versions. This guide grows with every release.

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

## Use case: register a folder in the database

The scan only reads files; it never moves, renames or changes them. It
runs as the normal user who can read the folder; no `sudo`.

1. Run `filetag scan /path/to/archive`.
2. On large folders a line `... 200 files`, `... 400 files` appears on the
   error channel every 200 files.
3. At the end two lines appear, for example:

   ~~~text
   scan done: 1234 files, 1230 new contents, 1234 new paths, 0 changed, 0 unchanged, 0 missing, 0 errors
   database: /home/USER/.local/share/filetag/filetag.db
   ~~~

   * *new contents*: files whose content was not known yet. Two hardlinks
     or copies of one file count as one content and two paths.
   * *changed*: known paths whose size, inode or modification time changed;
     they were read again.
   * *unchanged*: known paths that were not read again.
   * *missing*: known paths below the folder that no longer exist. They
     stay in the database with the time they went missing.
4. Exit code 0: all files read. Exit code 1: some files or folders could
   not be read (each one is named in a line `filetag: cannot read ...`)
   or the scan was interrupted with Ctrl+C. Exit code 2: the folder does
   not exist, or the database is from a newer filetag version.

Notes:

* Interrupting with Ctrl+C is safe. The work done so far is kept, and the
  next scan reads only what is still missing.
* After an interrupted scan, or when a folder could not be read, missing
  paths are not looked for; the summary then says `missing not checked`.
  This prevents files in an unreadable folder from being reported as gone.
* Symbolic links are not followed. Folders named `geloescht` are skipped,
  because filetag moves obsolete items there.

## Use case: scan only some file types

1. Only videos of two types:
   `filetag scan /path/to/archive --ext mp4 --ext mkv`
2. All files except two types:
   `filetag scan /path/to/archive --exclude-ext part --exclude-ext tmp`
3. Extensions are given with or without dot, in any case.

## Use case: keep the database somewhere else

1. For one command: `filetag scan /path/to/archive --db /path/to/test.db`.
2. For all commands: `export FILETAG_HOME=/path/to/folder`; the database is
   then `/path/to/folder/filetag.db`.

## Use case: see what the database holds

1. Run `filetag status`.
2. Example output:

   ~~~text
   database: /home/USER/.local/share/filetag/filetag.db (schema 1)
   files:    audio 3, document 12, image 410, other 7, video 802
   paths:    1240 present, 2 missing
   last run: 4 scan done 2026-11-18T09:12:03+00:00 2026-11-18T09:14:40+00:00
   ~~~

3. *last run* shows id, kind, state (`running`, `done`, `aborted`), start
   and end in UTC.
