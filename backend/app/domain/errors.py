class DomainError(Exception):
    """Base error exposed by the domain module interface."""


class NotFound(DomainError):
    pass


class Conflict(DomainError):
    pass


class Forbidden(DomainError):
    pass

