# Developer guide

## Packages and dependencies

~~~mermaid
flowchart LR
  core["filetag-core<br/>controller, CLI filetag"] --> protocol["filetag-protocol<br/>Job, Result"]
  worker["filetag-worker<br/>analysis, CLI filetag-worker"] --> protocol
  worker --> providers["filetag-providers<br/>profiles, adapters"]
  worker -. HTTP .-> server[("inference server<br/>Ollama / vLLM / cloud")]
  core -. SSH or localhost .-> worker
~~~

`filetag-core` never imports the worker: the two meet only through the
protocol (JSON). That keeps the controller free of heavy dependencies and
lets the worker run on another machine.

## Classes (UML)

~~~mermaid
classDiagram
  class Job {
    +str job_id
    +str kind
    +int size
    +str sha256
    +dict options
    +int protocol
    +to_json() str
    +from_json(text, supported) Job
  }
  class Result {
    +str job_id
    +str status
    +str model
    +str language
    +str title
    +str story
    +str story_de
    +list tags
    +str error
    +to_json() str
    +from_json(text, supported) Result
  }
  class Fields {
    +get(name, kind, required) Any
    +protocol(supported) int
  }
  class LanguageTagger {
    +normalise(code) str
    +title_tag(code) str
    +needs_german(code) bool
  }
  class FlatNamer {
    +int max_bytes
    +clean(title) str
    +build(title, tag, file_id, ext) str
  }
  class Cli {
    +Home home
    +run(argv) int
    +scan(args) int
    +status(args) int
  }
  class Profile {
    +str id
    +str kind
    +str api
    +str adult_content
    +date policy_checked
    +is_stale(today, max_age_days) bool
  }
  class ProfileRegistry {
    +builtin() ProfileRegistry
    +get(profile_id) Profile
    +stale(today) list
  }
  class Health {
    +report() dict
  }
  class WorkerCli {
    +run(argv) int
  }
  Job ..> Fields : parses with
  Cli --> Indexer
  Cli --> Home
  Result ..> Fields : parses with
  Cli --> LanguageTagger
  Cli --> FlatNamer
  ProfileRegistry o-- Profile
  WorkerCli --> Health
  WorkerCli --> ProfileRegistry
~~~

## Scan (UML)

~~~mermaid
classDiagram
  class Home {
    +Path root
    +database Path
    +ensure() Path
  }
  class Scanner {
    +set include
    +set exclude
    +frozenset skip_dirs
    +list errors
    +walk(root) Iterator~ScanEntry~
  }
  class ScanEntry {
    +str path
    +int device
    +int inode
    +int size
    +int mtime_ns
    +same_inode_state(other) bool
  }
  class Fingerprinter {
    +int chunk
    +digest(path, size) str
  }
  class KindClassifier {
    +classify(name) tuple
  }
  class Database {
    +start_run(kind, host, root, now) int
    +finish_run(run_id, status, now)
    +location(path) tuple
    +add_file(...) bool
    +put_location(entry, file_id, run_id, now)
    +seen(path, file_id, run_id, now)
    +mark_missing(root, run_id, now) int
    +status() dict
  }
  class Indexer {
    +scan(root) ScanSummary
  }
  class ScanSummary {
    +int seen
    +int new_files
    +int new_paths
    +int changed
    +int unchanged
    +int missing
    +bool missing_checked
    +bool aborted
    +line() str
  }
  Indexer --> Scanner
  Indexer --> Fingerprinter
  Indexer --> KindClassifier
  Indexer --> Database
  Indexer ..> ScanSummary : returns
  Scanner ..> ScanEntry : yields
  Database ..> ScanEntry : stores
~~~

Decision per path (`Indexer._register`):

~~~mermaid
flowchart TD
  A[path from Scanner] --> B{known and same device,<br/>inode, size, mtime?}
  B -- yes --> C[seen: update last_seen, no read]
  B -- no --> D[fingerprint: size + first and last 16 MiB]
  D -- read error --> E[record error; known path keeps its old state]
  D --> F[add_file: new content or last_seen]
  F --> G[put_location: path -> content]
~~~

After the walk, `mark_missing` sets `missing_since` on every location
below the root that this run did not see, but only when the walk was
complete (no Ctrl+C) and no folder was unreadable. Every 200 files the
transaction is committed, so an interrupted scan keeps its work.

The fingerprint reads at most 32 MiB per file. Two files of equal size
that differ only between the first and the last 16 MiB get the same id;
for media files this is unlikely (container headers and index data sit at
the ends), but it is a known limit.

## Database (schema version 1)

~~~mermaid
erDiagram
  runs ||--o{ locations : "last seen in"
  files ||--o{ locations : "lies at"
  files ||--o{ tags : has
  runs ||--o{ tags : "produced"
  runs {
    int id PK
    text kind
    text host
    text root
    text backend
    text model
    text prompt_version
    text started
    text finished
    text status
  }
  files {
    text id PK "fingerprint"
    int size
    text kind
    text mime
    text first_path
    text first_seen
    text last_seen
  }
  locations {
    text path PK
    text file_id FK
    int device
    int inode
    int size
    int mtime_ns
    text first_seen
    text last_seen
    int last_run FK
    text missing_since
  }
  tags {
    text file_id FK
    text tag
    text source "controlled or free"
    int run_id FK
  }
~~~

`fts` is an FTS5 table over `title`, `story`, `transcript` and `tags`,
keyed by `file_id`. The schema version is kept in `PRAGMA user_version`;
an older filetag refuses a newer database. Schema version 2 adds `analyses`
(one result per file, run and model: title, story, watermarks, statistics)
and `captions` (one row per analysed frame); version 1 is migrated in place.
Shots, transcripts and embeddings follow in later versions.

Times are ISO 8601 in UTC. Rows are never deleted by filetag.

## One job (sequence)

~~~mermaid
sequenceDiagram
  participant C as AnalysisRun (core)
  participant T as WorkerTransport
  participant J as JobRunner (worker)
  participant S as Workspace (RAM)
  participant A as Analyzer
  participant O as Ollama
  C->>T: run_job(job, path)
  T->>J: stdin: job line + file bytes (local or SSH)
  J->>S: enter: lock, clear leftovers, job folder
  J->>S: write and verify file (SHA-256)
  J->>A: run(job, file)
  loop every planned frame
    A->>A: cut frame with ffmpeg
    A->>O: image + instruction, thinking on every n-th frame
    O-->>A: description, watermarks
    A->>A: delete frame
  end
  A->>O: text only: segment summaries, then title, story, tags (JSON schema)
  O-->>A: text
  A-->>J: Result
  J->>S: exit: remove job folder
  J-->>T: stdout: Result JSON (stderr: progress without content)
  T-->>C: Result
  C->>C: store in one transaction, update search index
~~~

## Classes of the analysis (UML)

~~~mermaid
classDiagram
  class AnalysisRun { +videos(paths) +run(paths) int }
  class AnalysisRequest { +options() dict }
  class WorkerTransport { +command(action) +models() +run_job(job, path, progress) Result }
  class JobRunner { +run(source, output, log) int }
  class Workspace { +check_space(size) }
  class Analyzer { +run(job, video, folder) Result }
  class Settings { +times(duration) +wants_thinking(index) bool }
  class OllamaClient { +capabilities(model) +models() +generate(...) }
  class MediaTools { +duration(video) +frame(video, second, target) }
  AnalysisRun --> AnalysisRequest
  AnalysisRun --> WorkerTransport
  WorkerTransport ..> JobRunner : process
  JobRunner --> Workspace
  JobRunner --> Analyzer
  Analyzer --> Settings
  Analyzer --> OllamaClient
  Analyzer --> MediaTools
~~~

The job carries no file name. Instructions travel inside the job, so private
wording needs no place in the repository or on a command line. Long videos are
condensed in blocks of 30 captions before title and story are generated.

## Pipeline (video)

| Step | Method |
|---|---|
| Frames | 1 frame per second, scaled to 768 px width (ffmpeg) |
| Shot cuts | PySceneDetect, adaptive detector |
| Embeddings | SigLIP 2 for every frame; near-duplicates dropped |
| Clip captions | vision-language model, about 8 frames per call, within one shot |
| Transcript | faster-whisper with language detection |
| Story | language model: segment summaries, then the whole file |
| Title and tags | language model with JSON schema and a controlled vocabulary |

## Backend selection

1. `--cloud <provider>` given: that provider (frames and transcript text;
   whole video only with `--upload-video` and a provider that accepts it).
2. Otherwise the remote worker, if reachable (SSH and health check).
3. Not reachable: retry with growing intervals; after `fallback_after`
   (default 15 min) the local worker with a small model; back to the remote
   worker when it answers again.

## Worker without traces

* Files arrive over SSH in a RAM file system, mode 0700; names are
  pseudonymous job ids. The default is a private folder in `/dev/shm`;
  `FILETAG_WORK_ROOT` selects a tmpfs mounted with `noswap` once it exists.
* The work area is cleared after every job and at service start (the only
  deletion the tool performs: files it created itself in RAM).
* Only the result (JSON text) leaves the worker.

## Flat view

* `<title> [<code>-<Language>] [<id4>]<ext>` as hardlink to the original
  file on the same file system; English speech or none: no language tag.
* `<same name>.md`: generated companion text with story, chapters, tags,
  language, model, and the archive path, device, inode at analysis time.
* Extended attributes on the inode: `user.xdg.tags`, `user.xdg.comment`,
  `user.filetag.id`.
* Names that become obsolete (new title after re-analysis) are moved into
  the subfolder `geloescht` of the flat view, never removed.

## Workflow

Branching model, quality gates and coding rules: `CONTRIBUTING.md`.

Adding a provider: add `packages/providers/src/filetag_providers/profiles/<id>.json`
with the policy facts and the date they were read; `filetag-worker providers`
reports profiles whose facts are older than 90 days.
