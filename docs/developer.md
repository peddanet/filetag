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
    +run(argv) int
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
  Result ..> Fields : parses with
  Cli --> LanguageTagger
  Cli --> FlatNamer
  ProfileRegistry o-- Profile
  WorkerCli --> Health
  WorkerCli --> ProfileRegistry
~~~

## One job (sequence, target design)

~~~mermaid
sequenceDiagram
  participant C as Controller (core)
  participant W as Worker
  participant M as Model backend
  C->>W: health (SSH or localhost)
  W-->>C: versions, protocol, programs
  C->>W: Job JSON + file into RAM work area
  W->>W: frames, shots, audio, embeddings
  W->>M: captions, transcript, summaries
  M-->>W: text
  W->>W: clear work area
  W-->>C: Result JSON
  C->>C: store in database (one transaction)
  C->>C: project flat view, companion text, xattr
~~~

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

* Files arrive over SSH in a tmpfs mounted with `noswap`, mode 0700, owned
  by a service account; names are pseudonymous job ids.
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
