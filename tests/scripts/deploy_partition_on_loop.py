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
"""The partition deployer against real loop devices, real veritysetup and real zstd.

The unit tests fake both tools, which is the right trade for a suite that has to run
anywhere -- but it leaves the one thing that matters untested: that veritysetup really
does refuse a slot whose bytes have changed, and that a delta really does reconstruct
the next image from the bytes that are on the device. This runs the same code on the
real tools. It needs loop devices, so it is not part of the suite.

    docker run --rm --privileged -v "$PWD/src:/libs:ro" -v "$PWD/tests/scripts:/t:ro" \
        ubuntu:24.04 sh -c 'apt-get update -qq &&
            apt-get install -y -qq python3 e2fsprogs cryptsetup-bin zstd &&
            mkdir -p /work && PYTHONPATH=/libs python3 /t/deploy_partition_on_loop.py'
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from ota_image_tools.libs import block_diff
from ota_image_tools.libs.deploy_partition_image import (
    PartitionDeployError,
    apply_delta,
    delta_applies_to,
    device_size,
    source_digest,
    verify_verity,
    write_image,
)

WORK = Path("/work")
SLOT_SIZE = 128 << 20
IMAGE_SIZE = "64M"

results: list[tuple[str, bool]] = []


def sh(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            hasher.update(chunk)
    return hasher.hexdigest()


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed))
    print(f"  {'PASS' if passed else 'FAIL'}  {name}{f'   {detail}' if detail else ''}")


def build_verity_image(tree: Path, img: Path) -> tuple[str, int, int]:
    """An ext4 image of `tree` with a verity hash tree appended, as the blob builders
    make it. Returns the root hash, the hash offset and the total size."""
    sh("truncate", "-s", IMAGE_SIZE, str(img))
    sh("mkfs.ext4", "-F", "-q", "-b", "4096", "-L", "rootfs", "-O", "^has_journal",
       "-E", "lazy_itable_init=0,lazy_journal_init=0", "-d", str(tree), str(img))  # fmt: skip
    hash_offset = img.stat().st_size
    out = sh("veritysetup", "format", "--data-block-size=4096", "--hash-block-size=4096",
             f"--hash-offset={hash_offset}", str(img), str(img))  # fmt: skip
    root_hash = next(
        line.split()[-1] for line in out.splitlines() if line.startswith("Root hash")
    )
    return root_hash, hash_offset, img.stat().st_size


def loop_device(backing: Path) -> Path:
    sh("truncate", "-s", str(SLOT_SIZE), str(backing))
    return Path(sh("losetup", "--find", "--show", str(backing)).strip())


def main() -> int:
    WORK.mkdir(exist_ok=True)
    tree = WORK / "tree"
    (tree / "etc").mkdir(parents=True, exist_ok=True)
    (tree / "etc" / "rootfs-version").write_text("9.9.9\n")
    (tree / "big").write_bytes(os.urandom(12 << 20))

    img = WORK / "rootfs.img"
    root_hash, hash_offset, total = build_verity_image(tree, img)
    print(
        f"image {total} bytes, hash tree at {hash_offset}, root hash {root_hash[:16]}…"
    )

    slot = loop_device(WORK / "slot.raw")
    print(f"slot: {slot}")
    try:
        check(
            "device_size reports the loop device's capacity",
            device_size(slot) == SLOT_SIZE,
        )

        with open(img, "rb") as src:
            written = write_image(src, total, slot, digest=sha256(img))
        check("write_image streams the whole image onto the device", written == total)
        check(
            "the bytes on the device are the image's",
            source_digest(slot, total) == sha256(img),
        )
        check("verify_verity passes on the device just written",
              verify_verity(slot, root_hash, hash_offset))  # fmt: skip

        # The case the unit tests can only fake: a slot whose bytes changed under it.
        with open(slot, "r+b") as f:
            f.seek(8 << 20)
            f.write(b"\xde\xad\xbe\xef" * 256)
            f.flush()
            os.fsync(f.fileno())
        try:
            verify_verity(slot, root_hash, hash_offset)
            check(
                "a corrupted slot is refused",
                False,
                "verify_verity returned instead of raising",
            )
        except PartitionDeployError as e:
            check(
                "a corrupted slot is refused", True, str(e).split(":")[-1].strip()[:60]
            )

        with open(img, "rb") as src:
            write_image(src, total, slot, digest=sha256(img))
        check("the slot is whole again", verify_verity(slot, root_hash, hash_offset))

        # A second build of the same tree, and a delta from the first to it.
        (tree / "big2").write_bytes(os.urandom(2 << 20))
        img2 = WORK / "rootfs2.img"
        root_hash2, hash_offset2, total2 = build_verity_image(tree, img2)
        delta = WORK / "delta.tar"
        with open(delta, "wb") as out:
            stats = block_diff.encode(img, img2, out)
        print(f"block diff: {stats.copied} bytes copied, {stats.zero} zero, "
              f"{stats.literal} literal -> {stats.literal_compressed} compressed")  # fmt: skip
        print(f"delta {delta.stat().st_size} bytes for a {total2} byte image "
              f"({delta.stat().st_size * 100 // total2}%)")  # fmt: skip

        check("the delta is recognised as applying to what is on the device",
              delta_applies_to(slot, source_digest_hex=sha256(img), source_size=total))  # fmt: skip

        standby = loop_device(WORK / "slot2.raw")
        try:
            with open(delta, "rb") as stream:
                n = apply_delta(stream, standby, source_dev=slot, source_digest_hex=sha256(img),
                                source_size=total, target_size=total2,
                                target_digest=sha256(img2))  # fmt: skip
            check(
                "apply_delta reconstructs the second image from the first", n == total2
            )
            check("the reconstructed slot verifies against the SECOND root hash",
                  verify_verity(standby, root_hash2, hash_offset2))  # fmt: skip
        finally:
            sh("losetup", "-d", str(standby))

        check("a delta for another version is not claimed to apply",
              not delta_applies_to(slot, source_digest_hex="f" * 64, source_size=total))  # fmt: skip
    finally:
        sh("losetup", "-d", str(slot))

    failed = [name for name, passed in results if not passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
