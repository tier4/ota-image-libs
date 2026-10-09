# Copyright 2025 TIER IV, INC. All rights reserved.
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
"""Writing a partition-based payload onto block devices.

The counterpart of `deploy_image`: streams partition images (raw, zstd-compressed or
reconstructed from a block diff) onto devices, hashing on the way, and checks the
result. Shared by the USB installer, the flash helper and the update agent, so it takes
plain values (a size, a hex digest, a root hash) rather than descriptor types, and uses
the standard library plus the `zstd` and `veritysetup` binaries: the installer vendors
this package without the `zstandard` module.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from . import block_diff

logger = logging.getLogger(__name__)

CHUNK_SIZE = 4 * 1024 * 1024

# `verityinfo=<dev>:<root-hash>:<hash-offset>` on the kernel command line.
VERITYINFO_RE = re.compile(r"verityinfo=[^\s:]+:([0-9a-fA-F]{64}):(\d+)")


class PartitionDeployError(Exception):
    """Anything that stops a partition being written, or proved written."""


class ByteSource(Protocol):
    """What an image is read from: a file, a pipe, or a `block_diff.Reconstruction`."""

    def read(self, size: int = ..., /) -> bytes: ...


def chunks(
    src: ByteSource, size: int, what: str, *, chunk_size: int = CHUNK_SIZE
) -> Iterator[bytes]:
    """Exactly `size` bytes of `src`, in pieces; a source that ends early is an error."""
    read = 0
    while read < size:
        chunk = src.read(min(chunk_size, size - read))
        if not chunk:
            raise PartitionDeployError(f"{what} ended after {read} of {size} bytes")
        read += len(chunk)
        yield chunk


def device_size(path: Path) -> int:
    """Capacity of a block device, or the size of a regular file.

    `stat` reports 0 for a block device, so the end is found by seeking to it.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as e:
        raise PartitionDeployError(f"cannot open {path}: {e}") from e
    try:
        return os.lseek(fd, 0, os.SEEK_END)
    except OSError as e:
        raise PartitionDeployError(f"cannot measure {path}: {e}") from e
    finally:
        os.close(fd)


def write_image(
    src: ByteSource,
    size: int,
    dst_path: Path,
    *,
    progress: Callable[[int], None] | None = None,
    chunk_size: int = CHUNK_SIZE,
    digest: str | None = None,
) -> int:
    """Write `size` bytes from `src` onto `dst_path`, reporting 0..100 percent.

    The capacity is checked before the first byte is written. With `digest` (hex
    sha256) the bytes are hashed on the way and a mismatch is an error.
    """
    capacity = device_size(dst_path)
    if size > capacity:
        raise PartitionDeployError(
            f"image is {size} bytes but {dst_path} holds {capacity}; refusing to write"
        )
    if size == 0:
        raise PartitionDeployError("image is empty")

    last_percent = -1

    def report(percent: int) -> None:
        nonlocal last_percent
        if progress is not None and percent > last_percent:
            last_percent = percent
            progress(percent)

    report(0)
    written = 0
    hasher = hashlib.sha256() if digest is not None else None
    fd = os.open(dst_path, os.O_WRONLY)
    try:
        with os.fdopen(fd, "wb", closefd=True) as dst:
            for chunk in chunks(
                src,
                size,
                "the payload (the partition is now half-written)",
                chunk_size=chunk_size,
            ):
                dst.write(chunk)
                if hasher is not None:
                    hasher.update(chunk)
                written += len(chunk)
                report(written * 100 // size)
            dst.flush()
            os.fsync(dst.fileno())
    except OSError as e:
        raise PartitionDeployError(f"failed writing {dst_path}: {e}") from e

    if digest is not None and hasher is not None and hasher.hexdigest() != digest:
        raise PartitionDeployError(
            f"the image written to {dst_path} hashes to {hasher.hexdigest()[:12]}…, not the "
            f"{digest[:12]}… its descriptor says; it must not be booted"
        )
    report(100)
    logger.info("wrote %d bytes to %s", written, dst_path)
    return written


def source_digest(dev: Path, size: int) -> str:
    """The sha256 of the first `size` bytes of `dev`: what a delta says it applies to.

    A committed slot holds the image it was written from, byte for byte, so no copy of
    the previous payload has to be kept.
    """
    hasher = hashlib.sha256()
    try:
        with open(dev, "rb") as f:
            for chunk in chunks(f, size, str(dev)):
                hasher.update(chunk)
    except OSError as e:
        raise PartitionDeployError(f"cannot read {dev}: {e}") from e
    return hasher.hexdigest()


def delta_applies_to(dev: Path, *, source_digest_hex: str, source_size: int) -> bool:
    """Whether `dev` holds the bytes a delta was built from; askable before the delta
    is fetched."""
    got = source_digest(dev, source_size)
    if got == source_digest_hex:
        logger.info(
            "%s holds the %d bytes the delta applies to (%s…)",
            dev,
            source_size,
            source_digest_hex[:12],
        )
        return True
    logger.info(
        "the delta applies to %s… but %s holds %s…; this device is not at the version "
        "the delta was built from",
        source_digest_hex[:12],
        dev,
        got[:12],
    )
    return False


def can_apply_delta() -> bool:
    """Whether `zstd` is there: what a delta's literals and a compressed blob need."""
    return shutil.which("zstd") is not None


def _feed(src: ByteSource, dst: BinaryIO, chunk_size: int = CHUNK_SIZE) -> None:
    """Copy `src` into `dst` and close it; a closed pipe means the reader gave up."""
    try:
        while chunk := src.read(chunk_size):
            dst.write(chunk)
    except (BrokenPipeError, ValueError, OSError):
        pass
    finally:
        with contextlib.suppress(BrokenPipeError, OSError):
            dst.close()


@contextlib.contextmanager
def zstd_decompressed(src: ByteSource) -> Iterator[BinaryIO]:
    """`src`, a zstd stream, decoded on the way through `zstd -d`.

    A thread feeds the tool, since `src` may be a stream without a file descriptor. A
    decoder that exits non-zero is an error even when the consumer was satisfied, or a
    truncated image would pass.
    """
    if not can_apply_delta():
        raise PartitionDeployError(
            "this payload is zstd-compressed and there is no zstd to decode it"
        )
    with subprocess.Popen(
        ["zstd", "-d", "-c"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        feeder = threading.Thread(target=_feed, args=(src, proc.stdin), daemon=True)
        feeder.start()
        assert proc.stdout is not None
        try:
            yield cast(BinaryIO, proc.stdout)
        except BaseException:
            proc.kill()
            stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            if stderr.strip():
                logger.error("zstd: %s", stderr.strip().splitlines()[-1])
            raise
        # Whatever the consumer left unread is drained, so that the tool can finish and
        # its exit status means what it says.
        proc.stdout.read()
        feeder.join(timeout=60)
        if proc.wait() != 0:
            stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            raise PartitionDeployError(
                f"zstd exited {proc.returncode}: "
                f"{stderr.strip().splitlines()[-1] if stderr.strip() else 'no output'}"
            )


def write_compressed_image(
    src: ByteSource,
    size: int,
    dst_path: Path,
    *,
    progress: Callable[[int], None] | None = None,
    digest: str | None = None,
) -> int:
    """`write_image` for a blob stored zstd-compressed: `size` and `digest` are the
    image's, not the blob's, and the bytes are decoded on the way to the partition."""
    with zstd_decompressed(src) as raw:
        return write_image(raw, size, dst_path, progress=progress, digest=digest)


def apply_delta(
    delta_stream: BinaryIO,
    dst_path: Path,
    *,
    source_dev: Path,
    source_digest_hex: str,
    source_size: int,
    target_size: int,
    target_digest: str,
    progress: Callable[[int], None] | None = None,
    source_verified: bool = False,
) -> int:
    """Reconstruct the target onto `dst_path` from a block diff and the bytes on
    `source_dev`, read in place.

    Unless `source_verified`, the source is hashed first; the runs are checked against
    the sizes before the first byte is written, and the result against `target_digest`.
    """
    if not can_apply_delta():
        raise PartitionDeployError(
            "this payload carries a delta but there is no zstd to decode its literals"
        )
    if not source_verified and not delta_applies_to(
        source_dev, source_digest_hex=source_digest_hex, source_size=source_size
    ):
        raise PartitionDeployError(
            f"the delta applies to {source_digest_hex} but {source_dev} does not hold "
            "those bytes; this device is not at the version the delta was built from"
        )
    try:
        with block_diff.open_delta(
            delta_stream, target_size=target_size, source_size=source_size
        ) as delta:
            ops = delta.ops
            logger.info(
                "applying the delta: %d runs, %d bytes copied from %s, %d zero, %d literal",
                len(ops.ops),
                ops.bytes_of(block_diff.COPY),
                source_dev,
                ops.bytes_of(block_diff.ZERO),
                ops.bytes_of(block_diff.LITERAL),
            )
            fd = os.open(source_dev, os.O_RDONLY)
            try:
                with zstd_decompressed(delta.literals) as literals:
                    written = write_image(
                        block_diff.Reconstruction(ops, fd, literals),
                        target_size,
                        dst_path,
                        progress=progress,
                        digest=target_digest,
                    )
                    if literals.read(1):
                        raise PartitionDeployError(
                            "the delta carries more literal bytes than its runs use"
                        )
            finally:
                os.close(fd)
    except block_diff.BlockDiffError as e:
        raise PartitionDeployError(f"the delta cannot be applied: {e}") from e
    except OSError as e:
        raise PartitionDeployError(f"cannot read {source_dev}: {e}") from e
    return written


def verify_verity(dev: Path, root_hash: str, hash_offset: int) -> bool:
    """Check a written partition against the root hash its descriptor carries, as the
    initramfs will at boot. Returns whether the check ran: without `veritysetup` it is
    left to the boot."""
    if shutil.which("veritysetup") is None:
        logger.warning(
            "veritysetup is not installed; the hash tree is checked at boot only"
        )
        return False
    cmd = [
        "veritysetup",
        "verify",
        str(dev),
        str(dev),
        root_hash,
        f"--hash-offset={hash_offset}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise PartitionDeployError(
            f"{dev} does not verify against root hash {root_hash} (veritysetup: "
            f"{detail[-1] if detail else f'exited {result.returncode}'})"
        )
    logger.info("%s verifies against root hash %s…", dev, root_hash[:12])
    return True


def verity_params_in(cmdline: str) -> tuple[str, int] | None:
    """The root hash and hash offset a kernel command line carries, if it carries any."""
    m = VERITYINFO_RE.search(cmdline)
    if not m:
        return None
    return m.group(1).lower(), int(m.group(2))


def check_verity_pairing(
    cmdline: str,
    root_hash: str | None,
    hash_offset: int | None,
    *,
    what: str = "the boot blob",
) -> None:
    """Refuse a boot blob whose `verityinfo=` names another rootfs than the one beside
    it, before writing; a rootfs without verity annotations has nothing to check."""
    if root_hash is None or hash_offset is None:
        return
    found = verity_params_in(cmdline)
    if found is None:
        raise PartitionDeployError(
            f"the rootfs blob is annotated with a verity root hash but {what} carries no "
            "verityinfo=<dev>:<root-hash>:<hash-offset>; the slot could not be booted"
        )
    if found != (root_hash.lower(), hash_offset):
        raise PartitionDeployError(
            f"the two blobs are not from the same build and the slot would be refused at "
            f"boot: {what} names root hash {found[0]} at offset {found[1]}, the rootfs "
            f"blob is annotated {root_hash} at {hash_offset}"
        )
    logger.info("%s names the rootfs blob's own root hash %s…", what, found[0][:12])
