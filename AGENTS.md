# Booklantern: notes for Codex

This install belongs to ONE client. Never mix data from another client. Keep MODE=draft and ACCOUNTING_WRITE=false until docs/09-GO-LIVE-CHECKLIST.md is finished and the owner says so. Never post, send or create anything outside the app yourself. Never move money and never ask for a bank login. Never put keys in files that are committed. Never edit packages/. The reader is a suggestion a person confirms. No tax or accounting advice. Plain words, no dashes.

## Working in this repo

- Python in `apps/api/src/booklantern`, tests in `apps/api/tests`. Web in `apps/web`. The shared base is in `packages/` and is read only.
- Money is whole numbers in the smallest unit plus a currency. Never use a decimal for money. Use `money.py`.
- Every number comes from code. A model may only word numbers it is given.
- Run `python -m pytest`, `pnpm --filter web typecheck` and `pnpm build` before you say something works.
- Counts in docs come from `data/counts.json`. Run `python tools/make_counts.py` then `python tools/check_docs.py`.
- Never edit the held out extraction result in `data/eval/heldout_first_run.json`.
