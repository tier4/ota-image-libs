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

"""The block diff: what it carries, what it finds, and what it refuses.

An image is blocks, so the tests are built from blocks: a source of distinct random
blocks and targets that keep, move, zero or replace some of them. The reconstruction
runs through the same applier a device uses, `zstd` and all.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
import zstandard

from ota_image_tools.libs import block_diff
from ota_image_tools.libs.block_diff import (
    COPY,
    LITERAL,
    LITERALS_MEMBER,
    OPS_MEMBER,
    ZERO,
    BlockDiffError,
    Op,
    Ops,
    encode,
    open_delta,
)
from ota_image_tools.libs.deploy_partition_image import (
    PartitionDeployError,
    apply_delta,
    can_apply_delta,
    write_compressed_image,
)

BS = block_diff.BLOCK_SIZE
zstd_needed = pytest.mark.skipif(not can_apply_delta(), reason="zstd is not installed")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _block(seed: int) -> bytes:
    return hashlib.sha256(str(seed).encode()).digest() * (BS // 32)


def _image(*seeds: int) -> bytes:
    """One random-looking block per seed; 0 is the zero block."""
    return b"".join(bytes(BS) if s == 0 else _block(s) for s in seeds)


def _encode(
    tmp_path: Path, source: bytes, target: bytes, **kw
) -> tuple[bytes, block_diff.Stats]:
    src = tmp_path / "source.img"
    tgt = tmp_path / "target.img"
    src.write_bytes(source)
    tgt.write_bytes(target)
    out = io.BytesIO()
    stats = encode(src, tgt, out, **kw)
    return out.getvalue(), stats


def _ops_of(delta: bytes) -> Ops:
    with open_delta(io.BytesIO(delta)) as d:
        return d.ops


def _apply(tmp_path: Path, delta: bytes, source: bytes, target: bytes, **kw) -> bytes:
    slot = tmp_path / "slot"
    slot.write_bytes(source + b"\xff" * BS)  # a partition is bigger than its image
    dst = tmp_path / "dst"
    dst.write_bytes(b"\0" * (len(target) + BS))
    apply_delta(
        io.BytesIO(delta),
        dst,
        source_dev=slot,
        source_digest_hex=_sha(source),
        source_size=len(source),
        target_size=len(target),
        target_digest=kw.pop("target_digest", _sha(target)),
        **kw,
    )
    return dst.read_bytes()[: len(target)]


# --- what the encoder finds -----------------------------------------------------------


def test_an_unchanged_region_is_one_copy_and_a_changed_block_travels(tmp_path):
    source = _image(1, 2, 3, 4)
    target = _image(1, 2, 9, 4)
    delta, stats = _encode(tmp_path, source, target)
    ops = _ops_of(delta)
    assert [op.to_json() for op in ops.ops] == [
        [COPY, 2 * BS, 0],
        [LITERAL, BS],
        [COPY, BS, 3 * BS],
    ]
    assert (stats.copied, stats.literal, stats.zero, stats.runs) == (3 * BS, BS, 0, 3)
    assert stats.target_digest == _sha(target) and stats.source_digest == _sha(source)


def test_a_block_that_moved_is_found_where_it_went(tmp_path):
    source = _image(1, 2, 3, 4)
    target = _image(4, 1, 2, 3)
    delta, stats = _encode(tmp_path, source, target)
    assert [op.to_json() for op in _ops_of(delta).ops] == [
        [COPY, BS, 3 * BS],
        [COPY, 3 * BS, 0],
    ]
    assert stats.literal == 0


def test_zero_blocks_travel_as_nothing(tmp_path):
    source = _image(1, 2)
    target = _image(1, 0, 0, 2, 0)
    delta, stats = _encode(tmp_path, source, target)
    assert [op.to_json() for op in _ops_of(delta).ops] == [
        [COPY, BS, 0],
        [ZERO, 2 * BS],
        [COPY, BS, BS],
        [ZERO, BS],
    ]
    assert stats.zero == 3 * BS and stats.literal == 0


def test_the_same_offset_wins_over_an_earlier_duplicate(tmp_path):
    """A source with the same block twice: the copy stays contiguous."""
    source = _image(1, 2, 1, 3)
    target = _image(1, 2, 1, 3)
    delta, _ = _encode(tmp_path, source, target)
    assert [op.to_json() for op in _ops_of(delta).ops] == [[COPY, 4 * BS, 0]]


def test_a_partial_last_block_is_compared_as_it_is(tmp_path):
    source = _image(1, 2) + b"tail"
    same_tail = _image(1, 2) + b"tail"
    other_tail = _image(1, 2) + b"tale"
    delta, _ = _encode(tmp_path, source, same_tail)
    assert [op.to_json() for op in _ops_of(delta).ops] == [[COPY, 2 * BS + 4, 0]]
    delta, stats = _encode(tmp_path, source, other_tail)
    assert [op.to_json() for op in _ops_of(delta).ops] == [
        [COPY, 2 * BS, 0],
        [LITERAL, 4],
    ]
    assert stats.literal == 4


def test_a_target_longer_than_the_source_carries_the_rest(tmp_path):
    source = _image(1)
    target = _image(1, 2, 3)
    delta, stats = _encode(tmp_path, source, target)
    assert [op.to_json() for op in _ops_of(delta).ops] == [
        [COPY, BS, 0],
        [LITERAL, 2 * BS],
    ]
    assert stats.source_size == BS and stats.target_size == 3 * BS


def test_the_delta_is_a_tar_with_the_ops_first(tmp_path):
    delta, _ = _encode(tmp_path, _image(1), _image(2))
    with tarfile.open(fileobj=io.BytesIO(delta)) as tar:
        assert tar.getnames() == [OPS_MEMBER, LITERALS_MEMBER]
        literals = tar.extractfile(LITERALS_MEMBER).read()
    assert zstandard.ZstdDecompressor().decompress(
        literals, max_output_size=BS
    ) == _image(2)


def test_the_literals_are_compressed_with_a_window_a_plain_decoder_accepts(tmp_path):
    delta, _ = _encode(tmp_path, _image(1), _image(2, 3))
    with tarfile.open(fileobj=io.BytesIO(delta)) as tar:
        literals = tar.extractfile(LITERALS_MEMBER).read()
    params = zstandard.get_frame_parameters(literals)
    assert params.window_size <= 1 << block_diff.LITERALS_WINDOW_LOG


def test_an_empty_target_is_refused(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        _encode(tmp_path, _image(1), b"")


# --- the ops ----------------------------------------------------------------------------


def test_ops_round_trip_through_json():
    ops = Ops(BS, 3 * BS, 2 * BS, [Op(COPY, BS, BS), Op(ZERO, BS), Op(LITERAL, BS)])
    assert Ops.from_json(ops.to_json(), target_size=3 * BS, source_size=2 * BS) == ops


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda o: o.update(ops=[[COPY, BS, 0]]), "produce 4096 bytes, not the 8192"),
        (lambda o: o.update(ops=[[COPY, 2 * BS, BS]]), "outside the 8192-byte source"),
        (lambda o: o.update(ops=[["x", 2 * BS]]), "unknown kind 'x'"),
        (lambda o: o.update(ops=[[COPY, 2 * BS]]), "copies from nowhere"),
        (lambda o: o.update(ops=[[ZERO, 2 * BS, 0]]), "stray field"),
        (
            lambda o: o.update(ops=[[LITERAL, 0], [ZERO, 2 * BS]]),
            "not a positive integer",
        ),
        (lambda o: o.update(ops=[]), "not a non-empty list"),
        (lambda o: o.update(block_size=0), "block_size"),
        (
            lambda o: o.update(target_size=BS),
            "reconstructs 4096 bytes but the image is 8192",
        ),
        (
            lambda o: o.update(source_size=BS),
            "applies to 4096 bytes but its descriptor names 8192",
        ),
    ],
)
def test_ops_that_cannot_be_what_they_say_are_refused(change, message):
    obj = {
        "block_size": BS,
        "target_size": 2 * BS,
        "source_size": 2 * BS,
        "ops": [[COPY, 2 * BS, 0]],
    }
    change(obj)
    with pytest.raises(BlockDiffError, match=message):
        Ops.from_json(json.dumps(obj).encode(), target_size=2 * BS, source_size=2 * BS)


def test_ops_that_are_not_json_are_refused():
    with pytest.raises(BlockDiffError, match="not JSON"):
        Ops.from_json(b"{")
    with pytest.raises(BlockDiffError, match="not an object"):
        Ops.from_json(b"[]")


def _tar(members: list[tuple[str, bytes]]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def test_a_delta_whose_members_are_out_of_order_is_refused():
    ops = Ops(BS, BS, BS, [Op(COPY, BS, 0)]).to_json()
    with pytest.raises(BlockDiffError, match="does not start with ops.json"):
        with open_delta(io.BytesIO(_tar([(LITERALS_MEMBER, b""), (OPS_MEMBER, ops)]))):
            pass
    with pytest.raises(BlockDiffError, match="literals.zst does not follow"):
        with open_delta(io.BytesIO(_tar([(OPS_MEMBER, ops)]))):
            pass


def test_something_that_is_not_a_tar_is_refused():
    with pytest.raises(BlockDiffError, match="not a readable tar"):
        with open_delta(io.BytesIO(b"not a tar at all" * 100)):
            pass


# --- applying -----------------------------------------------------------------------


@zstd_needed
def test_a_rebuild_is_reconstructed_from_the_slot_and_the_literals(tmp_path):
    source = _image(1, 2, 3, 4, 0, 5)
    target = _image(5, 1, 9, 0, 0, 4) + b"tail"
    delta, _ = _encode(tmp_path, source, target)
    assert _apply(tmp_path, delta, source, target) == target


@zstd_needed
def test_the_source_is_read_where_it_lies_and_never_copied(tmp_path, monkeypatch):
    """Nothing is staged: the applier must not need free space for the source."""
    import shutil

    monkeypatch.setattr(
        shutil, "disk_usage", lambda p: (_ for _ in ()).throw(AssertionError("staged"))
    )
    source = _image(1, 2)
    target = _image(2, 1)
    delta, _ = _encode(tmp_path, source, target)
    assert _apply(tmp_path, delta, source, target) == target


@zstd_needed
def test_a_reconstruction_that_is_not_the_image_is_refused(tmp_path):
    source = _image(1, 2)
    target = _image(1, 3)
    delta, _ = _encode(tmp_path, source, target)
    with pytest.raises(
        PartitionDeployError, match="hashes to .*, not the .* its descriptor says"
    ):
        _apply(tmp_path, delta, source, target, target_digest="a" * 64)


@zstd_needed
def test_a_delta_for_another_image_size_is_refused_before_writing(tmp_path):
    source = _image(1, 2)
    target = _image(1, 3)
    delta, _ = _encode(tmp_path, source, target)
    dst = tmp_path / "dst"
    dst.write_bytes(b"\0" * 4 * BS)
    slot = tmp_path / "slot"
    slot.write_bytes(source)
    with pytest.raises(
        PartitionDeployError, match="reconstructs 8192 bytes but the image is 12288"
    ):
        apply_delta(
            io.BytesIO(delta),
            dst,
            source_dev=slot,
            source_digest_hex=_sha(source),
            source_size=len(source),
            target_size=3 * BS,
            target_digest=_sha(target),
        )
    assert dst.read_bytes() == b"\0" * 4 * BS


def _delta_with_literals(ops: Ops, literals: bytes) -> bytes:
    return _tar(
        [(OPS_MEMBER, ops.to_json()), (LITERALS_MEMBER, zstandard.compress(literals))]
    )


@zstd_needed
def test_a_literal_stream_that_ends_short_is_refused(tmp_path):
    source = _image(1)
    target = _image(2, 3)
    ops = Ops(BS, 2 * BS, BS, [Op(LITERAL, 2 * BS)])
    delta = _delta_with_literals(ops, _block(2))  # one block, two needed
    with pytest.raises(
        PartitionDeployError, match="literal stream ended 4096 bytes short"
    ):
        _apply(tmp_path, delta, source, target)


@zstd_needed
def test_literal_bytes_the_runs_do_not_use_are_refused(tmp_path):
    source = _image(1)
    target = _image(2)
    ops = Ops(BS, BS, BS, [Op(LITERAL, BS)])
    delta = _delta_with_literals(ops, _block(2) + b"extra")
    with pytest.raises(
        PartitionDeployError, match="more literal bytes than its runs use"
    ):
        _apply(tmp_path, delta, source, target)


@zstd_needed
def test_literals_that_are_not_zstd_are_refused(tmp_path):
    source = _image(1)
    target = _image(2)
    ops = Ops(BS, BS, BS, [Op(LITERAL, BS)])
    delta = _tar([(OPS_MEMBER, ops.to_json()), (LITERALS_MEMBER, b"not zstd" * 512)])
    with pytest.raises(PartitionDeployError):
        _apply(tmp_path, delta, source, target)


@zstd_needed
def test_a_source_that_does_not_hold_what_the_delta_names_is_refused(tmp_path):
    source = _image(1, 2)
    target = _image(2, 1)
    delta, _ = _encode(tmp_path, source, target)
    slot = tmp_path / "slot"
    slot.write_bytes(_image(1, 3))
    dst = tmp_path / "dst"
    dst.write_bytes(b"\0" * 2 * BS)
    with pytest.raises(PartitionDeployError, match="not at the version"):
        apply_delta(
            io.BytesIO(delta),
            dst,
            source_dev=slot,
            source_digest_hex=_sha(source),
            source_size=len(source),
            target_size=len(target),
            target_digest=_sha(target),
        )


# --- compressed images ------------------------------------------------------------------


@zstd_needed
def test_a_compressed_image_is_decoded_on_the_way_to_the_partition(tmp_path):
    image = _image(1, 2, 3)
    dst = tmp_path / "dst"
    dst.write_bytes(b"\0" * 4 * BS)
    written = write_compressed_image(
        io.BytesIO(zstandard.compress(image)), len(image), dst, digest=_sha(image)
    )
    assert written == len(image)
    assert dst.read_bytes()[: len(image)] == image


@zstd_needed
def test_a_compressed_image_that_is_cut_short_is_refused(tmp_path):
    image = _image(1, 2, 3)
    compressed = zstandard.compress(image)
    dst = tmp_path / "dst"
    dst.write_bytes(b"\0" * 4 * BS)
    with pytest.raises(PartitionDeployError):
        write_compressed_image(
            io.BytesIO(compressed[:-20]), len(image), dst, digest=_sha(image)
        )


@zstd_needed
def test_a_compressed_image_that_decodes_to_something_else_is_refused(tmp_path):
    image = _image(1, 2, 3)
    dst = tmp_path / "dst"
    dst.write_bytes(b"\0" * 4 * BS)
    with pytest.raises(PartitionDeployError, match="its descriptor says"):
        write_compressed_image(
            io.BytesIO(zstandard.compress(image)), len(image), dst, digest="b" * 64
        )


def test_without_zstd_the_applier_says_so(tmp_path, monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(PartitionDeployError, match="no zstd"):
        apply_delta(
            io.BytesIO(b""),
            tmp_path / "dst",
            source_dev=tmp_path / "slot",
            source_digest_hex="a" * 64,
            source_size=BS,
            target_size=BS,
            target_digest="a" * 64,
        )
    with pytest.raises(PartitionDeployError, match="no zstd"):
        write_compressed_image(io.BytesIO(b""), BS, tmp_path / "dst")
