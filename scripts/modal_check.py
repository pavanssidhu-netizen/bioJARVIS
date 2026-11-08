"""ONE authenticated call to the deployed Modal specialist function (cost: a fraction of a cent on CPU).

    .venv/bin/python scripts/modal_check.py
Prints the round-trip latency and the (honest) result - "not_configured" until the teammate model lands.
"""
import os
import time

import modal

app_name = os.getenv("MODAL_VISION_APP", "labmate-vision")
fn = modal.Function.from_name(app_name, os.getenv("MODAL_VISION_FUNCTION", "detect"))
t0 = time.perf_counter()
res = fn.remote(b"\xff\xd8\xff\xe0" + b"\0" * 32, "modal_check")
print(f"{app_name}.detect -> {res}  ({(time.perf_counter() - t0) * 1000:.0f} ms incl. cold start)")
