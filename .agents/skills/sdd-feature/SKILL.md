---
name: sdd-feature
description: Orchestrate a complete SpecKit SDD feature using cost-optimized Codex subagents. Use for new features that should follow Specify, Clarify, Plan, Tasks, Analyze, Implement and Converge.
---

# SDD Feature Orchestrator

The user's text following `$sdd-feature` is the feature request.

You are the orchestration agent.

DO NOT implement the feature yourself.
DO NOT perform technical planning yourself.
Delegate each SDD phase to the corresponding custom agent.

Use SDD artifacts as the contract between phases.

## Context policy

Each phase MUST use a fresh subagent context whenever possible.

When spawning a new phase agent:

- do not copy the entire parent conversation
- use `fork_turns=none` when available
- provide only the phase objective
- provide the feature description when needed
- let the agent reconstruct context from SpecKit artifacts and the repository

Close completed phase agents after collecting their result, except a clarifier
that is waiting for a user answer.

Do not run multiple SDD phases concurrently when one depends on the output
of another.

## Phase 1 - Specify

Spawn custom agent `sdd_specifier`.

Give it the complete feature request from the user.

Wait for it to finish.

Verify that a feature spec was created.

If specification failed, stop.

## Phase 2 - Clarify

Spawn custom agent `sdd_clarifier`.

Ask it to run the SpecKit clarification workflow for the active feature.

If it returns `NEEDS_USER_INPUT`:

1. Ask the question to the user in the main conversation.
2. STOP and wait for the user's answer.
3. Send the answer back to the SAME `sdd_clarifier` agent.
4. Continue until clarification is complete.

Never answer clarification questions on behalf of the user.

When clarification completes, present a concise summary of:

- feature goal
- functional scope
- important constraints
- explicit exclusions
- remaining assumptions

Ask the user to approve the specification.

STOP until approved.

## Phase 3 - Plan

After specification approval, spawn custom agent `sdd_planner`.

Wait for it to complete `$speckit-plan`.

Present only the important architectural decisions, risks and affected
components to the user.

Ask the user to approve the technical plan.

STOP until approved.

## Phase 4 - Tasks

After plan approval, spawn custom agent `sdd_tasker`.

Wait for `$speckit-tasks` to complete.

Do not require user approval unless the task decomposition reveals a material
scope or architecture problem.

## Phase 5 - Analyze

Spawn custom agent `sdd_analyzer`.

Wait for `$speckit-analyze`.

If BLOCKING findings exist:

- STOP
- present them to the user
- do not implement

Proceed only when the analyzer reports `READY_TO_IMPLEMENT`.

## Phase 6 - Implement

Spawn custom agent `sdd_implementer`.

Wait for `$speckit-implement` to complete.

Do not perform implementation work in the parent thread.

## Phase 7 - Converge

Spawn custom agent `sdd_converger`.

Wait for `$speckit-converge`.

If it reports `CONVERGED`, finish.

If it reports `NOT_CONVERGED` and SpecKit has created or reopened actionable
tasks:

1. Run `sdd_implementer` again.
2. Run `sdd_converger` again.

Perform at most TWO implementation/convergence cycles in one invocation.

If convergence still fails after the second cycle, STOP and present the
remaining work to the user instead of continuing autonomously.

## Final response

When converged, report concisely:

- feature
- specification status
- implementation status
- tests executed
- convergence status
- relevant files changed
- any remaining non-blocking observations
