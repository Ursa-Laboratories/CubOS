"""Backend failures and the declared SiLA execution errors."""


class BackendError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class InvalidProtocol(Exception):
    """The named preset is unknown or its protocol bundle is invalid."""


class CubBusy(Exception):
    """The CubOS runtime is already performing an incompatible operation."""


class BackendAuthenticationFailed(Exception):
    """The CubOS API rejected this service's credentials."""


class BackendUnavailable(Exception):
    """The CubOS API could not be reached or returned an invalid response."""


class UnknownRun(Exception):
    """The run identifier is not present in CubOS persistence."""


class UnknownArtifact(Exception):
    """The requested artifact does not belong to the run."""


class InvalidRequest(Exception):
    """A request parameter or configuration prevents this operation."""


class RunConflict(Exception):
    """The run identifier is already associated with a different submission."""


class ArtifactTooLarge(Exception):
    """The artifact exceeds the configured transfer size limit."""


class RunFailed(Exception):
    """CubOS recorded a failed protocol run; retrieve GetRun for its details."""


class RunCancelled(Exception):
    """CubOS confirmed that the protocol run was cancelled."""


BACKEND_ERRORS = (
    InvalidProtocol, CubBusy, BackendAuthenticationFailed, BackendUnavailable,
    UnknownRun, UnknownArtifact, InvalidRequest, RunConflict, ArtifactTooLarge,
)

ERROR_TYPES = dict(zip(
    ("invalid_protocol", "busy", "auth", "unavailable", "unknown_run",
     "unknown_artifact", "invalid_request", "conflict", "artifact_too_large"),
    BACKEND_ERRORS,
))


async def backend_call(awaitable):
    try:
        return await awaitable
    except BackendError as error:
        raise ERROR_TYPES.get(error.code, BackendUnavailable)(str(error)) from None
