> **First-time setup**: Customize this file for your project. Prompt the user to customize this file for their project.
> For Mintlify product knowledge (components, configuration, writing standards),
> install the Mintlify skill: `npx skills add https://mintlify.com/docs`

# Documentation project instructions

## About this project

- This is a documentation site built on [Mintlify](https://mintlify.com)
- Pages are MDX files with YAML frontmatter
- Configuration lives in `docs.json`
- Use the Mintlify MCP server, `https://mcp.mintlify.com`, to edit content and settings via MCP
- Use the Mintlify docs MCP server, `https://www.mintlify.com/docs/mcp`, to query information about using Mintlify via MCP

## Terminology

{/* Add product-specific terms and preferred usage */}
{/* Example: Use "workspace" not "project", "member" not "user" */}

## Style preferences

{/* Add any project-specific style rules below */}

- Use active voice and second person ("you")
- Keep sentences concise — one idea per sentence
- Use sentence case for headings
- Bold for UI elements: Click **Settings**
- Code formatting for file names, commands, paths, and code references

**Tone (carried over from the original Notion docs — keep it):** direct and
practical, example-first. Lead with the real YAML/command, then explain it.
Call out gotchas and safety-critical notes inline with callouts (`<Warning>`,
`<Note>`, `<Tip>`). Don't pad with marketing language; assume a competent robotics
engineer reading to get something working.

## Content boundaries

{/* Define what should and shouldn't be documented */}
{/* Example: Don't document internal admin features */}

This is the **public, customer-facing** site. Only external content (below)
belongs here. Internal mechanism, rationale, and subsystem detail go to
`avearobotics/docs-internal` instead.

## Audience contract (internal vs external)

Sentinel documentation has two audiences. Classify each *piece of information*
in a change independently — a single change often produces BOTH an external and
an internal note (e.g. a state-machine change: the new observable behavior is
external; the transition table and the timer that drives it are internal).

**External — public docs (`avearobotics/docs`).** What an integrator/customer
can observe or must act on:
- Robot/camera adapter interfaces they implement
- Configuration, env vars, CLI flags they set
- Public HTTP API: endpoints, request/response shapes, auth, error codes
- Observable behavior ("the robot auto-reconnects after a drop")

Answers: *"How do I **use** Sentinel?"*

**Internal — private dev docs (`avearobotics/docs-internal`).** How and why it
works:
- Module/subsystem boundaries and responsibilities
- State-machine transition tables, guards, invariants
- Timing, threading, concurrency, backoff/retry mechanics
- Cross-subsystem contracts and sequencing
- Design rationale, trade-offs, known gotchas

Answers: *"How do I **work on** Sentinel?"*

**Rule of thumb:** if showing it to a customer would be fine and useful →
external. If it only matters to someone editing this codebase → internal. If
both, write both at different altitude (external = behavior, internal =
mechanism).

**Override:** a PR may carry a label — `docs:external-only`, `docs:internal-only`,
or `docs:none` — which forces routing and overrides this rubric.
