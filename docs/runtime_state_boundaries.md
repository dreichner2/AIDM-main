# Runtime State Boundaries

AIDM currently has several overlapping state stores because older projection
paths, long-term canon memory, and the newer runtime game-state pipeline coexist.
Use these boundaries when adding runtime features.

## Live Runtime Truth

`Session.state_snapshot` is the live runtime game state once a session has a
snapshot. Systems that need the current play state should read from this
snapshot for:

- `currentScene`
- `playerCharacters`
- inventory, health, XP, and currency
- quests
- locations
- `knownNpcs` and `partyNpcs`
- flags
- `stateChangeLedger`

Future live systems should read scene, quest, location, NPC, character,
inventory, health, XP, currency, flags, and ledger state from
`Session.state_snapshot` unless they intentionally need long-term canon memory or
authored campaign data.

## Projection And Summary State

`SessionState` is a projection and summary record. It exists for older context
paths, rolling summaries, current-location/current-quest summaries, active
segment summaries, and memory snippets. It is not the live source of truth for
mutable runtime state after `Session.state_snapshot` exists.

## Long-Term Canon Memory

`emergent_memory`, `story_entities`, `story_facts`, and `story_threads` are
long-term canon memory. They capture durable story knowledge that arose through
play. They are not the immediate mutable runtime state for the current scene,
active quest list, character resources, or per-turn state application.

## Campaign Seed And Backcompat Fields

`Campaign.location` and `Campaign.current_quest` are seed and backcompat fields.
They may initialize or support older views, but they are not live runtime truth
after a session has `Session.state_snapshot`.

## Authored Story And Map Data

`CampaignSegment` is authored or planned story tooling. It is not the live quest
system.

`Map` records are authored map assets and data. They are not yet the live
location graph for runtime navigation.

## Turn Pipeline Metadata

Turn metadata under `state_pipeline` is audit, debug, and per-turn pipeline
metadata. It records extraction, validation, application, and summary details for
an individual turn. It is not the canonical session state.

The canonical session state remains `Session.state_snapshot`; the
`state_pipeline` metadata explains how a turn produced or attempted changes.
