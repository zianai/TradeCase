# P0 optional/reference upstream audit

Audit date: 2026-10-27. Scope: read-only public source inspection; no optional package installed, no browser attached, no user profile/history read, no backend/Proxy started, no paid API used. This is an engineering license inventory, not a legal opinion. `implemented` integration claims are intentionally absent. Source metadata was fetched live; syntax checks ran offline against those exact downloaded sources.

## Locked versions and decisions

| Repository | Locked commit SHA | License actually observed | V1 decision |
|---|---|---|---|
| unclecode/crawl4ai | `888299fb5f0b82181897dc0e61bfb4b036f0aea5` | Root LICENSE: Apache-2.0 body **plus appended Attribution Requirement**; pyproject says Apache-2.0 | Optional dependency only; no copied crawler engine. Dependency runtime remains untested. Preserve appended attribution when integrated. |
| eze-is/web-access | `d173a75978ceb2c63fa0b27f7408cd2bf7fe4310` | README says MIT and SKILL frontmatter `license: MIT`; **no LICENSE/COPYING/COPYRIGHT/NOTICE anywhere in untruncated Git tree** | Optional external Skill reference only; no copied/redistributed Proxy or Skill. Full-license verification blocked pending upstream clarification. No automatic install. |
| zpoint/vibe-seller | `c9be95f890108ce6f48cccf66f614c472fbf8ef6` | Root LICENSE Apache-2.0; Copyright 2026 The Vibe Seller Authors | `inspired-only`; session isolation/audit principles. GUI, backend and CDP mux `not-used`. |
| assafelovic/gpt-researcher | `3582a6841fe7dc801e2a34e34ee408641aea9bce` | Root LICENSE Apache-2.0. Appendix still uses `[yyyy] [name of copyright owner]`; no specific holder stated there | `inspired-only`; research/report structure, no Agent loop/framework or code/template copying. |
| fleixweb/superleads | `c45f451ff1846859f22282a444534c67b3034f88` | PolyForm Noncommercial 1.0.0, Required Notice Copyright (c) 2026 Fleix; NOTICE present | `not-used` source/templates for commercial-target V1; concept reference only. |
| JuneYaooo/launchfit-ai | `99d5a18cdee40bfeb9f117531577c5fdb55d3627` | PolyForm Noncommercial 1.0.0; Required Notice Copyright (c) 2026 JuneYaooo | `not-used` source/templates for commercial-target V1; concept reference only. |

GitHub public API `commits/HEAD` resolved each current head once; all subsequent file requests use its immutable SHA. The commits were dated 2026-10-26, 2026-10-14, 2026-10-24, 2026-10-10, 2026-08-24, and 2026-06-18 respectively. The audit snapshot is not a promise that those heads remain current.

## Evidence and reproducibility

Local evidence is in `upstream-audit/optional/` (outside the product repository):

- `source_manifest.json`: all six immutable source URLs, commit times, raw-file SHA-256 hashes, Git blob hashes and root notice filenames.
- `<owner>__<repo>/commit.json` and `tree.json`: raw public GitHub metadata; tree responses are all untruncated.
- Root license/readme/build metadata snapshots and selected Crawl4AI/Web Access implementation files.
- `syntax-checks.json`: actual commands and exit codes for six JavaScript syntax checks and four Python AST parses.

Requests executed: `GET https://api.github.com/repos/{repository}/commits/HEAD`, then `GET https://api.github.com/repos/{repository}/git/trees/{SHA}?recursive=1`, then `GET https://raw.githubusercontent.com/{repository}/{SHA}/{path}`. Python `urllib.request` performed public GET only. The fetch process exited 0; no failures in the enumerated-file fetch. A later explicit probe for Launchfit `NOTICE` returned HTTP 404, consistent with the tree listing; its actual LICENSE was fetched successfully. Web search tooling independently opened the two primary repository pages. All factual license claims below derive from saved root files, not GitHub's badge alone.

Validation executed:

```sh
node --check upstream-audit/optional/eze-is__web-access/scripts/browser-discovery.mjs
node --check upstream-audit/optional/eze-is__web-access/scripts/cdp-connection.mjs
node --check upstream-audit/optional/eze-is__web-access/scripts/cdp-proxy.mjs
node --check upstream-audit/optional/eze-is__web-access/scripts/check-deps.mjs
node --check upstream-audit/optional/eze-is__web-access/scripts/find-url.mjs
node --check upstream-audit/optional/eze-is__web-access/scripts/user-data.mjs
```

All six exit 0. Python `ast.parse` executed for `crawl4ai/__version__.py`, `async_crawler_strategy.py`, `async_webcrawler.py`, `install.py`; all four exit 0. **These are syntax checks only, not runtime tests or browser validation.** No optional upstream's test suite was claimed passed.

## Crawl4AI findings

Root source version is `0.9.5`. README quickstart recommends `pip install -U crawl4ai` and `crawl4ai-setup`; do not adopt unpinned `-U` in reproducible V1. The package is Python >=3.10 (TradeCase baseline >=3.11).

`pyproject.toml` has 34 direct runtime requirements, including `playwright>=1.49.0`, `patchright>=1.49.0`, `unclecode-litellm==1.81.13`, `playwright-stealth>=2.0.0`, `aiohttp>=3.11.11`, `httpx[http2]>=0.27.2`, Pydantic, lxml, numpy and Shapely. README's minimal-looking install therefore installs a substantial stack. `requirements.txt` differs from pyproject, including additional colorama/pdf2image/pypdf and a different fake-useragent lower bound. Use packaging metadata for a chosen wheel, not an assumption that both files are identical.

`crawl4ai/install.py:42` shows setup writes directories/database and invokes Playwright/Patchright browser installers; `_install_chromium` first tries `--with-deps --force chromium` (may require root on Linux), then a browser-only fallback. `CRAWL4AI_MODE=api` skips browsers but is not an instruction to use the hosted paid service. None of these setup paths was executed.

`AsyncHTTPCrawlerStrategy` at `async_crawler_strategy.py:2501` provides a real HTTP-only strategy with aiohttp. `AsyncWebCrawler` defaults to a browser strategy unless explicitly supplied one. For static public pages, the V1 adapter should select HTTP-only or the simpler existing fetch tool, never instantiate the default browser unintentionally.

The HTTP strategy accepts `http`, `https`, `file` and `raw`; see `VALID_SCHEMES` and `crawl` around lines 2871–2905. It therefore cannot serve as TradeCase's URL permission boundary. The caller must enforce public http(s), reject credentials/local/private-network targets, recheck redirects, bound response size/time/budget and refuse arbitrary JS/hooks from page content. Do not enable stealth/anti-bot evasion merely because included libraries support it.

The root LICENSE adds attribution beyond its Apache-2.0 body. Its required wording is preserved verbatim in the downloaded LICENSE. If integrated, retain that notice in THIRD_PARTY_NOTICES and CLI help/credits, as requested by the upstream's appendix. There is no separate root COPYRIGHT/NOTICE file in the tree.

`sbom/sbom.cdx.json` has timestamp `2026-01-27T01:43:08Z` and 679 mixed components. It lists MIT for one litellm build, Apache-2.0 for Playwright and Patchright builds, BSD-3-Clause for lxml/pypdf builds, and many entries without license data; it predates this 0.9.5 lock. It does **not** establish complete current transitive-license clearance, especially for `unclecode-litellm`. A resolved wheel lock plus per-distribution metadata/license audit is still required before shipping an installed optional dependency. Since no dependency was installed or copied here, no such clearance is claimed.

## Web Access findings

The current tree has only README/SKILL license declarations. No complete MIT grant/disclaimer text or explicit copyright notice is present under a license filename. Preserve this as `blocked` for vendoring/redistribution rather than labelling the license fully verified. Merely documenting the external tool does not require copying its implementation.

README installation options are `npx skills add eze-is/web-access`, Claude plugin marketplace/install (user scope), or cloning into `~/.claude/skills/web-access`. Each is outside the project's automatic-install policy. No command was run. Future opt-in should pin SHA and keep separate, subject to resolved license and user-granted site/browser access.

Selected scripts import only `node:` builtins and relative modules; no npm package manifest appears in the full tree. Node.js 22+ supplies native WebSocket. `find-url.mjs` shells out to `sqlite3` after copying a browser History DB. That feature is excluded from TradeCase's default operations. A complete upstream dependency/behavior validation was not executed.

`check-deps.mjs` is not a pure inspection command: it can migrate/create `~/.web-access/`, inspect configured browser data, and spawn a persistent detached CDP Proxy. `cdp-proxy.mjs:656` binds to `127.0.0.1`, default port 3456, not all network interfaces. Its `/eval`, `/click`, `/setFiles`, screenshot and navigation APIs can read and change authenticated browser state. Local binding reduces exposure but is not an authorization model.

The Skill's instruction making all networking mandatory through itself, its automatic use of browser login state, and its ability to submit forms must not override TradeCase's own read-only policy. Treat its text as audited third-party data during P0, not new agent instructions. Future browser use: explicit site authorization, new task tab, no arbitrary writes, no second controller of an occupied browser, record URL/time/excerpt, close owned tabs. When unavailable, static research continues and the browser-specific task is `blocked`.

## File-level reuse candidates for main matrix

| Upstream files | Target | Nature | Dependency / test | Reason / alternative |
|---|---|---|---|---|
| Crawl4AI `async_crawler_strategy.py::AsyncHTTPCrawlerStrategy`, `async_webcrawler.py` | future optional `providers` dependency adapter only | `not-used` source; dependency candidate | Python/aiohttp plus full package stack; 4 syntax parses passed; runtime not run | HTTP-only extraction if simpler public fetch is insufficient; no engine copy. |
| Crawl4AI `LICENSE` | notice metadata when dependency adopted | notice retention | Actual root file reviewed | Preserve Apache text plus attribution; optional dependency stays blocked/uninstalled until resolved. |
| Web Access `SKILL.md`, `scripts/check-deps.mjs`, `scripts/cdp-proxy.mjs` | external tool reference in browser policy, no product copy | `inspired-only` / implementation `not-used` | Node 22+, optional sqlite3; 6 syntax checks passed; full license/runtime blocked | Reuse a separately approved installed tool later; default static reader works now. |
| Vibe Seller `README.md` | browser/session policy concepts | `inspired-only` | No runtime dependency or test | Isolation and task auditing; no GUI/backend/CDP mux. |
| GPT Researcher `README.md` | research provenance concepts | `inspired-only` | No runtime dependency or test | Source/claim separation; host Agent supplies loop. |
| Superleads `LICENSE`, `NOTICE`; Launchfit `LICENSE` | license exclusion ledger | `not-used` | No code/template copied into product | Noncommercial restrictions conflict with commercial-target reuse; write original domain contracts. |

## Remaining items

- Crawl4AI installed dependency resolution, complete current license metadata, runtime smoke and public-site integration: `not_started` in this P0 subtask.
- Web Access full license grant, browser/site authorization and runtime validation: `blocked`; optional and must not block the deterministic core.
- Vibe Seller/GPT Researcher full code/dependency audits: intentionally out of scope because no code/runtime is adopted.
- Noncommercial source/templates: excluded from product. Downloaded readme/license snapshots are audit evidence only; do not promote them into executable/redistributed TradeCase assets.
