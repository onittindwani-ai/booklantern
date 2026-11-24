# Recipe: add an accounting system

> Read apps/api/src/booklantern/adapters/base.py and quickbooks.py. Write a new accounting adapter for <system> that reads vendors and invoices and creates a draft bill only when live mode, ACCOUNTING_WRITE and an approval are all on. Read the vendor's current API pages first and write down in docs/facts/ what you read and what you could not. Test it against a small stand in server in mock/ before anything else. Register it in registry.py with its variable names. Never call the real service and never put a key in a file.
