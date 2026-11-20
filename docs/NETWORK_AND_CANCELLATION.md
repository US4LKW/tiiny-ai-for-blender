# Network recovery and cancellation

Development build `dev-0.3.9`; extension version `0.1.0`.

## Stop generation

**Stop generation** ends local waiting immediately and marks the job as cancelled. It does not wait for a disconnected Tiiny to answer. If the task ID is known, a separate background request asks Tiiny to cancel that task.

The interface distinguishes these outcomes:

| Message | Meaning |
| --- | --- |
| Requesting remote stop | The add-on is trying to send a cancellation request. |
| Stop request accepted | Tiiny accepted the request; this alone does not prove computation has ended. |
| Tiiny confirmed stop | The cancellation endpoint explicitly returned a cancelled status. |
| Remote stop unconfirmed | The device did not confirm the request. Check its state before another generation. |
| Device task state unknown | A submission was in flight when waiting stopped; a task ID may not yet be available. |

A late task-submission response triggers a best-effort cancellation of the newly known task. The client never repeats a stage-creation POST automatically. While a previous submission is genuinely unresolved, a new generation is refused to avoid submitting a second job accidentally.

Late poll responses and downloads cannot restart a cancelled pipeline or enqueue its model for import. A model already waiting in Blender's import queue is skipped after cancellation. An import already executing synchronously inside Blender cannot be interrupted by another UI action until Blender returns control.

The active job remains accessible when the current Blender scene changes. The Stop control remains visible if local image-tool setup is being displayed. Loading another .blend file or disabling the extension stops local jobs.

## Lost connection limit

Preferences contains **Lost connection limit (s)**, default **300 seconds**. It limits time without a successful task-status response, rather than the total generation time.

A responsive device may take a long time or report unchanged progress; neither alone triggers this limit. After prolonged loss of responses, local waiting stops and a best-effort remote cancellation is attempted. Automatic generation restart is not performed.

Individual calls also have deadlines. Final artifact downloads allow a long overall transfer but use a shorter socket inactivity timeout. This avoids treating a continuously transferring large file as a failed generation while limiting the lifetime of dead connections.

## What cannot be guaranteed offline

Python cannot forcibly terminate a thread already inside an operating-system network call. The caller stops waiting, ignores late results and bounds the number of outstanding network operations. The underlying operation may finish later. An already running local image-preparation subprocess can also finish after cancellation; its result will not continue that cancelled generation.

A disconnected Pocket Lab may continue computing. Local cancellation is not evidence of device shutdown, memory release, or successful remote cancellation.

## Reports that survive a failed generation

A JSON report is created before capability retrieval, updated after task submission, and refreshed during polling. It records:

- development build and public extension version;
- requested and effective preset settings;
- capability snapshot and exact stage parameters;
- task IDs and input artifact references;
- last server progress/message and successful response time;
- transient polling failures and time without a response;
- failure stage and local/remote cancellation status.

Updates use an atomic temporary-file replacement. The configured API key, base URL and known local image/output paths are redacted from diagnostic error text. Inspect any additional TiinyOS logs before sharing them publicly.

The report format is now version 3. Existing version-2 reports remain useful evidence; their historical contents are not rewritten.

## Verification

The cancellation suite uses an actual loopback HTTP server that deliberately stalls task submission, polling or artifact downloads. It checks prompt local stop, late-response isolation, remote-cancel failure, a bounded outage, continued polling of a responsive task, live report updates, queued-import cancellation, and creation of a new job after cleanup. These tests do not run either neural model or reproduce a hardware crash.
