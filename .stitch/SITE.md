# SentinelOps — Site Vision

## Purpose

One page that does two jobs at once:

1. **Portfolio proof.** A recruiter or hiring engineer lands here from LinkedIn and
   sees, in 30 seconds, that a real engineer designed and shipped a real system.
2. **Product credibility.** A platform lead sees whether this is worth trying on
   their own alerts.

Both readers want the same thing: evidence. Same page serves both.

## Audience

Platform engineers, SRE leads, CTOs at companies running Kubernetes with an
on-call rotation. They will scroll fast, look for the architecture, and bounce on
marketing language.

## The one message

> An alert tells you *what* broke, not *why*. SentinelOps automates the first 20
> minutes of every incident and hands the engineer a root-cause hypothesis with
> the evidence behind it — in seconds. It never acts on the cluster, and the raw
> alert always gets through.

## Page roadmap

| # | Page | Status | Purpose |
|---|---|---|---|
| 1 | `index` | next | The whole story on one page |
| 2 | `architecture` | later | Deep dive: pipeline, ADRs, trade-offs |
| 3 | `demo` | later | Recorded replay of a fault-injection scenario |

Start with `index`. Do not build 2 and 3 until 1 is genuinely good.

## `index` section order

1. **Hero** — problem sentence, mechanism sentence, GitHub CTA.
2. **The 3 AM problem** — what manual triage costs (~20 min of context gathering).
3. **How it works** — the architecture diagram, labelled, real component names.
4. **What the engineer receives** — the hypothesis card with evidence, disproof,
   blast radius, next steps.
5. **Three decisions worth defending** — deterministic pipeline over agent loop
   (predictable cost, ~$0.006/alert); graceful degradation (raw alert always
   delivered); privacy (mandatory redaction, optional fully local model).
6. **Security posture** — read-only credentials, no write tools, output never
   executed, prompt-injection containment.
7. **Status** — shipped vs roadmap, honest table.
8. **Footer** — GitHub, LinkedIn, contact.

## Hard rules

- Never claim anything not true today. Roadmap items live in the status table.
- Every number on the page must be defensible: ~$0.006/alert, ~20 min manual
  triage, 60+ tests, CI green.
- No pricing, no monetization, no GTM copy on this page — that stays private.
- No fabricated logos, testimonials, or customer counts. There are no customers.
