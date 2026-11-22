"""The bridge folder and the names of files written to it."""
import os
import re
import time
import uuid

# Not under AppData: the Claude desktop app is MSIX-packaged and its AppData\Local writes are redirected
# into its private package folder, invisible to Resolve.
DIR = os.environ.get("RESOLVE_BRIDGE_DIR") or os.path.join(os.path.expanduser("~"), "resolve-claude-bridge")
os.makedirs(DIR, exist_ok=True)


def media_output(source, suffix):
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.splitext(os.path.basename(source))[0])[:48] or "media"
    return os.path.join(DIR, f"{stem}_{uuid.uuid4().hex[:8]}{suffix}")


def new_output(a, suffix):
    output = a.get("output") or os.path.join(DIR, f"export_{time.strftime('%Y%m%d-%H%M%S')}{suffix}")
    if os.path.exists(output):
        raise FileExistsError(f"refusing to overwrite {output}")
    return output
