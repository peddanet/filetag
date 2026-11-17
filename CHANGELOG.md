# Changelog

All notable changes are documented here. Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/);
versions: [Semantic Versioning](https://semver.org/). One version covers all packages.

## [0.1.0] - 2026-11-17

### Added

- Monorepo with four packages: `filetag-protocol` (job and result format),
  `filetag-core` (controller), `filetag-worker` (analysis node),
  `filetag-providers` (model backends and their policy facts).
- Language rules for titles: English without tag, others `[<code>-<Name>]`,
  German additionally described in German.
- Flat-view file names `<title> [<tag>] [<id>]<ext>`, safe characters,
  at most 255 bytes.
- Provider profiles for Ollama, vLLM, Mistral, OpenAI, OpenRouter, Gemini,
  xAI and Anthropic with the date of the last policy check;
  `filetag-worker providers` marks facts older than 90 days.
- Worker health report (`filetag-worker health`).
- Quality gates (`tools/check.sh`), pre-push hook, GitHub Actions on Python
  3.12 and 3.14, release check for all package versions.

### Documentation

- User guide with step-by-step use cases, developer guide with UML
  (package, class and sequence diagrams), linear Git workflow (rebase and
  fast-forward only, no merge commits).
- Folder layout: all data below `~/.local/share/filetag`, launchers in
  `~/.local/bin`.
