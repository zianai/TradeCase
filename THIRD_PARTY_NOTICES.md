# Third-party notices

This project derives from B2B Lead Hunter, https://github.com/xiongQvQ/-b2b-lead-hunter-skill, commit `ac27d0ec6627366337423bfcb1ba86c5be5a95a5`.

Copyright (c) 2026 xiongbojian. MIT license text is retained in root `LICENSE`. Inherited sources, assets, templates and references remain covered by this notice. Source-by-source decisions are recorded in `docs/SOURCE_REUSE_MATRIX.md`.

The V1 runtime uses Pydantic (MIT, including pydantic-core) and Python standard library. `requests` (Apache-2.0) belongs to inherited optional readers; transitive installed dependency metadata is recorded by the license check. Development tools pytest (MIT), Ruff (MIT), and setuptools (MIT) are development/build dependencies. No keys or paid databases are bundled.

AI Hunter and optional upstream notices will be appended following P0 inspection and any actual file selection. No code from Superleads or LaunchFit is permitted in the commercial execution path. Browser/crawler audit material is not equivalent to an installed or tested integration.

Optional projects currently not bundled: Crawl4AI `888299fb...` has Apache-2.0 plus an appended attribution requirement; Web Access `d173a759...` has only an MIT declaration and no complete LICENSE. Neither is installed or redistributed. See `docs/OPTIONAL_UPSTREAM_AUDIT.md` for exact SHAs and exclusions. Vibe Seller/GPT Researcher are conceptual references only. Superleads/LaunchFit PolyForm Noncommercial code and templates are excluded.

## AI Hunter file included in P2

`src/tradecase/vendor/ai_hunter/url_filter.py` is adapted from `backend/tools/url_filter.py` in https://github.com/xiongQvQ/AI_Find_Customer at `9b2fde8f719623c627516da2663707a893ee6805`. Copyright (c) 2026 AI Hunter. Full MIT grant/disclaimer is retained in `src/tradecase/vendor/ai_hunter/LICENSE`. Modifications validate scheme/host/ports and correctly scope LinkedIn matching. No other AI Hunter code, agents, services or PDF dependencies are bundled.

Installed core/dev distribution metadata and the bundled MIT notices are checked by `tools/check_licenses.py`; this does not claim clearance for uninstalled optional stacks. Dependency versions and download hashes are pinned in `uv.lock`.
