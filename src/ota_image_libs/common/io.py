# Copyright 2022 TIER IV, INC. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Common shared helper functions for IO."""

from __future__ import annotations

import hashlib
import io
import shutil
import sys
from functools import partial
from pathlib import Path

DEFAULT_FILE_CHUNK_SIZE = 1024**2  # 1MiB


if sys.version_info >= (3, 11):
    from hashlib import file_digest as _file_digest

else:

    def _file_digest(
        fileobj: io.BufferedReader,
        digest,
        /,
        *,
        _bufsize: int = DEFAULT_FILE_CHUNK_SIZE,
    ) -> hashlib._Hash:
        """
        Basically a simpified copy from 3.11's hashlib.file_digest.
        """
        if isinstance(digest, str):
            digestobj = hashlib.new(digest)
        else:
            digestobj = digest()

        buf = bytearray(_bufsize)  # Reusable buffer to reduce allocations.
        view = memoryview(buf)
        while True:
            size = fileobj.readinto(buf)
            if size == 0:
                break  # EOF
            digestobj.update(view[:size])

        return digestobj


def cal_file_digest(
    fpath: str | Path, digest, chunk_size: int = DEFAULT_FILE_CHUNK_SIZE
) -> hashlib._Hash:
    """Generate file digest with <algorithm> and returns Hash object.

    A wrapper for the _file_digest method.
    """
    with open(fpath, "rb") as f:
        return _file_digest(f, digest, _bufsize=chunk_size)


file_sha256 = partial(cal_file_digest, digest=hashlib.sha256)
file_sha256.__doc__ = "Generate file digest with sha256."


def remove_file(_fpath: Path, *, ignore_error: bool = True) -> None:
    """Use proper way to remove <_fpath>."""
    try:
        _fpath.unlink(missing_ok=True)
    except IsADirectoryError:
        return shutil.rmtree(_fpath, ignore_errors=ignore_error)
    except Exception:
        if not ignore_error:
            raise
