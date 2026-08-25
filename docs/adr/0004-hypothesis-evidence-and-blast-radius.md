# ADR-0004: Hypotheses carry evidence and a disproof; blast radius is a separate guardrail

- Status: accepted
- Date: 2026-08-25

## Context

A plausible hypothesis is cheap. An LLM will always produce one, and it will
always sound reasonable. At 3 AM the expensive mistake is following a confident
but wrong hypothesis down a dead end.

Two things make a hypothesis actually useful to an on-call engineer:

1. The **evidence** it rests on, so the engineer can check the reasoning in
   seconds instead of trusting a black box.
2. The **cheapest observation that would prove it wrong**. Knowing how to kill a
   theory fast is worth more than one more point of confidence.

Ranking purely by confidence optimises for the wrong thing. But ranking also has
a blind spot: it decides *what to investigate first*, and a naive score buries a
low-confidence hypothesis that, if true, would explain a full outage.

## Decision

1. **Every hypothesis carries its evidence and its disproof.** The structured
   output includes `evidence` (the specific signals from the collected context
   that support it) and `disproof` (the single cheapest check that would
   invalidate it). Both are surfaced in the delivered message.
2. **Investigation order is `confidence × evidence strength × (1 / time-to-disprove)`.**
   Cheap-to-disprove, well-evidenced hypotheses are tested first, because ruling
   them out is fast and informative.
3. **Blast radius is a separate guardrail, not a ranking multiplier.** Each
   hypothesis also carries `blast_radius` (single-pod, service, cluster). A
   high-blast-radius hypothesis is never dropped from the output, even at low
   confidence or high time-to-disprove. Ranking decides order; blast radius
   decides what cannot be omitted.

## Consequences

- The engineer can trust the output faster (evidence attached) and falsify it
  faster (disproof attached), which is the whole point of the 3 AM window.
- This iteration enriches the single hypothesis with these fields. The full
  ranked list of candidate hypotheses, ordered by the formula above with the
  blast-radius guardrail applied, is the next step and fits the same single LLM
  call (ADR-0001): the model returns several candidates, the pipeline ranks them.
- Blast radius as a distinct axis keeps a rare-but-catastrophic cause visible
  even when a common-but-minor one ranks higher.
