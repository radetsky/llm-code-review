Django checks:
- Raw SQL, extra() or RawSQL that builds the query with string formatting and user input is critical.
- Report mark_safe on data that comes from a user, and csrf_exempt on a view that changes data.
- Report DEBUG = True, a hardcoded SECRET_KEY and ALLOWED_HOSTS = ["*"] in production settings.
- Report a view that changes data and has no login or permission check.
- Report a query in a loop that select_related or prefetch_related can replace.
- Report objects.get() with no handling of DoesNotExist and MultipleObjectsReturned.
