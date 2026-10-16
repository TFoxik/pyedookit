class EdookitError(Exception):
    """Base error for all pyedookit failures."""


class AuthError(EdookitError):
    """Credentials were rejected, or Plus4U answered that a new login is needed."""


class SessionExpired(EdookitError):
    """The short-lived edookit session cookie expired; caller should refresh and retry."""


class ParseError(EdookitError):
    """A portal page did not have the expected structure.

    Edookit's markup isn't versioned, so this is the signal a parser needs updating
    rather than a bug in the caller's usage.
    """


class EdookitConnectionError(EdookitError):
    """The portal or Plus4U could not be reached, or a session renewal failed.

    Covers network errors, timeouts and renewals that fail for any reason
    other than Plus4U asking for a new login; retrying later is the fix.
    """
