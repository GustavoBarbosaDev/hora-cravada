from sqlalchemy.exc import DBAPIError

FOREIGN_KEY_VIOLATION = "23503"
EXCLUSION_VIOLATION = "23P01"


def sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)
