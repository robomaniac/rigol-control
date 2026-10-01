# Reduce file watching on the Pi

## What was observed

A read-only inspection on 2026-09-27 found this entry in the active VS Code server's log:

```text
2026-09-27 00:57:41.047 [error] [File Watcher ('parcel')] Inotify limit reached (ENOSPC) (path: /home/<user>)
```

Log: `~/.vscode-server/data/logs/20260927T004558/remoteagent.log`.

This confirms that VS Code attempted to watch the home directory recursively. That includes this repository, downloaded tools, virtual environments, application caches, and generated reports.

At the later inspection, the kernel limit was 8,192 watches per user. The VS Code file-watcher process had 2,000 watches, so the earlier limit error does **not** mean the limit was still exhausted. PID 3778 was the remote extension host, with its working directory at `/home/<user>`; it was in disk sleep with approximately 174 MiB resident memory and 323 MiB swapped out. The temporary report-rendering swap file also had approximately 311 MiB in use, alongside nearly full zram.

These observations establish a broad watcher scope and memory/disk pressure. They do not prove that file watching caused every SSH disconnection or all report-rendering delays.

## Applied remote settings

Prefer opening `~/rigol-control` as the VS Code folder instead of the entire home directory. For the current home-directory workspace, the following was applied to **Remote [SSH: <pi-hostname>]** settings on 27 September 2026:

```json
{
  "files.watcherExclude": {
    "**/dcdc-bench/runs/**": true,
    "**/dcdc-bench/examples/generated/**": true,
    "**/dcdc-bench/.tools/**": true,
    "**/dcdc-bench/test-artifacts/**": true,
    "**/rigol-control/Data/Runs/**": true,
    "**/.venv/**": true,
    "**/.vscode-server/**": true,
    "**/.cursor-server/**": true,
    "**/.codex/**": true,
    "**/.cache/**": true
  }
}
```

Host file: `~/.vscode-server/data/Machine/settings.json`. The change merged the ten `files.watcherExclude` entries, preserved other settings, replaced the file atomically, and read it back to verify every entry. No process was restarted. This is local machine configuration, not a prerequisite imposed on contributors.

This configuration excludes generated run trees, embedded-plot HTML, downloaded binaries, Python environments, caches, and the temporary swap file under `test-artifacts`. It does not hide files in Explorer or prevent opening reports directly. No `files.exclude` changes are proposed.

The repository already ignores `runs`, `examples/generated`, `.tools`, `test-artifacts`, and `.venv` in Git. VS Code search normally honors Git ignore files, but those rules do not replace explicit recursive watcher exclusions. No additional search exclusions are needed for this minimal change.

The inspection could read remote and workspace files, but not the user's Windows-side VS Code settings; effective client overrides may therefore still exist. The read-only investigation was followed by the limited configuration change above. Its effect on future disconnects has not yet been established.

## References

Microsoft documents recursive watcher troubleshooting and `files.watcherExclude` in [File Watcher Issues](https://github.com/microsoft/vscode/wiki/File-Watcher-Issues). Its [glob-pattern reference](https://code.visualstudio.com/docs/editor/glob-patterns) explains the `**/` patterns needed to match folders at different workspace depths. [Search Issues](https://github.com/microsoft/vscode/wiki/Search-Issues) documents how search uses Git ignore and exclusion settings.
