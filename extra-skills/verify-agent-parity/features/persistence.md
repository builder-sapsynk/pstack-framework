# Follow-up with retained context

## Sub-features

Follow-up with retained context.

## How to get to it (user POV)

Set resume_job to the owned completed job path.

## Driving it with the CLI

Use a new request preserving provider/model/cwd/mode, ask for previous task context and rerun its check. Compare session IDs and new job IDs.

## Gotchas

Completed-session resumption is not live native collaboration messaging; never restore repository snapshots implicitly.
