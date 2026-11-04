# slite-io — Specification

**Status:** Draft 0.1 · 2026-11-03
**Owner:** Paul Spitzner
**Purpose:** Mirror Markdown/MDX documentation from a Git repository into Slite,
with the Slite copy treated as a read-only, clearly labelled publication target.

---

## 1. Summary

`slite-io` is a Python/Typer CLI that takes local `.md`/`.mdx` files and
creates or updates corresponding notes in Slite. The first milestone is a
file-upload CLI. Later milestones mirror a Docusaurus documentation tree and run
automatically from a Forgejo (or GitHub) Action on pull requests.

Slite has no public API for per-note read-only permissions. “Read-only” is
therefore a documented convention enforced by a generated warning header and by
the sync process overwriting manual edits. The tool must not claim to enforce
Slite permissions it cannot set.

## 2. Goals

1. Upload a single Markdown/MDX file to a target Slite note.
2. Upload many files idempotently: update an existing note, never create
   accidental duplicates during normal reruns.
3. Prefix every mirrored note with a prominent read-only header containing:
   - the source path,
   - a link to the Git source and an edit link,
   - the last upload/sync timestamp,
   - the source revision and last source change (when Git metadata is available).
4. Mirror a Docusaurus `docs/` tree into a Slite folder tree.
5. Run from CI with one committed config file and one secret.
6. Be safe: preview by default, no destructive defaults, clear exit codes.

## 3. Non-goals

- Two-way sync or editing Slite notes back into Git.
- Enforcing Slite permissions or locking notes. The API does not expose this.
- Rendering a Docusaurus site, evaluating MDX/JSX, or executing JavaScript.
- dbt YAML parsing.
- Deleting Slite content by default.
- Translating content. Source language is preserved.

## 4. Reference implementation and code style

The implementation follows the conventions of
[`coasti-org/superset_io`](https://github.com/coasti-org/superset_io):

- **Class-based design.** Model the API, document parsing, selection, planning,
  and execution as classes. Avoid one-shot module-level functions; small helpers
  are acceptable only for a narrow, local concern.
- **Thin Typer layer.** The CLI wires typed options to classes. It does not
  contain business logic.
- **Heavy Typer usage.** Use a root callback, a typed `typer.Context` subclass
  with `obj`, `typer.Option`/`typer.Argument` with `Annotated`, `envvar`,
  `hide_input`, `exists`, `readable`, `resolve_path`, `typer.Exit`, and
  `typer.confirm` where a human decision is genuinely required.
- **`--version` is a global eager option**, not a `version` subcommand. It prints
  the distribution version and exits.
- **HTTP with `requests`.** Implement a `requests.Session` subclass for base URL
  and auth, mirroring `SupersetApiSession`. Do not introduce `httpx`.
- **YAML with `ruamel.yaml`.** Frontmatter parsing must use `ruamel.yaml`, not
  PyYAML or `python-frontmatter`.
- **Environment loading with `python-dotenv`.** `load_dotenv()` at CLI import.
- **Logging and output.** Use `logging.getLogger("slite_io")` with a module-level
  logger and a Rich-based handler. Provide a `catch_exception` decorator in
  `cli/utils.py` to log concise errors and exit with a code instead of a stack
  trace. All command output and diagnostics go through the logger, except the
  summary table, which is printed directly with a Rich `Console` to preserve
  alignment and styling, and `--version`, which uses plain `typer.echo`.
- **Verbosity.** `-v`, `-vv`, and `-vvv` increase detail: source paths, then
  level/time/tracebacks, then third-party modules with logger names.
- **Dependencies stay close to the reference:** `requests`, `typer`,
  `ruamel.yaml`, `python-dotenv`, `prompt-toolkit`. Avoid adding a dependency for
  something the standard library or these packages already cover. Do not add
  `httpx`, `python-frontmatter`, or `pathspec`: use `requests`, `ruamel.yaml`, and
  a small `FileSelector` built on `pathlib`/`glob`.
- **Layout under `src/`.** Use `src/slite_io/`, `tests/unit/`, and
  `tests/integration/`. Mirror the reference package’s split between
  `cli/`, `api/`, and domain modules.
- **Testing.** Unit tests mock `requests.Session`; integration tests are opt-in
  and never run by default.
- **Distribution assumption:** distribution `slite-io`, import package
  `slite_io`, console script `slite-io`.

### 4.1 Proposed module layout

```text
src/slite_io/
  __init__.py
  cli/
    __init__.py          # Typer app, callback, context, global options
    utils.py             # catch_exception, API-key resolution
    upload.py            # upload-single / upload-batch commands
    validate.py          # validate command
    doctor.py            # doctor command
  api/
    __init__.py          # SliteApiClient aggregate
    session.py           # SliteApiSession(requests.Session)
    notes.py             # NotesApiClient
  documents.py           # SourceDocument, FrontmatterParser, TitleResolver
  header.py              # ReadOnlyHeader
  selection.py           # FileSelector
  upload.py              # UploadPlanner, UploadExecutor, results
  models.py              # dataclasses for notes, actions, summaries
  utils.py               # get_version, shared narrow helpers
tests/
  unit/
  integration/
```

Packaging mirrors the reference: Hatchling build backend, `src/` layout, a
`slite-io` console script, and dependency groups for `lint` (`ruff`), `test`
(`pytest`, `pytest-cov`), `typed` (`mypy`, `types-requests`), and `dev`.

### 4.2 Key classes

| Class | Responsibility |
|---|---|
| `SliteApiSession` | `requests.Session` subclass: base URL, `x-slite-api-key`, retries, error mapping |
| `SliteApiClient` | Aggregate root: exposes `.notes`, `.session`; connection/identity check |
| `NotesApiClient` | Create, update, children, search, resolve root-channel/title paths, find child; logs root category |
| `SourceDocument` | Parsed file: path, repo path, title, body, metadata, warnings, draft flag |
| `FrontmatterParser` | ruamel-based frontmatter/document split |
| `TitleResolver` | Title precedence, H1 extraction, duplicate-H1 stripping |
| `ReadOnlyHeader` | Render the generated header and edit URL |
| `FileSelector` | Expand paths, apply include globs, subtract exclude globs, deterministic order |
| `UploadPlanner` | Resolve target, derive titles, detect duplicates, choose create/update/skip/fail |
| `UploadExecutor` | Apply planned actions, collect results, handle partial failure |
| `UploadResult`, `UploadSummary` | Result aggregation and exit-code inputs |

Future phases extend these classes rather than adding parallel function-based
paths.

## 5. Phases

### Phase 0 — Upload CLI (first implementation)

- Two upload subcommands:
  - `upload-single`: one source file to one explicit target note path.
  - `upload-batch`: scans the current working directory, selects files with
    include/exclude globs, and places them flat under one explicit target folder.
- Target folder/parent must already exist. Phase 0 never creates folders.
- Frontmatter parsing, title resolution, simple read-only header.
- MDX is passed through unchanged (frontmatter removed); no sanitisation yet.
- Preview by default; `--apply` writes.
- Find existing child by title; skip by default, update with `--overwrite`,
  otherwise create.
- Logged result output, API error handling.
- Unit tests with mocked `requests.Session`; no writes in tests.

### Phase 1 — Directory mirror

- Accept directories and globs.
- Map directories to Slite folder notes.
- Handle `index.md`/`intro.md` and folder metadata.
- MDX sanitisation and Docusaurus-specific conversions.
- Rewrite relative links and images.
- Optional pruning of removed docs (archive first, never delete by default).
- Ordering via `listPosition`.

### Phase 2 — Forgejo Action

- Composite action in this repository.
- Config committed in the documentation repository.
- Secret supplied as `SLITE_API_KEY`.
- PR summary comment; fails the check on upload errors.
- No writes from untrusted forks; runner decides.
- Optional manifest for stable note identity.

### Phase 3 — Operational polish

- `doctor`/`validate` commands for CI.
- Retry/backoff metrics, rate-limit handling.
- Migration from title matching to a manifest, if needed.

## 6. CLI interface

Resolved: subcommands, title-path targets only, flat batch upload, preview by
default, skip existing unless `--overwrite`.

The root Typer app uses a callback for shared options and a typed
`SliteContext(typer.Context)` whose `obj` is a `SliteApiClient`. The callback
must not authenticate for `--help`, `--version`, or offline commands; credentials
are resolved lazily when a command needs the API.

```text
slite-io [GLOBAL OPTIONS] COMMAND [ARGS]...

Global options:
  --api-key TEXT     Slite API key (hidden input; env SLITE_API_KEY)
  --base-url TEXT    API base URL (env SLITE_API_URL)
  -v, --verbose      Increase verbosity (-v, -vv, -vvv)
  --version          Print version and exit
  --help             Show help and exit

slite-io upload-single SOURCE_FILE --target-note "Channel/Folder/Note Title" [OPTIONS]
slite-io upload-batch --target-folder "Channel/Folder" [OPTIONS]
slite-io validate [OPTIONS]
slite-io doctor [OPTIONS]
```

`--version` is implemented as a Typer eager option or `version_option`, never as
a subcommand.

Targets are always resolved from a **root channel**, and the root channel is the
first target-path segment. There is no separate space flag: the API has no
“space” concept, and both the personal channel and organization channels are
depth-0 root notes.

- Target: `"My private channel/Level 1/Level 2/Authentication"`.

Resolution matches root-channel titles first. If more than one root note has the
same title, the command fails rather than guessing. The resolved root is
classified as `personal` when its id starts with `user-`, otherwise `company`;
that classification is logged at debug level only.

### 6.1 `upload-single`

Uploads exactly one Markdown/MDX file to an explicit target note.

```text
slite-io upload-single docs/api/auth.mdx \
  --target-note "My private channel/Level 1/Level 2/Authentication" \
  --header-edit-url "https://github.com/org/docs/edit/main/{filename}"
# preview by default; add --apply to write

slite-io upload-single scratch.md \
  --target-note "My private channel/Level 1/Level 2/Authentication"
```

- `--target-note` is a `/`-separated title path. The first segment is a root
  channel, the final segment is the Slite note title, and everything between is
  the folder path.
- The root channel may be an organization channel or the personal channel. No
  separate space flag is needed.
- The parent folder path must already exist.
- If any parent segment is missing, the command fails; Phase 0 does not create
  folders. The note itself may be created if it does not exist.
- If the note exists, it is skipped by default or updated with `--overwrite`.
- Title precedence from source content does not apply here; the target path
  provides the title. `--title` is not needed for this command.

### 6.2 `upload-batch`

Uploads many files flat under one existing target folder.

```text
slite-io upload-batch \
  --target-folder "My private channel/Level 1/Level 2" \
  --include-files "docs/**/*.md" --include-files "docs/**/*.mdx" \
  --exclude-files "docs/**/_*.md" \
  --header-edit-url "https://github.com/org/docs/edit/main/{filename}"
# preview by default; add --apply to write

slite-io upload-batch \
  --target-folder "My private channel/Level 1/Level 2" \
  --include-files "scratch/**/*.md"
```

- `--target-folder` must already exist. Phase 0 does not create it.
- `--target-folder` is an absolute root-channel path. The first segment is a root
  channel, which may be an organization channel or the personal channel.
- `upload-batch` expands include/exclude globs against the current working
  directory.
- Every selected file becomes a note directly under the target folder. Source
  directories do not become Slite folder notes in Phase 0.
- Note titles come from `title > sidebar_label > H1 > filename` (§8.3).
- Include/exclude precedence: union all include globs, then subtract every
  exclude glob. Both options are repeatable. Excludes always win. If no include
  globs are given, default to `**/*.md` and `**/*.mdx`.
- If two files resolve to the same title under the target, both are reported as
  ambiguous and failed; the rest of the batch continues.
- Deterministic processing order: absolute path, lexicographic.

### 6.3 Shared upload options (`upload-single` and `upload-batch`)

This table contains only options that affect which notes are written and how the
command behaves. The generated header has its own group in §6.4; nothing in that
group changes file selection, target resolution, or note content outside the
header.

| Option | Meaning |
|---|---|
| `--upload-format [markdown\|sliteml]` | Slite API content field. Default `markdown`. `sliteml` sends the same body through the `sliteml` field without conversion yet. |
| `--apply` | Perform writes. Without it, the command previews only. |
| `--overwrite / --no-overwrite` | Update existing notes. Default `--no-overwrite`: skip and continue. |

`--upload-format sliteml` does not translate Markdown into SliteML. It only
selects the `sliteml` field on create/update. A real Markdown-to-SliteML renderer
is future work.

Include/exclude globs always match against paths relative to the **current
working directory**. There is no source-root option.

`--api-key` and `--base-url` are global callback options, not per-command
options.

Semantics:

- **Preview is the default.** Without `--apply`, the command resolves targets,
  checks existing notes, and prints exactly what would happen, but sends no write
  requests. This is also the PR-check mode.
- **`--apply` writes.** CI must pass it explicitly.
- **Existing notes are skipped by default.** With title match and
  `--no-overwrite`, the file is skipped and the batch continues. `--overwrite`
  updates the note in place.
- No interactive confirmation prompts.
- Batch error handling: a failing file is reported and the batch continues. A
  batch with any failures exits `3`.
- Exit codes: `0` success (including skipped files), `1` runtime/API failure,
  `2` usage/config error, `3` partial success (some files failed).

### 6.4 Read-only header options

These options affect **only** the generated read-only blockquote prepended to
the created/updated Slite note. They do not clone, fetch, checkout, select files,
change the target, or alter the source body. If `--no-header` is used,
`--header-edit-url` is ignored.

| Option | Meaning |
|---|---|
| `--header / --no-header` | Prepend the generated read-only blockquote to the Slite note. Default on. |
| `--header-edit-url TEMPLATE` | Edit URL template. Supported placeholders: `{filename}` (with extension) and `{file_basename}` (without extension). |

`--header` (not an HTTP header) means this block at the top of the Slite note
body:

```markdown
> [!WARNING]
> **🔒 Read-only mirror — do not edit this note in Slite.**
> This note is generated from the Git repository. Manual changes are overwritten
> by the next sync.
>
> [Edit this file in Git](https://github.com/org/docs/edit/main/auth.mdx)
> · Last synced: 2026-11-03 14:05 UTC
```

Worked example:

```text
local file:          docs/api/auth.mdx
--header-edit-url:   https://github.com/org/docs/edit/main/{filename}
edit URL:            https://github.com/org/docs/edit/main/auth.mdx
```

- `{filename}` expands to the source filename with its extension, for example
  `auth.mdx`.
- `{file_basename}` expands to the filename without its extension, for example
  `auth`.
- If the template is omitted, the header shows the cwd-relative source path
  without a link.
- Unknown placeholders are an error. Only the two placeholders above are
  supported in Phase 0.
- Repository URL and branch detection are future work; for now the caller
  provides the full edit URL template.
- The template is expanded separately for each file in a batch.

### 6.5 `validate`

Parse files selected by `--include-files`/`--exclude-files` against the current
working directory, resolve titles, check body size, and report problems without
contacting Slite. Intended for CI pre-checks and fast local feedback. In Phase 0
this does not sanitise MDX.

### 6.6 `doctor`

Check API key validity, identity (`GET /me`), and target resolution. Target paths
are absolute root-channel paths, the same as the upload commands. Read-only.

### 6.7 Input precedence (Phase 0)

Phase 0 is CLI-only; there is no config file.

API key resolution, highest to lowest:

1. `--api-key`
2. `SLITE_API_KEY`
3. `SLITE_API_KEY_FILE` (path to a file containing the key)
4. error

API URL:

1. `SLITE_API_URL`
2. built-in `https://api.slite.com/v1`

All other settings come from CLI flags and built-in defaults. A `.slite-io.toml`
is deferred to the CI/action phase.

## 7. Configuration (deferred)

Phase 0 does not read a config file. The following TOML shape is the working
proposal for the action phase and is included so the CLI flags do not drift from
the eventual file format:

```toml
# .slite-io.toml — future, not read by Phase 0
[slite]
base_url = "https://api.slite.com/v1"
target_folder = "My private channel/Level 1/Level 2"
api_key_env = "SLITE_API_KEY"

[source]
root = "docs"
include = ["**/*.md", "**/*.mdx"]
exclude = ["**/_category_.json", "**/draft-*.md"]
title = ["frontmatter.title", "frontmatter.sidebar_label", "h1", "filename"]
skip_drafts = true
mdx = "pass-through"

[mirror]
mode = "flat"
overwrite = false
create_parents = false
strip_duplicate_h1 = true

[header]
enabled = true
edit_url = "https://github.com/org/docs/edit/main/{filename}"
```

Environment:

- `SLITE_API_KEY` — API key; never logged.
- `SLITE_API_KEY_FILE` — path to a file containing the API key.
- `SLITE_API_URL` — optional override, primarily for tests.
- CI variables such as `GITHUB_SHA`, `GITHUB_REF_NAME`, `FORGEJO_*` may provide
  revision metadata later.

## 8. Source model

### 8.1 File discovery

- `upload-single` takes exactly one source file.
- `upload-batch` and `validate` expand include/exclude globs against the current
  working directory.
- Include and exclude filters are repeatable file-path globs. Includes are
  expanded into a set of absolute files; excludes are expanded independently
  into another set; the exclude set is subtracted from the include set.
  Excludes always win.
- Default includes: `**/*.md`, `**/*.mdx`.
- Ignore `.git`, `node_modules`, and `.venv` in expansion results.
- Deterministic order: lexicographic by absolute path.

### 8.2 Frontmatter

`FrontmatterParser` uses `ruamel.yaml` to split and parse the leading `---`
block. Do not use PyYAML or `python-frontmatter`. Relevant fields:

- `title`
- `sidebar_label`
- `sidebar_position`
- `slug`
- `draft`
- `unlisted`
- `description`

Unknown fields are preserved for reference but not uploaded.

### 8.3 Title resolution

Default precedence for `upload-batch`:

1. `frontmatter.title`
2. `frontmatter.sidebar_label`
3. first level-1 Markdown heading
4. filename without extension, with `-`/`_` normalised to spaces

`upload-single` takes the note title from the final segment of `--target-note`
instead; content-derived titles are not used there.

If the body starts with an H1 equal to the resolved title, remove that H1 from
the body to avoid a duplicate title inside the Slite note. If the H1 differs,
keep it and warn.

### 8.4 Drafts

`draft: true` files are skipped by default, with a warning. `unlisted: true` is
uploaded unless configured otherwise.

### 8.5 MDX handling

Phase 0 passes MDX through unchanged, except for YAML frontmatter, which is
parsed and removed from the body. MDX is never executed. Imports, JSX, Docusaurus
components, and expressions are sent as-is; Slite may render them poorly.

Future work (not Phase 0) will add progressively:

- strip `import`/`export` statements and JSX comments,
- convert Docusaurus admonitions (`:::note`, `:::tip`, etc.),
- handle `<Tabs>`/`<TabItem>`, `<Admonition>`, `<details>`, `<kbd>`,
- warn on unknown components instead of silently dropping content,
- a strict mode that rejects unsupported constructs.

A full MDX parser is not required now. Any future transform must be conservative
and fixture-tested.

### 8.6 Links and images

Phase 0 keeps image and resource links exactly as they appear in the source.
Relative links and images will likely be broken in Slite; this is accepted for
now.

Backlog:

- investigate whether Slite supports uploading images/assets and how the API
  expects them to be referenced,
- rewrite relative images to Git raw URLs or uploaded Slite assets,
- rewrite internal document links to Slite note URLs after a two-pass upload,
- add warnings for known-broken relative links.

The only links the tool itself generates are the header’s source/edit links,
which are absolute.

## 9. Slite model and mapping

### 9.1 Target resolution

- Every target path is absolute from a **root channel**. The first segment is a
  root-channel title, not an implicit space.
- `GET /search-notes?query=&depth=0` returns all root notes: the personal
  channel plus organization channels. Notes directly under a root have depth 1.
- The root segment is matched by normalized title. If zero roots match, fail; if
  more than one matches, fail as ambiguous.
- The resolved root is classified for diagnostics only:
  - id starts with `user-` → `personal`
  - otherwise → `company`
- Log this classification at debug level when the root channel is resolved:
  `log.debug("Root channel %r (id=%s) classified as %s", title, id, category)`.
  This is a heuristic, not an API contract. It must never change whether a note
  is written.
- Every remaining path segment is matched against the child notes of the
  previous segment.
- Phase 0 requires every target folder segment to exist:
  - `upload-single`: the parent path (all but the final title segment) must
    exist; the note itself may be created.
  - `upload-batch`: the entire `--target-folder` path must exist.
- Missing targets raise a clear error. Phase 0 does not create folder notes;
  `create_parents` is reserved for Phase 1.
- There is deliberately no `--target-id` in Phase 0. The path is the single
  configuration surface, so a renamed Slite folder is a visible configuration
  error rather than a stale opaque ID.

### 9.2 Directory mapping (Phase 1)

`tree` mode:

```text
docs/
  intro.md                    -> target / "Introduction"
  api/
    index.md                  -> target / "API" (folder note content)
    auth.md                   -> target / "API" / "Authentication"
```

- A directory becomes a child note (folder note) under its parent.
- By default the folder note receives a generated index of its children plus any
  directory metadata.
- `index.md`/`intro.md` content is used as the folder note body when present;
  otherwise a generated index is used.
- `flat` mode places every document directly under the target, preserving only
  titles.

### 9.3 Note identity and updates

- Primary lookup: title among the target parent’s children.
- Paginate `GET /notes/{parentId}/children` fully before deciding create/update.
- Normalise titles for comparison (trim; optional case-insensitive match) but
  keep the configured display title.
- Duplicate titles under the same parent are ambiguous: fail that file with a
  clear error and continue the batch. Never guess which note to overwrite.
- The update endpoint accepts `title` and `markdown`, not `parentNoteId`.
  **A note cannot be moved through the public API.** A moved source file therefore
  cannot be followed by an update; the old note must be archived/deleted and a new
  note created. This is a documented limitation.
- Optional manifest (Phase 2): `.slite-io.lock.json` maps source path to
  note ID and parent ID, enabling reliable rename/move detection. It must be
  committed only by a trusted job, never written on a read-only PR check.

### 9.4 Pruning

- Default: `on_missing = "archive"` for notes known to be managed by the tool.
- Never delete by default. If `delete` is enabled, require an explicit config
  value and log every deletion.
- A note is “managed” if it matches a manifest entry or carries the generated
  marker/header. Without a manifest, do not prune, because title matching alone
  cannot distinguish mirrored notes from human-created notes.
- Archive endpoint: note archived state; delete endpoint is irreversible and
  cascades to children.

### 9.5 Ordering

- `listPosition` is writable on create/update.
- Phase 1 can map `sidebar_position` to descending `listPosition` values.
- If ordering is not configured, do not fight manual ordering; create at a stable
  position and leave it.

## 10. Read-only header

Every mirrored note begins with a simple header before the document body. The
CLI options that control this header are in §6.4; they affect nothing else.

```markdown
> [!WARNING]
> **🔒 Read-only mirror — do not edit this note in Slite.**
> This note is generated from the Git repository. Manual changes are overwritten
> by the next sync.
>
> [Edit this file in Git](https://git.example.com/org/docs/_edit/main/docs/foo.mdx)
> · Last synced: 2026-11-03 14:05 UTC
```

Rules:

- The header is generated; it is not part of the source Markdown.
- `Last synced` is the current upload time in UTC, generated at write time.
- The edit link is built from `--header-edit-url`; the fallback header shows the
  cwd-relative source path.
- If `--header-edit-url` is omitted, show the source path without a link.
- The header uses GitHub warning syntax (`> [!WARNING]`). Manual testing showed
  that Slite renders it as a styled alert. The remaining lines stay as a plain
  blockquote fallback.
- Phase 0 does not include source revision or last-source-change metadata.

Future work:

- Replace the Markdown blockquote with a SliteML `<callout type="note">` so the
  notice uses Slite’s native hint styling.
- Use a SliteML external link (`<a url="...">`) for **Edit now**, or a
  `<note-link>`/tile if a richer card/button-like element is wanted. There is no
  documented inline button block.
- Add source revision and last-source-change metadata once the basic mirror is
  stable.
- Consider a SliteML `<table-of-contents/>` block for long mirrored docs, after
  the write path is verified.
- A machine-readable marker may be added later for pruning/identity. Slite may
  strip HTML comments; identity must not depend on it.

The tool cannot make the Slite note truly read-only. This limitation must appear
in the README and in the spec, and the header wording must not overpromise.

## 11. Slite API client

Verified against the public API documentation and read-only calls:

- Base URL: `https://api.slite.com/v1`
- Auth: `x-slite-api-key: <key>` (the guide uses this header; the OpenAPI schema
  also advertises bearer auth)
- `GET /me` — identity check
- `POST /notes` — create note (`title`, `parentNoteId`, and one of `markdown`,
  `html`, or `sliteml`)
- `PUT /notes/{noteId}` — update title/content; same content-field choice; no
  parent change
- `GET /notes/{noteId}/children` — cursor pagination, 50 per page
- `GET /notes` — list notes; supports `parentNoteId`, ordering, pagination
- `GET /search-notes` — query, `parentNoteId`, depth, review state, pagination
- `GET /notes/{noteId}?format=md|html|sliteml` — read content
- `PUT /notes/{noteId}/tiles/{tileId}` — update/create a tile; requires an
  existing tile id copied from the editor
- `PATCH /notes/{noteId}/archived` or equivalent archive endpoint
- `DELETE /notes/{noteId}` — irreversible, cascades; not used by default
- No endpoint for note permissions, sharing, or “protect editing”.

### 11.1 Feature support matrix

Status values:

- **Yes (documented)** — exposed by the public API and/or SliteML reference.
- **Observed** — present in SliteML read-back from existing notes, but not in the
  documented SliteML reference; write path must be verified before relying on it.
- **No** — no public API endpoint or documented write path.
- **Partial** — possible only through a workaround or with prerequisites.

| Concern | API status | Mechanism | Notes |
|---|---|---|---|
| Per-note read-only / lock | **No** | — | Slite’s editor supports “protect editing” for writers, but the public API exposes no lock or permission endpoint. An API key can be read-only, but that applies to the whole key, not one note. |
| Doc permissions / sharing | **No** | — | Reader/writer/no-access and subdoc inheritance are UI-only. Restricted service accounts can be granted access manually. |
| Table of contents | **Observed** | SliteML `<table-of-contents id="..."/>` | Found in SliteML read-back; not listed in the SliteML reference. UI equivalent: `/toc` or `/outline`. Needs a write test. |
| Hints / callouts | **Yes (documented)** | SliteML `<callout type="note\|tip\|warning\|caution">` | Markdown works inside. UI equivalent: `!!` or `/hint`. |
| References to other notes | **Yes (documented)** | SliteML `<note-link note-id="..." title="...">`; user mentions: `<mention user-id="..." name="...">` | Requires resolving the target note ID. Rich doc cards are the intended form; plain external links use `<a url="...">`. |
| Rendered buttons | **Partial** | `<a url="...">`, `<note-link>`, or a tile | No documented inline button block. A tile can carry a URL/status header, but creating one requires an existing tile id from the editor. |
| Mermaid charts | **Observed** | SliteML `<diagram id="...">…mermaid source…</diagram>` | Found in SliteML read-back; not listed in the SliteML reference. UI equivalent: `/mermaid`. Write path needs verification. |
| GitHub-style Markdown / GFM alerts | **Working (observed)** | `> [!WARNING]` in the Markdown body | Manual upload showed Slite renders GitHub warning syntax as a styled alert. This is now used for the generated read-only header. Other GFM extensions are not verified. MDX/JSX is not executed. |
| Advanced tables / databases | **Partial** | Markdown tables, or SliteML `<database>` | Plain Markdown tables are the safe subset. Typed columns, selects, dates, and note references require SliteML. |
| Image/asset upload | **No documented endpoint** | Remote image URLs | No public asset-upload route is documented. Relative image paths are not resolved by Slite; remote URLs are the safe path until tested. |

Read-only SliteML inspection on 2026-11-03 confirmed:
`<table-of-contents>`, `<callout>`, `<note-link>`, `<mention>`, `<diagram>`,
`<database>`, `<mark>`, and `<file>` blocks in existing notes. The SliteML
reference documents `<callout>`, `<note-link>`, `<mention>`, `<database>`,
`<mark>`, and related tags, but not `<table-of-contents>` or `<diagram>`.

Implementation shape:

- `SliteApiSession(requests.Session)` subclasses `requests.Session`, stores
  `base_url`, injects `x-slite-api-key`, prefixes relative URLs in `request()`,
  sets a timeout, and maps HTTP errors to typed `SliteError` subclasses.
- `NotesApiClient` owns note operations: `find_root_channel`, `list_children`,
  `resolve_folder`, `resolve_parent_and_title`, `find_child`,
  `create_note`, `update_note`.
- `SliteApiClient` is the aggregate root, analogous to `SupersetApiClient`:
  it exposes `.session` and `.notes` and provides `test_connection()`.
- `upload-single` and `upload-batch` receive the aggregate through
  `SliteContext.obj`; they never construct a session directly.

Client requirements:

- Timeout on every request (for example 30 s connect/read).
- Retry `429` and `5xx` with exponential backoff; respect `Retry-After`.
  Do not retry `4xx` validation/auth errors.
- Preflight body size against Slite’s 1 MB request limit; fail with the file path
  and measured size.
- Never log the API key. Redact it from exceptions.
- Preview mode (no `--apply`) performs reads needed for planning but zero writes.
- Unit tests mock `requests.Session` / responses; no network.

## 12. Forgejo/GitHub Action

Phase 2 design constraints:

- The docs repository commits `.slite-io.toml`.
- The action receives `SLITE_API_KEY` from repository/organization secrets.
- On pull requests, run `validate` always and `upload-batch` without `--apply` to
  report the plan. Actual writes happen on merge to the default branch, or are
  opt-in per branch.
- PRs from forks must not receive the secret; the workflow must not attempt writes
  there.
- The action writes a concise summary: files processed, created, updated,
  skipped, failed, target URL.
- No prune on PR checks; prune only on the trusted default-branch job.
- A support script or composite action step installs the CLI. Pin the version.

Example workflow sketch:

```yaml
name: sync-slite
on:
  push:
    branches: [main]
    paths: ["docs/**", ".slite-io.toml"]
  pull_request:
    paths: ["docs/**", ".slite-io.toml"]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.forgejo/actions/slite-io
        with:
          command: validate

  sync:
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: ./.forgejo/actions/slite-io
        with:
          command: upload
          api-key: ${{ secrets.SLITE_API_KEY }}
```

The final action interface is intentionally left for Phase 2.

## 13. Security

- Slite API keys are personal and grant access to all content of the user. Treat
  the key as a high-value secret.
- Never pass the key on the command line in CI logs. Prefer environment variables.
- Do not log request bodies in normal mode; note content may be confidential.
- Document that test fixtures must be synthetic or sanitised.
- Do not run write tests against production Slite. A dedicated target note and a
  dedicated API key are acceptable for manual smoke tests only.

## 14. Testing and verification

- Test layout mirrors the reference: `tests/unit/` for fast mocked tests,
  `tests/integration/` behind an opt-in `--integration` flag, and a shared
  `tests/conftest.py`. Group related assertions in `Test...` classes.
- Unit tests:
  - frontmatter and title resolution,
  - H1 stripping,
  - header rendering with and without Git metadata,
  - MDX sanitisation fixtures,
  - path/tree mapping,
  - target path resolution,
  - existing-note lookup and duplicate handling,
  - size preflight,
  - retry/backoff classification.
- Mocked `requests.Session` tests for create/update/preview.
- CLI smoke tests with a local stub HTTP server: assert exit code and output.
- Manual smoke: one dedicated Slite target and one small fixture file. Writes are
  explicit and never part of automated tests.
- No test may depend on network access or the production API key.

## 15. Open questions

| ID | Question | Status |
|---|---|---|
| Q1 | Command surface: subcommands vs one command | resolved: `upload`, `validate`, `doctor` |
| Q2 | Target addressing: path, note ID, or both | resolved: title path only |
| Q3 | Phase 0 input: files/directories | resolved: paths + `--include-files`/`--exclude-files`; tree mapping still Q8 |
| Q4 | Existing-note policy and prompts | resolved: skip by default; `--overwrite` updates |
| Q5 | Dry-run default vs apply flag | resolved: preview default; `--apply` writes |
| Q6 | MDX policy: passthrough, sanitise, or strict | resolved: pass through in Phase 0 |
| Q7 | Title precedence and duplicate-title behaviour | resolved: title > sidebar_label > H1 > filename; duplicate → fail file |
| Q8 | Directory mapping and `index.md` handling | resolved: flat in Phase 0; tree in Phase 1 |
| Q9 | Note identity: title matching vs committed manifest | resolved: title match in Phase 0 |
| Q10 | Prune policy for removed docs | resolved: none in Phase 0 |
| Q11 | Header wording and whether to add Slite “Verified” state | resolved: simple header, no Verified; native callout/buttons later |
| Q12 | Link/image rewriting policy | resolved: unchanged in Phase 0; image upload investigation in backlog |
| Q13 | Single-file target semantics: final path segment as title | resolved: yes |
| Q14 | Config file location/format for Phase 0 | resolved: CLI flags only; config deferred |
| Q15 | API key input: environment only vs optional flag | resolved: `--api-key` → `SLITE_API_KEY` → `SLITE_API_KEY_FILE` |
| Q16 | Upload subcommand names | resolved: `upload-single`, `upload-batch` |
| Q17 | Distribution/package/command names | resolved: `slite-io` / `slite_io` / `slite-io`; no coasti prefix |
| Q18 | Space selector for target paths | resolved: none; first path segment is the root channel, including `My private channel` |
| Q19 | Channel category detection | resolved: classify `user-` roots as personal, others as company, for `log.debug` only |

## 16. Backlog / TODOs

- Investigate Slite image/asset upload support and how to reference uploaded
  images from Markdown. Keep source image links unchanged until then.
- Investigate Slite-native admonition/callout blocks via SliteML and native
  linking buttons. Target an **Edit now** button that opens the repository’s
  in-browser editor.
- Add source revision and last-source-change metadata to the header.
- Directory-tree mirroring (`tree` mode), folder notes, and `index.md` handling.
- MDX sanitisation and Docusaurus component conversion.
- SliteML renderer for rich blocks: callouts/hints, note links, TOC, mermaid,
  typed tables, and button-like tiles.
- Rewrite internal document links to Slite note URLs after a two-pass upload.
- Manifest-based identity for renames/moves.
- Prune/archive removed documents, with explicit opt-in.
- `listPosition` ordering from `sidebar_position`.
- Forgejo/GitHub composite action and PR summary.
- Rate-limit/retry metrics and `doctor` diagnostics.
- README and public usage documentation.

## Appendix B — Verified API facts

Read-only checks performed on 2026-11-03:

- `GET /me` returns the authenticated user and organization.
- `GET /notes` returns the full note list with cursor pagination.
- `GET /search-notes?query=&depth=0` returns both the personal channel
  (`id` starts with `user-`, title `My private channel`) and organization root
  channels. Depth is the number of parents; notes directly under a channel have
  depth 1.
- `GET /search-notes?query=...` matches note content and returns `parentNotes`
  breadcrumbs; this can be used to resolve channel names and locate markers.
- The public documentation confirms:
  - 1 MB request-body limit,
  - `429` rate limiting,
  - create/update body fields,
  - children pagination,
  - no parent/move field on update,
  - no permission, sharing, or “protect editing” endpoint,
  - archive and irreversible delete endpoints.
- Slite’s help center confirms “protect editing” exists in the editor permission
  model for writers, but it is not exposed through the public API.
- Slite service accounts (Enterprise) can have read-only or read-write API keys;
  this scopes the key, not individual notes.
- Read-only SliteML inspection found `<table-of-contents>`, `<callout>`,
  `<note-link>`, `<mention>`, `<diagram>`, `<database>`, `<mark>`, and `<file>`
  blocks in existing notes. `<callout>`, `<note-link>`, `<mention>`,
  `<database>`, and `<mark>` are documented in the SliteML reference;
  `<table-of-contents>` and `<diagram>` are not.
- UI features: `/toc`, `/hint` (`!!`), `/mermaid`, `/doc`/`@` links.
