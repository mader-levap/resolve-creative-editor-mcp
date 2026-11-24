"""The edit__ tools, built on the Lua bridge and FFmpeg. One module per kind of edit; tools don't import each other.

Rules every mutating tool follows:
- Without confirm=true it only returns a preview of what it would do.
- It checks first, acts, then reads the timeline back. Results carry an `_operation` block
  (status, verification, changes, warnings); see outcome.py.
- Clips are never deleted before their replacement exists with the grade and settings copied onto it.
Responses are compact by default; pass detail/limit for more.
A handler's docstring is a one-line summary; its arguments and behaviour are documented by its tool
description in schemas/edit.py, which is what the model reads.
"""
