# Custom harness protocol

A custom harness is an executable argv array in the agent's `command` field, with optional `extra_args` appended for every run. Reserved `--lgt-` flags are rejected in extra arguments. The backend launches it without a shell. Stdout uses UTF-8 NDJSON; stderr is saved in the per-run log. Each stdout line is bounded by `ndjson_line_limit`. Missing terminal events, malformed events, and nonzero process exits fail the run.

## Capability probe

`POST /harnesses/custom/probe` accepts `{"command": ["python", "my_runner.py"], "extra_args": ["--profile", "local"]}`. `extra_args` is optional. The backend appends these arguments and `--lgt-probe` to the command, closes stdin, and requires one JSON line followed by a successful exit within three seconds. The descriptor is cached per complete argv and used to validate agents.

```json
{"type":"probe","contract_version":1,"version":"1.0","capabilities":{"resume":false,"interrupt":true,"text_delta":true,"allowed_tools":true,"image_input":false,"usage":true,"rate_limits":false},"models":[{"id":"local-model","label":"Local model","description":"Local inference","default":true}],"tools":[{"id":"Read","label":"Read","description":"Read project files"}]}
```

Every capability is a boolean. Models require `id`, `label`, `description`, and `default`. Tools require `id`, `label`, and `description`. A custom harness that advertises tool restrictions must enforce the requested `allowed_tools` in its implementation. The backend validates that the selected tools and model appear in its catalog.

Version 1 requires `resume: false`; custom sessions rebuild cold. Interruption terminates the process tree. The probe does not perform a model turn.

## Turn request

The normal command receives exactly one stdin line. The backend then closes stdin.

```json
{"type":"turn","version":1,"run_id":"01...","prompt":"Rendered channel context","model":"local-model","system_prompt":"Agent instructions","session_mode":"cold","session_id":null,"allowed_tools":["Read"],"attachments":[{"attachment_id":"01...","filename":"notes.pdf","media_type":"application/pdf","size_bytes":1234,"path":"C:/.../notes.pdf"}]}
```

Attachment paths refer to server storage. A harness can pass supported files into its model as native inputs. Other files remain available through their paths and the rendered prompt.

## Output events

```json
{"type":"run_started","session_id":"optional-session-id"}
{"type":"text_delta","text":"Partial answer"}
{"type":"message","text":"Completed answer"}
{"type":"tool_call","tool_call_id":"t1","tool":"Read","input":{"file_path":"README.md"}}
{"type":"tool_result","tool_call_id":"t1","is_error":false,"exit_code":0,"duration_ms":12,"output":"File contents"}
{"type":"usage","tokens_in":100,"tokens_out":20,"tokens_cached_in":30,"tokens_reasoning":5,"tokens_total":120,"context_tokens":800,"model_context_window":200000}
{"type":"limits","snapshot":{"primary":{"usedPercent":10,"windowDurationMins":300,"resetsAt":1800000000}}}
{"type":"run_finished","ok":true}
```

Tool calls and results are normalized before they enter the event log. The backend measures output bytes and lines before applying `tool_output_cap`. Token usage events are increments for the current run. `message` commits text to history; `text_delta` is live only. A successful run requires a terminal event with `ok: true` and a zero process exit. The terminal event must be the last stdout line. A failed terminal can include `error` and `cancelled`.

The executable is responsible for honoring its advertised capabilities. Unsupported event types fail the run.
