# Finalizer Metrics Report - 2026-06-24

## Scope

ISS-020 requires operational visibility into final help-card quality and finalization rate. This change adds a read-only metrics layer; it does not change `PipiFinalizeGraph`, recommendation strategy, or iOS behavior.

## Added

- `app.services.finalizer_metrics.finalizer_summary`
- `GET /admin/api/finalizer/summary`
- No-DB unit tests for finalization and final card contract metrics

## Metrics

- `finalization_rate`: finalized help cards divided by help cards ready for finalization.
- `help_final_quality`: finalized cards passing the minimal final-card contract divided by finalized cards.
- `intent_answer_writeback_rate`: `help_final` `IntentAnswer` writebacks divided by finalized cards.
- `light_event_rate`: `final_ready` light events divided by finalized cards.

## Minimal Final-Card Contract

A finalized help card is considered quality-passing when:

- the final `RecommendationCard` exists;
- the final card has a title;
- the final card has one decision factor or persisted reason;
- evidence ids are present;
- no legacy `reasons` / `bullets` / `followups` / `warning` payload fields are present;
- a `help_final` `IntentAnswer` points back to the help card;
- a `final_ready` `LightEvent` points back to the help card;
- the final card payload links to the source help card.

## Admin Endpoint

`GET /admin/api/finalizer/summary?since_hours=720`

The endpoint writes an admin audit log with `action=view_finalizer_summary`.

## Notes

This is an observation-only layer for ISS-020. The existing finalizer behavior remains governed by `PipiFinalizeGraph` and existing finalizer tests.
