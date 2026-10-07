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
"""The partition delta of spec/partition_image.md: a block diff, and its container.

The new image is described as runs of 4 KiB blocks that are copies of blocks the old
image already has (named by offset), all zeros, or literal bytes; the literals travel
zstd-compressed. The container is a tar of `ops.json` then `literals.zst`, in that
order, so that it can be applied from a stream that cannot seek.

Only the encoder needs the `zstandard` module: the reader and the reconstruction are
the standard library, for a consumer (the USB installer) that vendors this package
without its dependencies.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Iterator, List, Optional

from typing_extensions import TypeGuard

if TYPE_CHECKING:
    import zstandard

OPS_MEMBER = "ops.json"
LITERALS_MEMBER = "literals.zst"

BLOCK_SIZE = 4096  # ext4's block size
LITERALS_WINDOW_LOG = 27  # 128 MiB: the largest window a plain `zstd -d` accepts

COPY = "c"
LITERAL = "l"
ZERO = "z"

_READ_SIZE = 64 * 1024 * 1024
_HASH_SIZE = 16


class BlockDiffError(ValueError):
    """A delta that cannot be read, or cannot be what it says it is."""


@dataclass(frozen=True)
class Op:
    """One run of the target: `length` bytes copied from the source at
    `source_offset`, or zeros, or the next `length` literal bytes."""

    kind: str
    length: int
    source_offset: int = 0

    def to_json(self) -> list:
        if self.kind == COPY:
            return [self.kind, self.length, self.source_offset]
        return [self.kind, self.length]


@dataclass(frozen=True)
class Ops:
    """The runs that make up the target, in order, with the sizes they are for."""

    block_size: int
    target_size: int
    source_size: int
    ops: List[Op]

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "block_size": self.block_size,
                "target_size": self.target_size,
                "source_size": self.source_size,
                "ops": [op.to_json() for op in self.ops],
            },
            separators=(",", ":"),
        ).encode()

    @classmethod
    def from_json(
        cls,
        data: bytes,
        *,
        target_size: Optional[int] = None,
        source_size: Optional[int] = None,
    ) -> "Ops":
        """Parse and check the runs; with `target_size` and `source_size`, also check
        that they are for the image and the source the descriptor names."""
        try:
            obj = json.loads(data)
        except (ValueError, UnicodeDecodeError) as e:
            raise BlockDiffError(f"{OPS_MEMBER} is not JSON: {e}") from e
        if not isinstance(obj, dict):
            raise BlockDiffError(f"{OPS_MEMBER} is not an object")
        block_size = _positive_int(obj.get("block_size"), "block_size")
        t_size = _positive_int(obj.get("target_size"), "target_size")
        s_size = obj.get("source_size")
        if not _is_int(s_size) or s_size < 0:
            raise BlockDiffError(f"{OPS_MEMBER}: source_size is {s_size!r}")
        if target_size is not None and t_size != target_size:
            raise BlockDiffError(
                f"the delta reconstructs {t_size} bytes but the image is {target_size}"
            )
        if source_size is not None and s_size != source_size:
            raise BlockDiffError(
                f"the delta applies to {s_size} bytes but its descriptor names {source_size}"
            )
        raw = obj.get("ops")
        if not isinstance(raw, list) or not raw:
            raise BlockDiffError(f"{OPS_MEMBER}: ops is not a non-empty list")
        ops: List[Op] = []
        total = 0
        for n, item in enumerate(raw):
            if not isinstance(item, list) or len(item) not in (2, 3):
                raise BlockDiffError(f"{OPS_MEMBER}: op {n} is malformed: {item!r}")
            kind = item[0]
            length = _positive_int(item[1], f"op {n} length")
            if kind == COPY:
                if len(item) != 3:
                    raise BlockDiffError(f"{OPS_MEMBER}: op {n} copies from nowhere")
                offset = item[2]
                if not _is_int(offset) or offset < 0 or offset + length > s_size:
                    raise BlockDiffError(
                        f"{OPS_MEMBER}: op {n} copies {length} bytes from {offset!r}, "
                        f"outside the {s_size}-byte source"
                    )
                ops.append(Op(COPY, length, offset))
            elif kind in (LITERAL, ZERO):
                if len(item) != 2:
                    raise BlockDiffError(f"{OPS_MEMBER}: op {n} has a stray field")
                ops.append(Op(kind, length))
            else:
                raise BlockDiffError(f"{OPS_MEMBER}: op {n} has unknown kind {kind!r}")
            total += length
        if total != t_size:
            raise BlockDiffError(
                f"{OPS_MEMBER}: the ops produce {total} bytes, not the {t_size} of the image"
            )
        return cls(
            block_size=block_size, target_size=t_size, source_size=s_size, ops=ops
        )

    def bytes_of(self, kind: str) -> int:
        return sum(op.length for op in self.ops if op.kind == kind)


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_int(value: object, what: str) -> int:
    if not _is_int(value) or value <= 0:
        raise BlockDiffError(
            f"{OPS_MEMBER}: {what} is {value!r}, not a positive integer"
        )
    return value


# --- encoding -----------------------------------------------------------------------


@dataclass(frozen=True)
class Stats:
    """What the delta carries, for the log of whoever built it."""

    target_size: int
    source_size: int
    target_digest: str
    """Hex sha256 of the target, hashed on the way: what the image descriptor says."""
    source_digest: str
    """Hex sha256 of the source: what the delta descriptor names as its source."""
    copied: int
    """Bytes the device reads from its own slot."""
    zero: int
    literal: int
    """Bytes that travel, before compression."""
    literal_compressed: int
    """Bytes that travel."""
    runs: int


def _blocks(path: Path, block_size: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_READ_SIZE)
            if not chunk:
                return
            view = memoryview(chunk)
            for i in range(0, len(chunk), block_size):
                yield view[i : i + block_size].tobytes()


def _hash(block: bytes) -> bytes:
    return hashlib.blake2b(block, digest_size=_HASH_SIZE).digest()


def compressor(level: int) -> zstandard.ZstdCompressor:
    """What the literals, and every compressed blob, are made with: long-range
    matching over the window the device's plain `zstd -d` accepts."""
    import zstandard  # imported here so that the reader side stays stdlib-only

    params = zstandard.ZstdCompressionParameters.from_level(
        level,
        window_log=LITERALS_WINDOW_LOG,
        enable_ldm=True,
        threads=-1,
        write_checksum=1,
        write_content_size=1,
    )
    return zstandard.ZstdCompressor(compression_params=params)


def encode(source: Path, target: Path, out: BinaryIO, *, level: int = 19) -> Stats:
    """Write the delta that turns `source` into `target` onto `out`.

    Every block of the target is looked up among the blocks of the source: at the same
    offset first, so that an unchanged region is one long copy, then anywhere.
    """
    block_size = BLOCK_SIZE
    source_size = source.stat().st_size
    target_size = target.stat().st_size
    if target_size == 0:
        raise ValueError(f"{target} is empty")

    zero = bytes(block_size)
    zero_hash = _hash(zero)
    # Every source block's hash by block number, for the same-offset check, and the
    # first offset of each distinct hash, for a block that moved.
    hashes = bytearray()
    first: dict = {}
    offset = 0
    source_sha = hashlib.sha256()
    for block in _blocks(source, block_size):
        source_sha.update(block)
        h = _hash(block)
        hashes += h
        if h != zero_hash and h not in first:
            first[h] = offset
        offset += len(block)

    ops: List[Op] = []
    copied = zero_bytes = literal = 0

    def push(kind: str, length: int, source_offset: int = 0) -> None:
        if ops:
            last = ops[-1]
            if last.kind == kind and (
                kind != COPY or last.source_offset + last.length == source_offset
            ):
                ops[-1] = Op(kind, last.length + length, last.source_offset)
                return
        ops.append(Op(kind, length, source_offset))

    with tempfile.TemporaryFile() as literals:
        with compressor(level).stream_writer(literals, closefd=False) as writer:
            offset = 0
            target_sha = hashlib.sha256()
            for block in _blocks(target, block_size):
                target_sha.update(block)
                n = len(block)
                if block == zero[:n]:
                    push(ZERO, n)
                    zero_bytes += n
                else:
                    h = _hash(block)
                    i = offset // block_size * _HASH_SIZE
                    if hashes[i : i + _HASH_SIZE] == h:
                        push(COPY, n, offset)
                        copied += n
                    elif h in first:
                        push(COPY, n, first[h])
                        copied += n
                    else:
                        push(LITERAL, n)
                        literal += n
                        writer.write(block)
                offset += n
        literal_compressed = literals.tell()
        literals.seek(0)

        ops_json = Ops(block_size, target_size, source_size, ops).to_json()
        with tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as tar:
            tar.addfile(_member(OPS_MEMBER, len(ops_json)), io.BytesIO(ops_json))
            tar.addfile(_member(LITERALS_MEMBER, literal_compressed), literals)

    return Stats(
        target_size=target_size,
        source_size=source_size,
        target_digest=target_sha.hexdigest(),
        source_digest=source_sha.hexdigest(),
        copied=copied,
        zero=zero_bytes,
        literal=literal,
        literal_compressed=literal_compressed,
        runs=len(ops),
    )


def _member(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o644
    return info


# --- reading ------------------------------------------------------------------------


@dataclass
class Delta:
    ops: Ops
    literals: BinaryIO
    """`literals.zst` as a stream, still compressed: the caller decodes it."""


@contextlib.contextmanager
def open_delta(
    stream: BinaryIO,
    *,
    target_size: Optional[int] = None,
    source_size: Optional[int] = None,
) -> Iterator[Delta]:
    """Open a delta read from a stream: the ops, then the literals still compressed.

    The literal member is readable only while the tar is, hence a context manager.
    With `target_size` and `source_size`, the ops are checked against them.
    """
    try:
        tar = tarfile.open(fileobj=stream, mode="r|")
    except tarfile.TarError as e:
        raise BlockDiffError(f"the delta is not a readable tar: {e}") from e
    try:
        try:
            ops_member = tar.next()
            if ops_member is None or ops_member.name != OPS_MEMBER:
                raise BlockDiffError(
                    f"the delta does not start with {OPS_MEMBER}: "
                    f"{ops_member.name if ops_member else 'nothing'}"
                )
            ops_file = tar.extractfile(ops_member)
            if ops_file is None:
                raise BlockDiffError(f"{OPS_MEMBER} is not a file")
            ops = Ops.from_json(
                ops_file.read(), target_size=target_size, source_size=source_size
            )
            literals_member = tar.next()
            if literals_member is None or literals_member.name != LITERALS_MEMBER:
                raise BlockDiffError(
                    f"{LITERALS_MEMBER} does not follow {OPS_MEMBER}: "
                    f"{literals_member.name if literals_member else 'nothing'}"
                )
            literals = tar.extractfile(literals_member)
            if literals is None:
                raise BlockDiffError(f"{LITERALS_MEMBER} is not a file")
        except tarfile.TarError as e:
            raise BlockDiffError(f"the delta is not a readable tar: {e}") from e
        yield Delta(ops=ops, literals=literals)  # type: ignore[arg-type]
    finally:
        with contextlib.suppress(tarfile.TarError):
            tar.close()


class Reconstruction(io.RawIOBase):
    """The target image as a readable stream, produced run by run from the source
    device, the zero block and the decoded literals."""

    def __init__(self, ops: Ops, source_fd: int, literals: BinaryIO) -> None:
        super().__init__()
        self._ops = ops.ops
        self._fd = source_fd
        self._literals = literals
        self._i = 0
        self._pos = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:  # type: ignore[override]
        while self._i < len(self._ops):
            op = self._ops[self._i]
            left = op.length - self._pos
            if left == 0:
                self._i += 1
                self._pos = 0
                continue
            take = left if size < 0 else min(size, left)
            if op.kind == COPY:
                data = os.pread(self._fd, take, op.source_offset + self._pos)
                if len(data) != take:
                    raise BlockDiffError(
                        f"the source ended at {op.source_offset + self._pos + len(data)}; "
                        f"the delta copies up to {op.source_offset + op.length}"
                    )
            elif op.kind == ZERO:
                data = bytes(take)
            else:
                data = _read_exact(self._literals, take)
            self._pos += len(data)
            return data
        return b""


def _read_exact(stream: BinaryIO, n: int) -> bytes:
    parts = []
    got = 0
    while got < n:
        chunk = stream.read(n - got)
        if not chunk:
            raise BlockDiffError(
                f"the literal stream ended {n - got} bytes short of what the ops use"
            )
        parts.append(chunk)
        got += len(chunk)
    return b"".join(parts) if len(parts) != 1 else parts[0]
