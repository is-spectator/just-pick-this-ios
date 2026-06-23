# Personalization Product Path Report - 2026-06-24

## Scope

This slice tightens `ISS-015 Personalization`.

Before this change, user preference memory was recorded from behavior events, but the area-food product path mainly used explicit words in the current query. That meant the acceptance criterion "same query, different preferences -> different decision factor" was not strongly true unless the user repeated their preference in the message.

## Runtime Change

Area-food retrieval now passes `User.profile_json.preference_memory_v1` into `area_food_evidence_policy`.

The memory summary is converted into a deterministic preference hint and reuses the existing prompt-configured `profile_cuisine_rules`:

- `top_cuisines=粤菜` -> Cantonese / light profile
- `top_cuisines=杭帮菜|本帮菜|淮扬菜` -> Jiangzhe / light profile
- `spice_preferences=not_spicy` -> non-spicy profile
- `companions=parents` -> parents profile
- `companions=date` -> date profile

The selected rule is also written into retrieval metadata/payload:

- `area_food_preference.rule_name`
- `area_food_preference.source`
- `preference_source`
- `preference_rule_name`

This keeps the product path deterministic and does not add a new table or alter the PipiLoop architecture.

## Acceptance Coverage

`backend/app/tests/test_area_food_evidence_policy_profiles.py` now proves:

- same query + Cantonese memory selects `cantonese_profile`;
- same query + Jiangzhe memory selects `jiangzhe_profile`;
- same query + non-spicy memory selects `non_spicy_profile`;
- same query with Cantonese vs Jiangzhe memory produces different `decision_factor` text.

The test file is now in the no-DB allowlist so these checks run locally even without PostgreSQL.

## Verification

Commands run locally:

```bash
cd backend
uv run --extra dev pytest app/tests/test_area_food_evidence_policy_profiles.py -q -rx
```

Result:

- `9 passed`

## Remaining Verification

Run the full DB-backed product suite or CI backend job to verify the end-to-end `/v1/chat/turn` retrieval payload includes the new preference metadata for real users with stored preference memory.
