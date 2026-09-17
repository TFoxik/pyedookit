class EdookitError(Exception):
    """Base error for all pyedookit failures."""


class AuthError(EdookitError):
    """Credentials were rejected, or the long-lived Plus4U session expired."""


class SessionExpired(EdookitError):
    """The short-lived edookit session cookie expired; caller should refresh and retry."""


class ParseError(EdookitError):
    """A portal page did not have the expected structure.

    Edookit's markup isn't versioned, so this is the signal a parser needs updating
    rather than a bug in the caller's usage.
    """
