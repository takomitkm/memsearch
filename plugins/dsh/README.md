# @zilliz/memsearch-dsh

MemSearch plugin for [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH).
It gives DSH persistent, cross-agent memory on the same `.memsearch/memory/`
markdown store used by the Claude Code, Codex, OpenClaw, and OpenCode plugins,
backed by a Milvus hybrid search index.

```
capture  ── session/event turn/end ──> summarize (dsh-headless agent default, or custom-llm) ──> memory/YYYY-MM-DD.md
inject   ── agent/pre-step step 1  ──> memsearch search ──> returned chunks injected (zero cost otherwise)
recall   ── ctx.skills.register(memory-recall) ──> search → expand → transcript
review   ── web UI dock panel ──> GET/POST /memsearch-dsh/* ──> list candidates / queue review / install
```

## Prerequisites

- Install memsearch:

  ```bash
  uv tool install "memsearch[onnx]"
  ```

- A DSH profile (web / headless / tui) you want to attach memory to.
- Node >= 22.19 (DSH's requirement).

## Install

### From npm (recommended)

```bash
dsh plugin --profile web add @zilliz/memsearch-dsh
```

### From source (development)

```bash
dsh plugin --profile web add /path/to/memsearch/plugins/dsh
```

> `dsh plugin` is a pnpm forwarder: it links the package into the profile,
> detects the `dsh.bundle` declaration in `package.json`, and appends it to
> the profile's bundle layers. `cordis.patch.yml` inside the package then
> inserts the `memsearch` row into the profile's plugin tree.
>
> Replace `web` with your profile name (`headless`, `tui`, ...), and restart
> DSH for the profile (or start a new session) so the plugin mounts.

### Manual patch insertion (no `dsh plugin`)

Append this row to the profile's `cordis.patch.yml` and make sure
`@zilliz/memsearch-dsh` is resolvable from the profile's `node_modules` (for example a
`link:` dependency):

```yaml
- insert:
    - id: memsearch
      name: '@zilliz/memsearch-dsh'
```

### From this fork (Windows)

Upstream cannot launch the `dsh-headless` summarizer on Windows (see
*Windows: launching the headless summarizer* below). To use this fork's build in
a profile, clone the repository and add the plugin directory by path — the
package lives in `plugins/dsh`, so a `github:`/URL spec that installs the
repository root will not work:

```bash
git clone https://github.com/takomitkm/memsearch
dsh plugin --profile desktop add /path/to/memsearch/plugins/dsh
```

> Prefer the UI for this: a `dsh plugin …` run started from a terminal inherits
> pnpm's descriptors, so the plugin manager has no output stream to watch and
> therefore no silence timeout — if pnpm stalls, the run hangs indefinitely and
> leaves `.plugin-manager/run.json` behind, which then blocks every later
> profile operation. Runs started from the web UI are captured, and a captured
> run that prints nothing for `idleTimeoutMs` (default 600 000 ms) is terminated
> by DSH itself.

### Verify it loaded

Start DSH and check the session log for the plugin mount, or confirm the
`memory-recall` skill is available through the `skill` tool. Captured turns
land in `<project>/.memsearch/memory/YYYY-MM-DD.md`.

## Configuration

The plugin is configured through the profile's `cordis.patch.yml` `config`
block (patch the `memsearch` row you inserted). All keys are optional.

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `captureEnabled` | bool | `true` | Capture completed turns into memory. |
| `injectEnabled` | bool | `true` | Inject returned memory candidates before each turn's first step. |
| `summarizeEnabled` | bool | `true` | Summarize turns before writing (on failure a short unavailable note is written, never a raw dump). |
| `summarizeMode` | string | `auto` | Summarizer backend. `auto` (default) mirrors the other platform plugins: if `[plugins.dsh.summarize] provider` is set in memsearch config, it uses `custom-llm`; otherwise `dsh-headless` (zero-config DSH agent). Explicit `dsh-headless` / `custom-llm` pin the backend. |

Everything else — provider/model, Milvus, collection, memory dir — comes from
**memsearch config / environment**, exactly like the other platform plugins
(no per-plugin config fields):

- **Summarize provider/model** → `[plugins.dsh.summarize] provider` / `model`
  in `~/.memsearch/config.toml` (or `[llm.providers.*]`; see the
  `custom-llm` section below).
- **Milvus** → `[milvus] uri` in memsearch config.
- **Collection** → derived from the project path (`derive-collection.sh`),
  or `--collection` passed to the memsearch CLI.
- **Memory dir** → `MEMSEARCH_DIR` env (explicit → global scope), else
  `<project>/.memsearch`.

### Maintenance tasks (PROJECT.md / USER.md / skills)

Optional background upkeep, aligned with the other platform plugins. Each task
is disabled by default; enable the ones you want in `~/.memsearch/config.toml`:

```toml
[plugins.dsh.project_review]
enabled = true            # maintain .memsearch/PROJECT.md
[plugins.dsh.user_profile]
enabled = true            # maintain .memsearch/USER.md
[plugins.dsh.memory_to_skill]
enabled = true            # distill recurring workflows into skill candidates
min_occurrences = 3       # how often a workflow must recur before distilling
```

Common settings per task: `provider` (`native` = a one-shot DSH headless
agent, default), `model`, `min_interval_hours` (default 24), `input_dir`,
`output_file`. Candidates land in `.memsearch/skill-candidates/` (git-tracked)
and are **never installed automatically** — installing is a human step (see
the `memory-to-skill` skill in the other platform plugins).

Example override layer (add this to the profile's own `cordis.patch.yml`):

```yaml
- id: memsearch
  config:
    summarizeMode: dsh-headless   # pin the headless backend (default is auto)
```

### Summarization modes

Two backends are available, selected by `summarizeMode` — the same
"configured choice" the Claude Code / Codex / OpenClaw / OpenCode plugins
offer (each can summarize with their own LLM or a headless agent + small
model). The default (`auto`) matches theirs: configure a provider and you get
a direct LLM call; configure nothing and you get a headless agent.

- **`auto`** (default) — mirrors the other platform plugins:
  - if `[plugins.dsh.summarize] provider` is set in memsearch config
    (`~/.memsearch/config.toml`, same place the other plugins read), use
    `custom-llm` with that provider/model;
  - otherwise use `dsh-headless` (zero-config DSH agent).
  This means the plugin behaves like the other four: **configure a provider
  → direct LLM; configure nothing → headless**.
- **`dsh-headless`** — boots a one-shot DSH headless agent
  (`dsh --profile headless "<summarize task>"`) to write the notes, mirroring
  how the other plugins reuse their own agent's headless mode. Zero-config for
  anyone already using DSH: the sub-agent's model is the deployment's
  `agent-default-model` — the user layer of `~/.dsh/settings.yaml` (the same
  selection the Web UI model settings write) wins over any patch, so **the
  `[plugins.dsh.summarize]` provider/model do NOT apply here** — change the
  model in DSH settings (`agent-default-model:` in `~/.dsh/settings.yaml`, or
  the Web UI model picker) instead. The boot is asynchronous and fire-and-forget,
  so the few seconds of headless startup never block the conversation. Requires
  `dsh` on PATH or `DSH_CLI` set to the CLI
  entry — on Windows neither of those is reachable in a plain DSH Desktop
  install, see *Windows: launching the headless summarizer* below. The sub-agent
  is booted with `MEMSEARCH_DSH_SUMMARIZE=1`; the plugin
  checks that flag and stays inert (no capture / inject / skill) inside the
  summarizer, so the summarizer's own session is never re-captured in a loop.
- **`custom-llm`** — `scripts/summarize.py` imports memsearch's
  `[llm.providers.*]` config and calls the LLM directly. Lightweight: one
  python process, no DSH boot, no extra CLI dependency. Choose this when you
  want a specific small model (e.g. an official `deepseek-v4-flash` key in
  memsearch config) without booting an agent. Provider selection
  (most specific first):
  1. `[plugins.dsh.summarize] provider` (or the `summarizeProvider` CLI
     argument summarize.py receives from it) — looked up in
     `[llm.providers.<name>]`; a missing entry fails loudly (visible error),
     never a silent empty write.
  2. `llm.provider` when it names a configured provider or is a raw type.
  3. `compact.llm_provider` (deprecated) or `openai` as a final default.

There is **no automatic fallback between modes**: the backend you configure
(or auto resolves) is the backend used. If it fails (missing dsh CLI, bad
provider config), a short unavailable note is written with the reason — the
plugin never silently switches to an LLM you did not configure.

A failed summarization writes a short unavailable note (mirroring Claude
Code's behavior — memory stays clean, the transcript anchor keeps the raw
content reachable for progressive disclosure), and logs a visible warning
through the DSH logger.

### Windows: launching the headless summarizer

**Symptom.** Every captured turn writes a note like this instead of a summary,
and nothing ever lands in `.memsearch/memory/`:

```
Memory summary unavailable: spawn C:\Users\<you>\AppData\Local\Programs\DeepSeek ENOENT
```

The truncated path is the clue, but it is not the only way this fails — on a
Windows DSH Desktop install all three ways upstream looks for the CLI come up
empty, so the summarizer never starts at all.

**Why the three lookups fail.** DSH Desktop ships its CLI as a `cmd.exe` batch
launcher, `dsh.cmd`, which points at the Electron binary with
`ELECTRON_RUN_AS_NODE=1` and `--expose-internals …\dsh-desktop-host\lib\cli.js`:

1. **The PATH probe** runs `bash -c 'command -v dsh'`. Windows resolves
   executables through `PATHEXT`, and the MSYS bash builds tested here do not
   apply it to that lookup: `command -v dsh` fails, plain `dsh` reports
   "command not found", while `command -v dsh.cmd` succeeds. The DSH installer
   does add its launcher directories to the user `PATH`
   (`%USERPROFILE%\.dsh\bin`, plus `…\resources\runtime\cli\bin` under the app
   directory), so `dsh` works in `cmd.exe` and PowerShell but is invisible to
   this probe.
2. **`DSH_CLI`** was split on whitespace. DSH's own path contains a space
   (`Program Files\DeepSeek Harness`, or here `AppData\Local\Programs\DeepSeek
   Harness`), so the value became `['C:\Users\…\Programs\DeepSeek', 'Harness', …]`
   and `spawn` reported `ENOENT` on the first fragment — the error above.
   A path with no spaces does survive this branch.
3. **The pnpm global bin** is looked up as `$HOME/.local/share/pnpm/dsh`, a POSIX
   layout. Here `HOME` is set to the profile directory, so that resolves to
   `C:\Users\<you>\.local\share\pnpm\dsh`, which does not exist — pnpm's global
   bin on Windows is `%LOCALAPPDATA%\pnpm`, and DSH Desktop is not installed
   through pnpm at all, so nothing is in either place.

Even if the launcher path were found, `spawn`/`execFile` cannot start a `.cmd`
directly: since the CVE-2024-27980 fix Node rejects it with `EINVAL` unless a
shell is involved. And routing it through `cmd.exe /c` loses the transcript —
`cmd` treats an embedded newline as a command separator, so a multi-line prompt
arrives as its first line only (both measured, see *Verify* below).

**Resolution order after this patch.** The first three branches are upstream's,
unchanged; the Windows branch is a last resort that only runs when everything
before it failed, so POSIX behavior is untouched:

1. `dsh` resolvable through `bash` (as before).
2. `DSH_CLI` — now kept as **one** argv entry when the trimmed value is an
   existing file; split on whitespace only when it is an interpreter invocation.
3. `$HOME/.local/share/pnpm/dsh` (as before).
4. **New, `win32` only:** the first existing PowerShell shim among
   `<DSH_HOME|HOME|USERPROFILE>/bin/dsh.ps1` and
   `<…>/.dsh/bin/dsh.ps1`, launched as
   `pwsh.exe -NoProfile -File <shim> …`. `pwsh.exe` is a real executable under a
   space-free path from `%LOCALAPPDATA%\Microsoft\WindowsApps` (on the default
   user `PATH`), and `-File` binds each remaining argv entry to `$args` verbatim,
   so multi-line transcripts arrive intact.

**Set it up.** `DSH_HOME` is not set by DSH Desktop, so the shim is found
through `HOME`/`USERPROFILE` — put it where DSH already keeps its own launcher:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.dsh\bin" | Out-Null
```

Write `%USERPROFILE%\.dsh\bin\dsh.ps1` (adjust the two paths to your install;
they are absolute on purpose, so the shim works from any working directory):

```powershell
$ErrorActionPreference = 'Stop'
$exe = 'C:\Users\<you>\AppData\Local\Programs\DeepSeek Harness\DeepSeek Harness.exe'
$cli = 'C:\Users\<you>\AppData\Local\Programs\DeepSeek Harness\resources\app.asar\dsh\node_modules\@deepseek-ai\dsh-desktop-host\lib\cli.js'
$env:ELECTRON_RUN_AS_NODE = '1'
& $exe --expose-internals $cli @args
exit $LASTEXITCODE
```

The shim is found by `pwsh.exe`, which is PowerShell 7+ — it ships as a separate
install from the built-in Windows PowerShell 5.1, and lands in
`%LOCALAPPDATA%\Microsoft\WindowsApps` (on the default user `PATH`) when installed
from the Store or `winget install Microsoft.PowerShell`. Check with
`where.exe pwsh.exe`. If you have only 5.1, set `DSH_CLI` to the whole invocation
instead — that is exactly what branch 2 now accepts:

```
DSH_CLI = pwsh.exe -NoProfile -File C:\Users\<you>\.dsh\bin\dsh.ps1
```

Because that value is several tokens and not one existing file, branch 2 splits
it into the right argv. The single-path form is no longer truncated either — a
value that names an existing file is kept as one entry however many spaces it
contains — but pointing `DSH_CLI` straight at `…\DeepSeek Harness\…\dsh.cmd`
still fails: the summarizer spawns the resolved command without a shell, and
Node will not start a `.cmd` that way. Keep the shim as the target.

Branch 4 needs no exported variable at all, which is why the shim is the
recommended form. Restart DSH after changing the environment, and note that
`dsh-headless` boots the sub-agent with the deployment's `agent-default-model`
(see the mode table above), not with `[plugins.dsh.summarize]`.

**Verify.** From Git Bash, the shim must answer like the CLI does:

```bash
pwsh.exe -NoProfile -File "$USERPROFILE/.dsh/bin/dsh.ps1" --version   # -> 0.2.0-rc.x
```

Then ask the **installed plugin** what it resolves — `detectDshCmd` is exported,
so this is exactly what the summarizer will spawn. A `dsh` that works in your
own shell proves nothing here:

```bash
node --input-type=module -e 'const m=await import("file:///"+process.argv[1]);console.log(JSON.stringify(m.detectDshCmd()))' \
  "C:/Users/<you>/.dsh/profiles/<profile>/node_modules/@zilliz/memsearch-dsh/index.js"
```

Forward slashes only in that path — they work in a `file://` URL, and typing
backslashes invites shell-mangling mistakes. Replace `<profile>` with the profile
the plugin is installed in (`desktop`, `headless`, …). DSH Desktop does not put a
`node` on `PATH`; if `node` is missing, run the same command through the app's own
Node runtime by prefixing `ELECTRON_RUN_AS_NODE=1` and using
`C:/Users/<you>/AppData/Local/Programs/DeepSeek Harness/DeepSeek Harness.exe`
in place of `node`.

Expected output on Windows:

```json
["pwsh.exe","-NoProfile","-File","C:\\Users\\<you>\\.dsh\\bin\\dsh.ps1"]
```

To reproduce the two claims this design rests on (both measured here):

```bash
node -e 'const{spawnSync}=require("node:child_process");const o={encoding:"utf-8"};
console.log("direct .cmd spawn:", spawnSync(process.env.USERPROFILE+"\\.dsh\\bin\\dsh.cmd",["--version"],o).error?.code);
console.log("transcript through cmd.exe:", JSON.stringify(spawnSync("cmd.exe",["/c","echo","a\\nb\\nc"],o).stdout))'
```

Expected:

```
direct .cmd spawn: EINVAL
transcript through cmd.exe: "a\r\n"
```

Node refuses to start a `.cmd` without a shell, and `cmd` reads the embedded
newline as a command separator, so everything after the first line of the
transcript is dropped. `pwsh -File` passes it whole.

## How it works

- **Capture** — listens on `session/event` for `turn/end`, renders the turn
  (`[User]` / `[Assistant]` / `[Tool call]` lines), then fire-and-forget
  summarizes (if enabled) and appends it to the **session's own**
  `memory/YYYY-MM-DD.md` with the shared anchor format
  `<!-- session:<id> turn:<N> db:<path> -->`. The project directory comes from
  `session.header.cwd`, so a long-lived web surface captures every project it
  hosts, not just the process's boot directory. Turns are serialized (LLM
  summarize calls never overlap) and `captureExists` dedup keeps each turn
  idempotent if its event replays.
- **Inject** — on `agent/pre-step` at step 1, runs a bounded memsearch search
  over the user's question. Only when the search returns chunks does it inject
  them plus a `[memsearch] Retrieved memory context attached.` marker;
  otherwise the decision is returned unchanged (zero context cost). The model
  still evaluates whether each candidate chunk is relevant.
- **Recall** — registers a `memory-recall` skill (invocable through DSH's
  native `skill` tool) that performs search → expand → transcript drill-down
  and returns a curated summary.
- **Maintenance** — runs the shared maintenance runner (PROJECT.md / USER.md
  upkeep and memory-to-skill distillation), triggered on `session/disposed`
  plus a 6-hourly fallback timer. Each task is a due-state machine: it runs at
  most once per `min_interval_hours` (default 24h) and only when enabled in
  memsearch config (`[plugins.dsh.project_review]`, `[plugins.dsh.user_profile]`,
  `[plugins.dsh.memory_to_skill]`), mirroring the other platform plugins. The
  maintenance work is executed by a one-shot DSH headless agent (the same
  `dsh --profile headless` mechanism as summarization), booted with
  `MEMSEARCH_DSH_SUMMARIZE=1` so the plugin stays inert inside it.
- **Skill review panel (web only)** — a non-blocking dock strip above the
  composer (registered into the `conversation.input.dock` slot) lists skill
  candidates distilled into `.memsearch/skill-candidates/`. It is served by the
  plugin's browser half (`client.js`, declared through `dsh.client` in
  `package.json`) and talks to the host through two JSON routes on the DSH web
  server:
  - `GET /memsearch-dsh/skill-candidates?sessionId=<id>` — lists candidates
    (pending first) parsed from each candidate's `meta.json`.
  - `POST /memsearch-dsh/skill-review` with `{ sessionId, name, action }`:
    - `action: "review"` queues a `[memsearch] Skill candidate ...` user
      message into the live agent's inbox (`agent.inbox.append('next-turn',
      ...)`). The agent reviews the candidate on its next turn — non-blocking,
      it never interrupts a running turn and never opens a blocking dialog.
    - `action: "install"` runs `memsearch skills install <name> --path <dir>`
      in the background (detached, unref'd) to the resolved target: the first
      entry of `plugins.dsh.memory_to_skill.paths` in memsearch config
      (relative entries resolve against the project dir), else the DSH default
      `~/.agents/skills`, which the `skill-filesystem` provider watches and
      loads automatically.
  The project directory is resolved from the session id (its durable cwd), so
  the panel reflects the project of the session you are viewing on a
  multi-project web surface. The routes are registered once the DSH web server
  service becomes available (the memsearch plugin mounts in the base bundle
  layer, before the web server starts; `apply` retries on a 1s unref'd timer).
  Headless / TUI profiles have no browser: the `webServer` service never
  appears, no routes are registered, and everything else is unchanged.

## Uninstall

```bash
dsh plugin --profile web remove @zilliz/memsearch-dsh
```

Removing the dependency drops the profile-layer entry; the memory markdown
files and the Milvus index are left untouched.

## Development

- The plugin is plain ESM with no build step — `dsh plugin add` links the
  checkout directly, so edits are live after a profile reload.
- The browser half (`client.js`) is a prebuilt client-module bundle: it
  registers its factory with `window.__ModuleLoader__.load({ id, factory })`
  (the lazy CJS table the web shell serves at `/plugins/<id>/client.js`) and
  exports the Cordis client plugin shape (`inject` + `apply`). It is checked
  in as-is; edit it directly and keep the `__ModuleLoader__` registration
  format (mirror the shipped `@deepseek-ai/dsh-client-ui-*` `lib/client.js`
  bundles).
- Python helpers under `scripts/` are linted with the repo's `ruff` config and
  tested under `plugins/dsh/tests/`.
- Keep the memory-write format byte-compatible with the other platform
  plugins; see `plugins/opencode/scripts/capture-daemon.py` for the canonical
  writer.
