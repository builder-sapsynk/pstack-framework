# Durable jobs and cancellation

## Sub-features

Durable jobs and cancellation.

## How to get to it (user POV)

Retain the emitted job path and host terminal handle.

## Driving it with the CLI

Run status and checkpoint, cancel a deliberately waiting owned job, then inspect final receipt and known process identities.

## Gotchas

Cancellation requested differs from cancelled; local process death does not prove remote API termination.
