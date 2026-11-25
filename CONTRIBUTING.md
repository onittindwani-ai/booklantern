# Contributing

Set up first with `docs/05-RUN-LOCALLY.md` (on Windows use WSL 2 with Ubuntu). Then run `make install`, `.venv/bin/python -m pytest` and `python3 tools/check_docs.py`.


- Keep money as whole numbers in the smallest unit. One module owns rounding.
- A new adapter needs a stand in server test before it counts as tested, and a note in `docs/facts/` of what you read and what you could not.
- Do not tune the offline reader against the held out set and still call it held out. Make a new set.
- Do not edit `packages/`. Ask for a change in the shared base instead.
- No secrets, no real company or person names in examples, plain words, no dashes in docs.
- Run the tests, `python tools/check_docs.py` and `python tools/scan_secrets.py` before you open a change.
- A new setting goes into `.env.example` and `docs/04-ENVIRONMENT-VARIABLES.md`; a test fails when it is missing from either.
- Report a security problem through the repository Security tab (see `SECURITY.md`), not a public issue.
