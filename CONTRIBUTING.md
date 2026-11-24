# Contributing

- Keep money as whole numbers in the smallest unit. One module owns rounding.
- A new adapter needs a stand in server test before it counts as tested, and a note in `docs/facts/` of what you read and what you could not.
- Do not tune the offline reader against the held out set and still call it held out. Make a new set.
- Do not edit `packages/`. Ask for a change in the shared base instead.
- No secrets, no real company or person names in examples, plain words, no dashes in docs.
- Run the tests and `python tools/check_docs.py` before you open a change.
