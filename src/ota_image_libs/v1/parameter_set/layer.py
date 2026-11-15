# Copyright 2026 TIER IV, INC. All rights reserved.
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
"""The layer of a parameter set: writing it from a tree, and reading it back.

The layer is an OCI image layer (tar, zstd-compressed) holding, for each slot the set
fills, the slot's directory, an opaque whiteout in it (`.wh..wh..opq`: the directory
replaces the base's), and the regular files and directories below it. Nothing else:
no link, no device, no other whiteout, nothing outside a slot.

Both directions are here so that the format has one owner: the builder writes with
`write_parameter_layer`, and a consumer validates (and unpacks) with
`read_parameter_layer`, which refuses anything the writer would not have written.
"""

from __future__ import annotations

import io
import os
import posixpath
import stat
import tarfile
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import IO, BinaryIO

import zstandard

from ota_image_libs.common.oci_spec import Sha256Digest

from .schema import ParameterSetFileEntry, slot_of
from .slots import ParameterSlotRef

OPAQUE_WHITEOUT = ".wh..wh..opq"
"""In a slot's directory: the directory replaces the base's (OCI image layer spec)."""
WHITEOUT_PREFIX = ".wh."

TAR_FORMAT = tarfile.PAX_FORMAT
ZSTD_LEVEL = 19
READ_SIZE = 1024**2
_DIR_MODE = 0o755
_OPAQUE_MODE = 0o644


class ParameterLayerInvalid(Exception):
    """The layer holds something a parameter set does not."""


@dataclass
class ParameterLayerInfo:
    """What a layer holds, as written or as read."""

    digest: Sha256Digest | None = None
    """Of the compressed blob; known to the writer only."""
    size: int = 0
    """Of the compressed blob; known to the writer only."""
    diff_id: Sha256Digest | None = None
    """Of the uncompressed tar: what the set's config lists in `diff_ids`."""
    files: list[ParameterSetFileEntry] = field(default_factory=list)
    files_size: int = 0


class _HashingWriter(io.RawIOBase):
    def __init__(self, sink: BinaryIO) -> None:
        self._sink = sink
        self.hash = sha256()
        self.size = 0

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:  # type: ignore[override]
        _b = bytes(b)
        self.hash.update(_b)
        self.size += len(_b)
        self._sink.write(_b)
        return len(_b)


class _HashingReader(io.RawIOBase):
    def __init__(self, source: BinaryIO) -> None:
        self._source = source
        self.hash = sha256()
        self.size = 0

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:  # type: ignore[override]
        _data = self._source.read(len(b))
        _n = len(_data)
        b[:_n] = _data
        self.hash.update(_data)
        self.size += _n
        return _n

    def drain_hashing(self) -> None:
        while _data := self._source.read(READ_SIZE):
            self.hash.update(_data)
            self.size += len(_data)


def _tarinfo(name: str, *, type_: bytes, mode: int, size: int = 0) -> tarfile.TarInfo:
    """A member with nothing but its name, type, mode and size: owned by root, no
    names, no time, so that the same tree always makes the same layer."""
    _ti = tarfile.TarInfo(name)
    _ti.type = type_
    _ti.mode = mode
    _ti.size = size
    _ti.uid = _ti.gid = 0
    _ti.uname = _ti.gname = ""
    _ti.mtime = 0
    return _ti


def write_parameter_layer(
    root: Path, slots: list[ParameterSlotRef], out: BinaryIO
) -> ParameterLayerInfo:
    """Write the layer of `slots` from the tree at `root` to `out`.

    Each slot's directory under `root` must exist and hold only regular files and
    directories. Members are in a fixed order with fixed owners and times, and the
    permission bits are kept (setuid, setgid and sticky are refused), so the layer
    depends on the tree's contents alone.
    """
    _info = ParameterLayerInfo()
    _compressed = _HashingWriter(out)
    _compressor = zstandard.ZstdCompressor(level=ZSTD_LEVEL)
    with _compressor.stream_writer(_compressed, closefd=False) as _zstd:  # type: ignore[arg-type]
        _tar_out = _HashingWriter(_zstd)  # type: ignore[arg-type]
        with tarfile.open(fileobj=_tar_out, mode="w|", format=TAR_FORMAT) as _tar:
            for _slot in sorted(slots, key=lambda _s: _s.relpath):
                _write_slot(_tar, root, _slot, _info)
        _info.diff_id = Sha256Digest(_tar_out.hash.hexdigest())
    _info.digest = Sha256Digest(_compressed.hash.hexdigest())
    _info.size = _compressed.size
    return _info


def _write_slot(
    tar: tarfile.TarFile, root: Path, slot: ParameterSlotRef, info: ParameterLayerInfo
) -> None:
    _slot_dir = root / slot.relpath
    if os.path.realpath(_slot_dir) != os.path.join(
        os.path.realpath(root), slot.relpath
    ):
        raise ParameterLayerInvalid(
            f"slot {slot.name!r}: {_slot_dir} is behind a symbolic link"
        )
    _st = os.lstat(_slot_dir)
    if not stat.S_ISDIR(_st.st_mode):
        raise ParameterLayerInvalid(
            f"slot {slot.name!r}: {_slot_dir} is not a directory"
        )
    tar.addfile(
        _tarinfo(slot.relpath, type_=tarfile.DIRTYPE, mode=_perm(_st, _slot_dir))
    )
    tar.addfile(
        _tarinfo(
            f"{slot.relpath}/{OPAQUE_WHITEOUT}",
            type_=tarfile.REGTYPE,
            mode=_OPAQUE_MODE,
        )
    )
    for _dirpath, _dirnames, _filenames in os.walk(_slot_dir, followlinks=False):
        _dirnames.sort()
        _rel_part = Path(_dirpath).relative_to(_slot_dir).as_posix()
        _rel_dir = slot.relpath if _rel_part == "." else f"{slot.relpath}/{_rel_part}"
        for _name in sorted([*_dirnames, *_filenames]):
            if _name.startswith(WHITEOUT_PREFIX):
                raise ParameterLayerInvalid(
                    f"{_dirpath}/{_name}: a name starting with {WHITEOUT_PREFIX!r} "
                    "would be read as a whiteout"
                )
            _src = Path(_dirpath) / _name
            _rel = f"{_rel_dir}/{_name}"
            _st = os.lstat(_src)
            if stat.S_ISDIR(_st.st_mode):
                tar.addfile(
                    _tarinfo(_rel, type_=tarfile.DIRTYPE, mode=_perm(_st, _src))
                )
            elif stat.S_ISREG(_st.st_mode):
                _ti = _tarinfo(
                    _rel, type_=tarfile.REGTYPE, mode=_perm(_st, _src), size=_st.st_size
                )
                _hash = sha256()
                with open(_src, "rb") as _f:
                    tar.addfile(_ti, _HashedFile(_f, _hash))
                info.files.append(
                    ParameterSetFileEntry(
                        path=_rel,
                        size=_st.st_size,
                        digest=Sha256Digest(_hash.hexdigest()),
                    )
                )
                info.files_size += _st.st_size
            else:
                raise ParameterLayerInvalid(
                    f"{_src}: only regular files and directories go into a parameter set"
                )


class _HashedFile:
    """A file read by tarfile, hashed on the way."""

    def __init__(self, f: BinaryIO, hash_) -> None:
        self._f = f
        self._hash = hash_

    def read(self, size: int = -1) -> bytes:
        _data = self._f.read(size)
        self._hash.update(_data)
        return _data


def _perm(st: os.stat_result, path: Path) -> int:
    _mode = stat.S_IMODE(st.st_mode)
    if _mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
        raise ParameterLayerInvalid(
            f"{path}: setuid, setgid and sticky bits do not go into a parameter set"
        )
    return _mode


#
# ------ reading ------ #
#


def _member_path(member: tarfile.TarInfo) -> str:
    _name = member.name
    if _name.startswith("./"):
        _name = _name[2:]
    _name = _name.rstrip("/") if member.isdir() else _name
    if (
        not _name
        or _name.startswith("/")
        or posixpath.normpath(_name) != _name
        or _name.split("/")[0] == ".."
        or "\0" in _name
    ):
        raise ParameterLayerInvalid(f"member {member.name!r} is not a normalized path")
    return _name


def read_parameter_layer(
    blob: BinaryIO,
    slots: list[ParameterSlotRef],
    *,
    extract_to: Path | None = None,
    max_size: int | None = None,
    blob_digest: Sha256Digest | None = None,
    diff_id: Sha256Digest | None = None,
) -> ParameterLayerInfo:
    """Validate the layer read from `blob` (compressed) against the set's `slots`, and
    unpack it under `extract_to` when given.

    Every member must be a slot's directory, the opaque whiteout directly in it, or a
    regular file or directory below it, and every slot must have its directory and its
    whiteout. The whiteout itself is not unpacked: under `extract_to` each slot's
    directory is the whole of its new contents. Files are created exclusively, without
    following links, owned by the caller (root on a device) and with the member's
    permission bits.

    `max_size` bounds the regular files' total size, for unpacking onto a tmpfs.
    `blob_digest` and `diff_id`, when given, are checked against the compressed blob
    and the uncompressed tar once read; what was unpacked before a mismatch is found
    is the caller's to discard. Returns what the layer holds, with its `diff_id`.
    Raises ParameterLayerInvalid.
    """
    _info = ParameterLayerInfo()
    _seen: set[str] = set()
    _dirs: set[str] = set()
    _opaque: set[str] = set()
    _blob_in = _HashingReader(blob)
    _decompressed = zstandard.ZstdDecompressor().stream_reader(_blob_in, closefd=False)  # type: ignore[arg-type]
    _tar_in = _HashingReader(_decompressed)  # type: ignore[arg-type]
    try:
        with tarfile.open(
            fileobj=io.BufferedReader(_tar_in, READ_SIZE),  # type: ignore[arg-type]
            mode="r|",
        ) as _tar:
            for _member in _tar:
                _path = _member_path(_member)
                if _path in _seen:
                    raise ParameterLayerInvalid(f"{_path!r} appears twice")
                _seen.add(_path)
                _slot = slot_of(_path, slots)
                if _slot is None:
                    raise ParameterLayerInvalid(
                        f"{_path!r} is not in one of the set's slots"
                    )
                _name = posixpath.basename(_path)
                _parent = posixpath.dirname(_path)
                if _member.mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
                    raise ParameterLayerInvalid(
                        f"{_path!r} has setuid, setgid or sticky"
                    )
                if _name.startswith(WHITEOUT_PREFIX):
                    if not (
                        _name == OPAQUE_WHITEOUT
                        and _parent == _slot.relpath
                        and _member.isreg()
                        and not _member.issparse()
                        and _member.size == 0
                    ):
                        raise ParameterLayerInvalid(
                            f"{_path!r}: the only whiteout is the empty opaque one "
                            "directly in a slot's directory"
                        )
                    _opaque.add(_slot.name)
                    continue
                if _path != _slot.relpath and _parent not in _dirs:
                    raise ParameterLayerInvalid(f"{_path!r} comes before its directory")
                if _member.isdir():
                    _dirs.add(_path)
                    if extract_to is not None:
                        _mkdir(extract_to, _path, stat.S_IMODE(_member.mode))
                elif _member.isreg() and not _member.issparse():
                    if _path == _slot.relpath:
                        raise ParameterLayerInvalid(
                            f"slot {_slot.name!r} is not a directory"
                        )
                    _info.files_size += _member.size
                    if max_size is not None and _info.files_size > max_size:
                        raise ParameterLayerInvalid(
                            f"the files exceed {max_size} bytes"
                        )
                    _hash = sha256()
                    _src = _tar.extractfile(_member)
                    assert _src is not None
                    _write_file(
                        extract_to, _path, stat.S_IMODE(_member.mode), _src, _hash
                    )
                    _info.files.append(
                        ParameterSetFileEntry(
                            path=_path,
                            size=_member.size,
                            digest=Sha256Digest(_hash.hexdigest()),
                        )
                    )
                else:
                    raise ParameterLayerInvalid(
                        f"{_path!r}: only regular files and directories go into a "
                        "parameter set"
                    )
        # the end-of-archive blocks and any padding after them are in the diff_id too
        _tar_in.drain_hashing()
        _blob_in.drain_hashing()
    except (tarfile.TarError, zstandard.ZstdError, EOFError) as e:
        raise ParameterLayerInvalid(f"not a zstd-compressed tar: {e}") from e

    for _slot in slots:
        if _slot.relpath not in _dirs or _slot.name not in _opaque:
            raise ParameterLayerInvalid(
                f"slot {_slot.name!r} lacks its directory or its opaque whiteout"
            )
    _info.diff_id = Sha256Digest(_tar_in.hash.hexdigest())
    if diff_id is not None and _info.diff_id != diff_id:
        raise ParameterLayerInvalid(f"the tar is {_info.diff_id}, not {diff_id}")
    _digest = Sha256Digest(_blob_in.hash.hexdigest())
    if blob_digest is not None and _digest != blob_digest:
        raise ParameterLayerInvalid(f"the blob is {_digest}, not {blob_digest}")
    return _info


def _mkdir(root: Path, path: str, mode: int) -> None:
    _dst = root / path
    _dst.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
    if _dst.is_symlink() or not _dst.is_dir():
        raise ParameterLayerInvalid(f"{_dst} is not a directory")
    os.chmod(_dst, mode)


def _write_file(root: Path | None, path: str, mode: int, src: IO[bytes], hash_) -> None:
    _fd = None
    if root is not None:
        _fd = os.open(
            root / path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
    try:
        while _data := src.read(READ_SIZE):
            hash_.update(_data)
            if _fd is not None:
                os.write(_fd, _data)
        if _fd is not None:
            os.fchmod(_fd, mode)
    finally:
        if _fd is not None:
            os.close(_fd)
