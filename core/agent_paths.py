"""Reject redirected/network destinations for trusted agent-triggered workflows.

Agents cannot supply paths. This is a recheck of a user's UI selection, not a
filesystem sandbox or protection against concurrent hostile path replacement.
"""
from pathlib import Path
import os
import stat

from core.agent_commands import CommandError


def validate_output(path, extension=None):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or str(path).startswith(('\\\\', '//')):
        raise CommandError('PATH_DENIED')
    if extension and path.suffix.lower() != extension:
        raise CommandError('PATH_DENIED')
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise CommandError('PATH_DENIED')
    if os.name == 'nt':
        import ctypes
        get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
        get_drive_type.argtypes = [ctypes.c_wchar_p]
        # Fixed/local removable/RAM drives only; mapped network drives are denied.
        if get_drive_type(path.anchor) not in (2, 3, 6):
            raise CommandError('PATH_DENIED')
        if any(Path(part).is_reserved() or part.rstrip(' .') != part for part in path.parts[1:]):
            raise CommandError('PATH_DENIED')
    if path.resolve() != path:
        raise CommandError('PATH_DENIED')
    return path
