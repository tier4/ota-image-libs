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
"""pack_artifact: the constraints its docstring promises, on every Python it runs on."""

from __future__ import annotations

import sys
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest

from ota_image_libs.v1.artifact import (
    DEFAULT_TIMESTAMP,
    DIR_PERMISSION,
    FILE_PERMISSION,
)
from ota_image_libs.v1.consts import (
    IMAGE_INDEX_FNAME,
    INDEX_JWT_FNAME,
    OCI_LAYOUT_F_CONTENT,
    OCI_LAYOUT_FNAME,
    RESOURCE_DIR,
)

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11), reason="the packer needs Python 3.11 or newer"
)


@pytest.fixture
def image_root(tmp_path: Path) -> Path:
    root = tmp_path / "image"
    (root / RESOURCE_DIR).mkdir(parents=True)
    (root / IMAGE_INDEX_FNAME).write_text('{"schemaVersion": 2}')
    (root / INDEX_JWT_FNAME).write_text("header.payload.signature")
    (root / OCI_LAYOUT_FNAME).write_text(OCI_LAYOUT_F_CONTENT)
    for name, data in (("b" * 64, b"second"), ("a" * 64, b"first" * 1000)):
        (root / RESOURCE_DIR / name).write_bytes(data)
    return root


def _pack(image_root: Path, out: Path) -> int:
    from ota_image_libs.v1.artifact.packer import pack_artifact

    return pack_artifact(image_root, out, rw_chunk_size=4096)


def test_the_artifact_is_packed_as_the_reader_expects(image_root: Path, tmp_path: Path):
    out = tmp_path / "artifact.zip"
    assert _pack(image_root, out) == 5

    with ZipFile(out) as zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        # The index is the archive's manifest: the first entry, the JWT after it.
        assert names[:2] == [IMAGE_INDEX_FNAME, INDEX_JWT_FNAME]
        assert names[2:] == [
            OCI_LAYOUT_FNAME,
            "blobs/",
            "blobs/sha256/",
            f"{RESOURCE_DIR}/{'a' * 64}",
            f"{RESOURCE_DIR}/{'b' * 64}",
        ]
        for info in infos:
            assert info.compress_type == ZIP_STORED, info.filename
            assert info.date_time == DEFAULT_TIMESTAMP, info.filename
            # The fixed bits are ORed into the source's mode, not set in its place.
            want = DIR_PERMISSION if info.is_dir() else FILE_PERMISSION
            assert info.external_attr >> 16 & want == want, info.filename
        assert zf.read(f"{RESOURCE_DIR}/{'a' * 64}") == b"first" * 1000


def test_the_same_image_packs_to_the_same_bytes(image_root: Path, tmp_path: Path):
    _pack(image_root, tmp_path / "one.zip")
    _pack(image_root, tmp_path / "two.zip")
    assert (tmp_path / "one.zip").read_bytes() == (tmp_path / "two.zip").read_bytes()
