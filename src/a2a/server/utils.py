# Contains code from Google Agent2Agent samples (Apache-2.0).
# Adapted for FuzzAgent.
# See THIRD_PARTY_NOTICES and THIRD_PARTY_LICENSES/Apache-2.0.txt.

from src.a2a.types import (
    JSONRPCResponse,
    ContentTypeNotSupportedError,
    UnsupportedOperationError,
)
from typing import List


def are_modalities_compatible(
    server_output_modes: List[str], client_output_modes: List[str]
):
    """Modalities are compatible if they are both non-empty
    and there is at least one common element."""
    if client_output_modes is None or len(client_output_modes) == 0:
        return True

    if server_output_modes is None or len(server_output_modes) == 0:
        return True

    return any(x in server_output_modes for x in client_output_modes)


def new_incompatible_types_error(request_id):
    return JSONRPCResponse(id=request_id, error=ContentTypeNotSupportedError())


def new_not_implemented_error(request_id):
    return JSONRPCResponse(id=request_id, error=UnsupportedOperationError())
