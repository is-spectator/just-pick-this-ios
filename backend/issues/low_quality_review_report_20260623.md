# Low Quality Review API Report - 2026-06-23

## Issue

ISS-011: Low Quality Review 后台：人工标注归因/建议修复/seed patch。

## Scope

This slice tightens the existing admin eval review API. It does not change product routing, PipiLoop behavior, recommendation strategy, iOS, or benchmark cases.

## Changes

- Extended eval review payloads with:
  - `suggested_fix`
  - `seed_patch`
- Preserved existing fields:
  - `action`
  - `reviewer`
  - `notes`
  - `labels`
- Added validation:
  - `suggested_fix` must be an object or string when present.
  - `seed_patch` must be an object when present.
- Review responses now echo these fields.
- Admin audit logs persist the same payload in `after_json`.

## Why

Low-quality cases already could be listed and reviewed, but review decisions did not carry the actionable repair payload required by the issue backlog. This makes a reviewed seed gap or agent bug directly usable by data/agent operators without losing the suggested repair.

## Verification

- Updated `app/tests/test_admin_eval_review_api.py` to assert:
  - review response contains `suggested_fix`;
  - review response contains `seed_patch`;
  - `AdminAuditLog.after_json` stores both;
  - invalid non-object `seed_patch` is rejected with `422`.

## Remaining Work

- Add a richer admin UI editor for `suggested_fix` and `seed_patch`.
- Add an explicit workflow that turns approved `seed_patch` records into draft `IntentAnswer` rows.
- Add reviewer assignment/status lifecycle if ops volume grows.
