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

"""The bytes half of writing a partition-based payload: what must not be written, and
what must not be believed once it has been."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from ota_image_tools.libs import block_diff
from ota_image_tools.libs.deploy_partition_image import (
    PartitionDeployError,
    apply_delta,
    can_apply_delta,
    check_verity_pairing,
    delta_applies_to,
    device_size,
    source_digest,
    verify_verity,
    verity_params_in,
    write_image,
)

HASH = "a" * 64


def _blob(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- writing --------------------------------------------------------------------------


def test_the_bytes_arrive_and_the_digest_is_checked_on_the_way(tmp_path):
    payload = os.urandom(9000)
    dst = _blob(tmp_path, "dst", b"\0" * 9000)
    with open(_blob(tmp_path, "src", payload), "rb") as src:
        assert write_image(src, len(payload), dst, digest=_sha(payload)) == len(payload)
    assert dst.read_bytes() == payload


def test_an_image_that_does_not_fit_is_refused_before_the_first_byte(tmp_path):
    dst = _blob(tmp_path, "dst", b"\0" * 100)
    before = dst.read_bytes()
    with open(_blob(tmp_path, "src", b"x" * 500), "rb") as src:
        with pytest.raises(PartitionDeployError, match="refusing to write"):
            write_image(src, 500, dst)
    assert dst.read_bytes() == before


def test_a_digest_that_does_not_match_is_an_error(tmp_path):
    payload = b"y" * 4096
    dst = _blob(tmp_path, "dst", b"\0" * 4096)
    with open(_blob(tmp_path, "src", payload), "rb") as src:
        with pytest.raises(PartitionDeployError, match="must not be booted"):
            write_image(src, len(payload), dst, digest=_sha(b"something else"))


def test_a_source_that_ends_early_is_an_error(tmp_path):
    """Not a short write: the length is known before the first byte, so a stream that
    ends early means the archive is truncated."""
    dst = _blob(tmp_path, "dst", b"\0" * 4096)
    with open(_blob(tmp_path, "src", b"z" * 100), "rb") as src:
        with pytest.raises(PartitionDeployError, match="ended after 100 of 4096"):
            write_image(src, 4096, dst)


def test_an_empty_image_is_refused(tmp_path):
    dst = _blob(tmp_path, "dst", b"\0" * 16)
    with open(_blob(tmp_path, "src", b""), "rb") as src:
        with pytest.raises(PartitionDeployError, match="empty"):
            write_image(src, 0, dst)


def test_progress_runs_from_zero_to_a_hundred(tmp_path):
    seen: list[int] = []
    payload = os.urandom(1 << 16)
    dst = _blob(tmp_path, "dst", b"\0" * len(payload))
    with open(_blob(tmp_path, "src", payload), "rb") as src:
        write_image(src, len(payload), dst, progress=seen.append, chunk_size=4096)
    assert seen[0] == 0 and seen[-1] == 100
    assert seen == sorted(seen)


def test_device_size_of_a_missing_path_says_which_path(tmp_path):
    with pytest.raises(PartitionDeployError, match="cannot open"):
        device_size(tmp_path / "not-here")


# --- deltas ---------------------------------------------------------------------------


def test_a_delta_is_matched_against_the_bytes_actually_on_the_device(tmp_path):
    data = os.urandom(8192)
    dev = _blob(tmp_path, "slot", data)
    assert delta_applies_to(dev, source_digest_hex=_sha(data), source_size=len(data))
    assert not delta_applies_to(dev, source_digest_hex=HASH, source_size=len(data))


def test_the_source_digest_covers_only_the_source_size_the_delta_names(tmp_path):
    """A slot is bigger than the image written to it, so the digest is of the image's
    length, not the partition's."""
    data = os.urandom(4096)
    dev = _blob(tmp_path, "slot", data + b"\xff" * 4096)
    assert source_digest(dev, 4096) == _sha(data)


@pytest.mark.skipif(not can_apply_delta(), reason="zstd is not installed")
def test_a_delta_reconstructs_the_target_and_the_result_is_checked(tmp_path):
    source = os.urandom(1 << 16)
    target = source[: 1 << 15] + os.urandom(1 << 15)
    src_file = _blob(tmp_path, "source.img", source)
    tgt_file = _blob(tmp_path, "target.img", target)
    patch = tmp_path / "delta.tar"
    with open(patch, "wb") as out:
        block_diff.encode(src_file, tgt_file, out)
    dst = _blob(tmp_path, "dst", b"\0" * len(target))
    with open(patch, "rb") as stream:
        apply_delta(
            stream,
            dst,
            source_dev=src_file,
            source_digest_hex=_sha(source),
            source_size=len(source),
            target_size=len(target),
            target_digest=_sha(target),
        )
    assert dst.read_bytes() == target


@pytest.mark.skipif(not can_apply_delta(), reason="zstd is not installed")
def test_a_delta_is_refused_when_the_device_is_not_at_the_version_it_patches(tmp_path):
    src_file = _blob(tmp_path, "source.img", os.urandom(4096))
    dst = _blob(tmp_path, "dst", b"\0" * 4096)
    with open(_blob(tmp_path, "delta", b"not a patch"), "rb") as stream:
        with pytest.raises(PartitionDeployError, match="not at the version"):
            apply_delta(
                stream,
                dst,
                source_dev=src_file,
                source_digest_hex=HASH,
                source_size=4096,
                target_size=4096,
                target_digest=HASH,
            )


# --- verity ---------------------------------------------------------------------------


@pytest.fixture
def fake_veritysetup(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "veritysetup").write_text(
        '#!/bin/sh\necho "$@" > "$0.args"\nexit "${VERITYSETUP_EXIT:-0}"\n'
    )
    (bindir / "veritysetup").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    return bindir / "veritysetup.args"


def test_verity_is_checked_the_way_the_initramfs_will_check_it(
    tmp_path, fake_veritysetup
):
    dev = tmp_path / "rootfs_a"
    assert verify_verity(dev, HASH, 4096) is True
    assert fake_veritysetup.read_text().split() == [
        "verify",
        str(dev),
        str(dev),
        HASH,
        "--hash-offset=4096",
    ]


def test_a_partition_that_does_not_verify_names_itself_and_the_hash(
    tmp_path, fake_veritysetup, monkeypatch
):
    monkeypatch.setenv("VERITYSETUP_EXIT", "1")
    with pytest.raises(
        PartitionDeployError, match=f"rootfs_a does not verify against root hash {HASH}"
    ):
        verify_verity(tmp_path / "rootfs_a", HASH, 4096)


def test_without_veritysetup_the_check_is_left_to_the_boot(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert verify_verity(tmp_path / "rootfs_a", HASH, 4096) is False


# --- the pairing of the two blobs -------------------------------------------------------


def test_the_cmdline_grammar_is_the_one_every_platform_reads():
    assert verity_params_in(f"ro verityinfo=/dev/x:{HASH}:1234 quiet") == (HASH, 1234)
    assert verity_params_in("ro quiet") is None


def test_a_boot_blob_from_another_build_is_refused_before_anything_is_written():
    """A pair that cannot boot is a refused update, not a failed trial boot."""
    with pytest.raises(PartitionDeployError, match="not from the same build"):
        check_verity_pairing(f"verityinfo=/dev/x:{'b' * 64}:99", HASH, 1234)


def test_a_boot_blob_with_no_verity_at_all_is_refused_when_the_rootfs_has_one():
    with pytest.raises(PartitionDeployError, match="could not be booted"):
        check_verity_pairing("ro quiet", HASH, 1234)


def test_an_image_without_verity_annotations_has_nothing_to_check_against():
    """The initramfs stays the backstop there; this is not the place to invent a rule."""
    check_verity_pairing("ro quiet", None, None)
    check_verity_pairing("ro quiet", HASH, None)
