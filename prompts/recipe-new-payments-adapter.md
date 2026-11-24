# Recipe: add a way to take payment

> Read apps/api/src/booklantern/adapters/others.py (the Stripe adapter). Write an adapter for <provider> that only creates a pay link for an invoice. It must never capture, charge or move money, and in draft mode it saves a placeholder and calls nobody. Read the provider's current API pages first, list what you could not read as UNVERIFIED in docs/facts/, test against a stand in server, and register it.
