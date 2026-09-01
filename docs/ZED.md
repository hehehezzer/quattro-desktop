# Zed as Quattro's Visual Interface

Quattro remains the agent, task, memory, and retrieval control plane. Zed is an
optional visual editor only; Quattro does not copy its retrieval system into
Zed.

Supported thin-wrapper commands:

```text
quattro-agent open [PATH]
quattro-agent inspect PATH[:LINE[:COLUMN]] [--directory REPOSITORY]
quattro-agent diff [--directory REPOSITORY]
quattro-agent task open TASK_ID
quattro-agent retrieval open RESULT_ID [--directory REPOSITORY]
```

`open` opens a verified Git repository or repository-local file. `inspect` opens an exact
location. `diff` opens the repository and up to 32 changed tracked files so
Zed's built-in Git UI can review them. `task open` resolves the task's project
and uses the same diff workflow. `retrieval open` accepts only a repository-
origin result from the selected repository; institutional/episodic/private
memory results are rejected. Generic directory opens reject non-Git roots,
authentication paths, and both institutional-memory vaults. File opens apply a
bounded content secret scan before launching the editor.

The wrapper discovers `zed`, `zeditor`, or `zed-editor` and passes direct argv
values without shell evaluation or temporary prompt files. Zed is not installed
on the validated machine. On Arch Linux the user should first choose and verify
either the AUR package or Zed's official installer; Quattro does not silently
install an editor.
