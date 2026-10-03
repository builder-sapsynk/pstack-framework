# Automation capability mapping

The complete Benny pack and make-bot-ui workflow are included. Installation leaves both dormant. Cursor-native events/routines continue to use their original host API when running in Cursor. Other hosts require a supported service adapter and separate readiness tests.

On Codex, discover the supported automation API for scheduling and thread wakeups. Preserve trigger coordinates, deduplication, ownership and checkpoint recovery. Normalize an incoming top-level message_ts to the operational trigger.ts field once before freezing source coordinates. If using polling instead of an event hook, state the changed latency and verify duplicate/recovery behavior with a harmless authorized test.

Benny delegates must lack Slack write tools and credentials through real host enforcement. Inherited tool maps or prompt prohibitions do not establish isolation. Use the coordinator for source-thread writes or all work when enforced separation is unavailable. Preserve real UI repro, rejection window, evidence, draft PR only, and never-merge/deploy requirements.

A scheduled job must retrieve the exact committed source/project pin and required credentials in a new environment. Local process IDs and /tmp state cannot provide that. Missing event/runtime integration is an unmet capability, not an omitted source feature or successful simulated delivery.
