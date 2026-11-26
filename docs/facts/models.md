# Language model reader

UNVERIFIED live. Date written: 2026-11-23.

What the code does (`apps/api/src/booklantern/model_tasks.py`, `extraction/live.py`): it goes through the base wrapper (`sendora_core.llm`), which sends `POST /v1/messages` to the Anthropic Messages API with the key in `x-api-key`, the `anthropic-version` header, the system prompt, the bill text inside a marked untrusted block, and a JSON schema in `output_config.format`. The request and response fields follow the vendor documentation as read for the base on 2026-11-23 (see the hub's FACTS-AND-SOURCES). Models used: `claude-sonnet-5-5` for reading bills, `claude-haiku-5-5` for wording.

What was run: the whole path against a mock server on this machine (`mock/anthropic_mock.py`) that checks the request shape, and replay of recorded answers (`data/llm_fixtures/`, made by that mock server). **Never run with a real key.** How a real model reads a real bill, its cost per bill and its error rate are unknown.

The wrapper takes text only, so a scanned page cannot be sent. See `14-LIMITS-AND-HONEST-NOTES.md`.
