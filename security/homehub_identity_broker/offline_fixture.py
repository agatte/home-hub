"""OFFLINE FIXTURE ONLY. Exclude from any future serving composition."""
from .runtime import Denied


def offline_fixture_bootstrap(broker, state, *, trusted_fixture):
    """Explicit offline builder ONLY. Flag is fixture intent, not OS privilege.

    No service composition may call this; real recovery/provisioning is absent.
    Caller supplies fake one-way verifier records; this function mints nothing.
    """
    if trusted_fixture is not True:
        raise Denied()
    try:
        with broker._lock:
            if any(p.exists() for p in (broker._db, broker._journal, broker._guard)):
                raise Denied()
            broker._transition(state, create=True)
    except Exception:
        pass
    else:
        return
    raise Denied()
