# Future Pi Writable Execution Policy (Design Only)

**Status:** Proposed — not implemented

## Problem

Pi currently has no enforceable filesystem sandbox. Quattro correctly refuses
ordinary writable Pi tasks and also rejects `full-access-explicit` because that
profile requests full network authority, while the Pi adapter can enforce only
no network access. This document defines the minimum design bar for any future
writable Pi capability; it does not authorize a bypass.

## Proposed profile

A future `pi-isolated-write-explicit` profile would require all of:

- a newly created disposable or explicitly user-selected isolated workspace;
- writable roots limited to that workspace and no desktop, account, or memory
  directories;
- `NetworkAccess.NONE`, enforced by the Pi runtime boundary rather than prompt
  text;
- explicit per-run approval and a user-visible confirmation summary;
- bounded command/time budgets and existing supervisor process-group controls;
- no publishing, credential access, browser sign-in, or external side effects.

It must remain unavailable for shared working trees. Codex continues to own
integration and final validation.

## Required adapter/runtime changes

1. Prove that Pi can enforce the isolated working directory and disabled
   network at process-launch level, not merely by passing tool instructions.
2. Add a dedicated policy profile only after the proof above exists; do not
   repurpose `full-access-explicit` or relax its network semantics.
3. Make the Pi adapter reject any writable roots beyond the isolated workspace
   and reject all unapproved tools.
4. Keep delegated Pi workers read-only and non-recursive.

## Validation gate

Before enabling the profile, demonstrate:

- attempted writes outside the isolated workspace fail;
- attempted network access fails;
- Pi task creation requires explicit approval;
- cancellation kills the full process group without orphaned children;
- a disposable write task is audited, validated, and reported by the existing
  durable task lifecycle;
- Codex account credentials, Quattro memory vaults, and user desktop files
  remain inaccessible.

## Security risks

A writable tool runtime without kernel/process-level workspace and network
containment can modify arbitrary files or exfiltrate data. Prompt-only rules,
model assurances, and post-hoc validation are insufficient controls. Until the
runtime proves containment, the current fail-closed behavior is the production
policy.
