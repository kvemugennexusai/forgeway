<!--
This checklist restates CONTRIBUTING.md's "PR expectations" section
verbatim — see that file for the full context behind each item. Check off
what applies; leave unchecked (with a note) anything that doesn't.
-->

## What does this change?

<!-- One or two sentences. Keep the PR scoped to one thing. -->

## Checklist (see CONTRIBUTING.md's "PR expectations")

- [ ] Backend change: `pytest tests/ -v` is green, and there's a new test for the new behavior.
- [ ] Frontend change: `tsc --noEmit`, `npm run lint`, and `npm run build` are all clean.
- [ ] If `api/app/models.py` changed, `web/lib/types.ts` was checked for the same change.
- [ ] The relevant doc in `docs/` was updated in this same PR, if this changes documented behavior.
- [ ] No fabricated `MEASURED` or `PUBLISHED` value was added anywhere, in fixtures or in code.
- [ ] No secrets, no machine-specific absolute paths, no committed build artifacts.
- [ ] This PR is scoped to one thing (not bundled with an unrelated change).
