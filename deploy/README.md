# Deployment of a GPU host

Planned content (phase 0/1): installation of the inference server, the RAM
work area (tmpfs with `noswap`), the worker service unit and the restricted
SSH access for the controller. Every file here is generic; host names and
addresses live in local configuration only.

Current minimum for a worker reached by SSH: `filetag-worker` in
`~/.local/bin`, Ollama with a vision model, `ffmpeg`, and key-based SSH access
from the controller. Without a dedicated tmpfs the worker uses a private
folder in `/dev/shm`; `/dev/shm` has no `noswap`, so memory pressure can move
pages to swap. Set `FILETAG_WORK_ROOT` when a `noswap` tmpfs is available.
