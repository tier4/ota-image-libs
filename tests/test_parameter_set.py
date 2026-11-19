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
"""Tests for the parameter set: schemas, the layer, and laying it over a base tree."""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import tarfile
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest
import zstandard
from pydantic import ValidationError

from ota_image_libs.common.oci_spec import Sha256Digest
from ota_image_libs.v1.annotation_keys import (
    BUILD_TOOL_VERSION,
    OTA_RELEASE_KEY,
    PARAMETER_SET_VERSION,
    PLATFORM_ECU,
)
from ota_image_libs.v1.consts import IMAGE_INDEX_FNAME, RESOURCE_DIR
from ota_image_libs.v1.image_index.schema import ImageIndex
from ota_image_libs.v1.image_manifest.schema import (
    ImageIdentifier,
    ImageManifest,
    OTAReleaseKey,
)
from ota_image_libs.v1.media_types import (
    IMAGE_MANIFEST,
    OCI_EMPTY_JSON,
    OCI_LAYER_TAR_ZSTD,
    PARAMETER_SET_ARTIFACT,
    PARAMETER_SET_CONFIG_JSON,
)
from ota_image_libs.v1.parameter_set import layer as layer_module
from ota_image_libs.v1.parameter_set.layer import (
    MAX_TAR_TRAILER,
    OPAQUE_WHITEOUT,
    READ_SIZE,
    ParameterLayerInvalid,
    read_parameter_layer,
    write_parameter_layer,
)
from ota_image_libs.v1.parameter_set.schema import (
    EmptyDescriptor,
    ParameterLayerDescriptor,
    ParameterSetConfig,
    ParameterSetFileEntry,
    ParameterSetManifest,
)
from ota_image_libs.v1.parameter_set.slots import (
    ParameterSlot,
    ParameterSlotRef,
    check_slots,
    check_slots_disjoint,
    check_slots_in_tree,
)
from ota_image_libs.v1.update_agent_package.schema import EMPTY_JSON
from ota_image_tools.cmds.list_image import _list_image_from_artifact, _render_output
from ota_image_tools.cmds.lookup_image import _lookup_image_from_artifact
from ota_image_tools.libs.deploy_parameter_set import (
    ParameterSetInvalid,
    ParameterSetNotApplicable,
    open_parameter_set,
    overlay_parameter_set,
)

SLOT_PATH = "/opt/autoware/vehicle/sample_vehicle/individual_params"
OTHER_SLOT_PATH = "/opt/autoware/vehicle/sample_vehicle/launch"
APPLY = "/opt/autoware/vehicle/sample_vehicle/apply.sh"
SLOT = ParameterSlot(name="individual_params", path=SLOT_PATH, apply=APPLY)
OTHER_SLOT = ParameterSlot(name="launch", path=OTHER_SLOT_PATH, apply="reboot")
ECU = "autoware"
IMAGE_ID = ImageIdentifier(ECU, OTAReleaseKey.dev)
MANIFEST_ANNOTATIONS = {
    PLATFORM_ECU: ECU,
    OTA_RELEASE_KEY: "dev",
    PARAMETER_SET_VERSION: "2026.10.29-1",
}


def make_tree(root: Path, slot: ParameterSlotRef = SLOT) -> Path:
    """A slot's directory as a set carries it: files at two levels."""
    _slot_dir = root / slot.relpath
    (_slot_dir / "default").mkdir(parents=True)
    (_slot_dir / "default" / "vehicle.param.yaml").write_text("max_speed: 10\n")
    (_slot_dir / "vehicle-0042").mkdir()
    (_slot_dir / "vehicle-0042" / "vehicle.param.yaml").write_text("max_speed: 12\n")
    (_slot_dir / "README").write_text("parameters\n")
    return root


def layer_bytes(root: Path, slots=(SLOT,)) -> tuple[bytes, object]:
    _out = io.BytesIO()
    _info = write_parameter_layer(root, list(slots), _out)
    return _out.getvalue(), _info


def raw_tar(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    """A hand-made tar, with its end-of-archive marker and record padding."""
    _raw = io.BytesIO()
    with tarfile.open(fileobj=_raw, mode="w", format=tarfile.PAX_FORMAT) as _tar:
        for _ti, _data in members:
            _tar.addfile(_ti, io.BytesIO(_data) if _data is not None else None)
    return _raw.getvalue()


def zstd_tar(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    """A hand-made layer, for what the writer would never write."""
    return zstandard.ZstdCompressor().compress(raw_tar(members))


def tar_members_end(raw: bytes) -> int:
    """Where the end-of-archive marker of `raw` starts."""
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as _tar:
        _tar.getmembers()
        return _tar.offset


def member(
    name: str, type_=tarfile.REGTYPE, data: bytes = b"", mode: int = 0o644, **kw
):
    _ti = tarfile.TarInfo(name)
    _ti.type = type_
    _ti.mode = mode
    _ti.size = len(data) if type_ == tarfile.REGTYPE else 0
    for _k, _v in kw.items():
        setattr(_ti, _k, _v)
    return (_ti, data if type_ == tarfile.REGTYPE else None)


def slot_members(slot: ParameterSlotRef = SLOT):
    return [
        member(slot.relpath, tarfile.DIRTYPE, mode=0o755),
        member(f"{slot.relpath}/{OPAQUE_WHITEOUT}"),
    ]


#
# ------ slots ------ #
#


class TestSlots:
    def test_a_slot_says_how_a_change_to_it_takes_effect(self):
        _slot = ParameterSlot.model_validate(
            {"name": "individual_params", "path": SLOT_PATH, "apply": "reboot"}
        )
        assert _slot.relpath == SLOT_PATH[1:]
        with pytest.raises(ValidationError):
            ParameterSlot.model_validate({"name": "s", "path": SLOT_PATH})

    @pytest.mark.parametrize(
        "path",
        ("relative/path", "/", "/opt/../etc", "/opt/x/", "//opt", "/opt/./x", "/a\nb"),
    )
    def test_a_slot_path_is_absolute_and_normalized(self, path):
        with pytest.raises(ValidationError):
            ParameterSlotRef(name="s", path=path)

    @pytest.mark.parametrize("apply", ("restart.sh", "/opt/../bin/x", ""))
    def test_apply_is_an_absolute_path_or_reboot(self, apply):
        with pytest.raises(ValidationError):
            ParameterSlot(name="s", path=SLOT_PATH, apply=apply)

    @pytest.mark.parametrize("path", ("/opt/.wh.params", "/opt/.wh..wh..opq/x"))
    def test_a_slot_path_has_no_whiteout_name(self, path):
        """The reader would take the slot's directory for a whiteout."""
        with pytest.raises(ValidationError, match="whiteout"):
            ParameterSlotRef(name="s", path=path)

    @pytest.mark.parametrize("name", ("", "-x", "a b", "x" * 65))
    def test_a_slot_name_is_a_plain_name(self, name):
        with pytest.raises(ValidationError):
            ParameterSlotRef(name=name, path=SLOT_PATH)

    def test_slots_are_disjoint(self):
        check_slots_disjoint("t", [SLOT, OTHER_SLOT])
        with pytest.raises(ValueError, match="unique"):
            check_slots_disjoint(
                "t", [SLOT, ParameterSlotRef(name=SLOT.name, path="/x")]
            )
        with pytest.raises(ValueError, match="inside"):
            check_slots_disjoint(
                "t", [SLOT, ParameterSlotRef(name="inner", path=f"{SLOT_PATH}/default")]
            )
        with pytest.raises(ValueError, match="inside"):
            check_slots_disjoint(
                "t", [SLOT, ParameterSlotRef(name="same", path=SLOT_PATH)]
            )
        # a path that only starts with the same letters is another directory
        check_slots_disjoint(
            "t", [SLOT, ParameterSlotRef(name="sibling", path=f"{SLOT_PATH}2")]
        )

    @pytest.mark.parametrize(
        "path",
        (
            "/opt/ota",
            "/opt/ota/client",
            "/boot/grub",
            "/usr/share",
            "/usr/share/ota",
            "/etc",
        ),
    )
    def test_a_slot_is_not_over_what_the_consumer_reads(self, path):
        with pytest.raises(ValueError, match="reads for itself"):
            check_slots("t", [ParameterSlot(name="s", path=path, apply="reboot")])

    @pytest.mark.parametrize(
        "path", ("/opt/otaclient", "/bootstrap", "/usr/share/otafoo", "/etc/fstab.d")
    )
    def test_a_slot_next_to_what_the_consumer_reads(self, path):
        check_slots("t", [ParameterSlot(name="s", path=path, apply="reboot")])

    def test_a_slots_apply_is_not_inside_a_slot(self):
        """What runs is the base's: inside a slot, a set would replace it."""
        with pytest.raises(ValueError, match="which a set replaces"):
            check_slots(
                "t",
                [
                    ParameterSlot(
                        name="s", path=SLOT_PATH, apply=f"{SLOT_PATH}/apply.sh"
                    )
                ],
            )
        with pytest.raises(ValueError, match="which a set replaces"):
            check_slots(
                "t",
                [
                    ParameterSlot(
                        name="a", path=SLOT_PATH, apply=f"{OTHER_SLOT_PATH}/x"
                    ),
                    ParameterSlot(name="b", path=OTHER_SLOT_PATH, apply="reboot"),
                ],
            )
        check_slots("t", [SLOT, OTHER_SLOT])


#
# ------ config and manifest ------ #
#

DIFF_ID = "sha256:" + "1" * 64


def config_dict(**kw) -> dict:
    _d = {
        "schemaVersion": 1,
        "mediaType": PARAMETER_SET_CONFIG_JSON,
        "name": "sample_vehicle_params",
        "version": "2026.10.29-1",
        "slots": [{"name": SLOT.name, "path": SLOT.path, "apply": APPLY}],
        "diff_ids": [DIFF_ID],
        "files": [
            {
                "path": f"{SLOT.relpath}/default/vehicle.param.yaml",
                "size": 14,
                "digest": "sha256:" + "2" * 64,
            }
        ],
    }
    _d.update(kw)
    return _d


def manifest_dict(*, empty: bool = False) -> dict:
    _layer = (
        {
            "mediaType": OCI_EMPTY_JSON,
            "digest": f"sha256:{sha256(EMPTY_JSON).hexdigest()}",
            "size": 2,
        }
        if empty
        else {
            "mediaType": OCI_LAYER_TAR_ZSTD,
            "digest": "sha256:" + "3" * 64,
            "size": 18432,
        }
    )
    return {
        "schemaVersion": 2,
        "mediaType": IMAGE_MANIFEST,
        "artifactType": PARAMETER_SET_ARTIFACT,
        "config": {
            "mediaType": PARAMETER_SET_CONFIG_JSON,
            "digest": "sha256:" + "4" * 64,
            "size": 640,
        },
        "layers": [_layer],
        "annotations": MANIFEST_ANNOTATIONS,
    }


class TestConfig:
    def test_a_config_names_its_slots_and_their_diff_id(self):
        _config = ParameterSetConfig.parse_metafile(json.dumps(config_dict()))
        assert _config.slot(SLOT.name) == SLOT
        assert not _config.is_empty
        assert str(_config.diff_ids[0]) == DIFF_ID
        assert (
            json.loads(_config.export_metafile())["mediaType"]
            == PARAMETER_SET_CONFIG_JSON
        )

    def test_an_empty_set_fills_no_slot_and_has_no_diff_id(self):
        _config = ParameterSetConfig.parse_metafile(
            json.dumps(config_dict(slots=[], diff_ids=[], files=[]))
        )
        assert _config.is_empty

    @pytest.mark.parametrize(
        "change",
        (
            pytest.param({"diff_ids": []}, id="slots_without_diff_id"),
            pytest.param({"diff_ids": [DIFF_ID, DIFF_ID]}, id="two_diff_ids"),
            pytest.param({"slots": [], "files": []}, id="diff_id_without_slots"),
            pytest.param(
                {"files": [{"path": "etc/passwd", "size": 1, "digest": DIFF_ID}]},
                id="file_outside_the_slots",
            ),
            pytest.param(
                {
                    "files": [
                        {"path": f"{SLOT.relpath}/../x", "size": 1, "digest": DIFF_ID}
                    ]
                },
                id="file_path_not_normalized",
            ),
            pytest.param(
                {"files": [config_dict()["files"][0]] * 2}, id="file_listed_twice"
            ),
            pytest.param({"version": "1 0"}, id="version_with_a_space"),
            pytest.param({"name": ""}, id="no_name"),
            pytest.param(
                {
                    "slots": [
                        {"name": "a", "path": "/x", "apply": "reboot"},
                        {"name": "b", "path": "/x/y", "apply": "reboot"},
                    ]
                },
                id="nested_slots",
            ),
            pytest.param(
                {"slots": [{"name": SLOT.name, "path": SLOT.path}]},
                id="slot_without_apply",
            ),
            pytest.param(
                {
                    "slots": [
                        {
                            "name": SLOT.name,
                            "path": SLOT.path,
                            "apply": f"{SLOT_PATH}/a",
                        }
                    ]
                },
                id="apply_inside_the_slot",
            ),
            pytest.param(
                {"slots": [{"name": "s", "path": "/opt/ota/x", "apply": "reboot"}]},
                id="slot_over_the_consumers_own",
            ),
        ),
    )
    def test_a_config_that_does_not_add_up_is_refused(self, change):
        with pytest.raises(ValidationError):
            ParameterSetConfig.parse_metafile(json.dumps(config_dict(**change)))

    def test_the_files_listed_are_the_layers(self):
        _config = ParameterSetConfig.parse_metafile(json.dumps(config_dict()))
        assert _config.files is not None
        _listed = _config.files[0]
        _config.check_files([_listed])

        _other_digest = _listed.model_copy(update={"digest": Sha256Digest("9" * 64)})
        _other_size = _listed.model_copy(update={"size": _listed.size + 1})
        _extra = ParameterSetFileEntry(
            path=f"{SLOT.relpath}/extra", size=0, digest=Sha256Digest("8" * 64)
        )
        for _held in ([_other_digest], [_other_size], [_listed, _extra], []):
            with pytest.raises(ValueError, match="other files"):
                _config.check_files(_held)

    def test_files_left_out_are_not_checked_and_an_empty_list_is(self):
        _raw = config_dict()
        del _raw["files"]
        _without = ParameterSetConfig.parse_metafile(json.dumps(_raw))
        assert _without.files is None
        assert "files" not in json.loads(_without.export_metafile())
        _without.check_files([])

        _empty = ParameterSetConfig.parse_metafile(json.dumps(config_dict(files=[])))
        _empty.check_files([])
        _a_file = ParameterSetFileEntry(
            path=f"{SLOT.relpath}/a", size=1, digest=Sha256Digest("8" * 64)
        )
        with pytest.raises(ValueError, match="other files"):
            _empty.check_files([_a_file])


class TestManifest:
    def test_a_manifest_carries_its_artifact_type_and_names_no_base(self):
        _manifest = ParameterSetManifest.parse_metafile(json.dumps(manifest_dict()))
        assert isinstance(_manifest.layer, ParameterLayerDescriptor)
        assert _manifest.version == "2026.10.29-1"
        assert _manifest.image_identifier == IMAGE_ID

        _exported = json.loads(_manifest.export_metafile())
        assert _exported["artifactType"] == PARAMETER_SET_ARTIFACT
        assert "subject" not in _exported
        assert (
            ParameterSetManifest.parse_metafile(_manifest.export_metafile())
            == _manifest
        )

    def test_an_empty_set_carries_the_empty_descriptor(self):
        _manifest = ParameterSetManifest.parse_metafile(
            json.dumps(manifest_dict(empty=True))
        )
        assert _manifest.layer is None
        assert isinstance(_manifest.layers[0], EmptyDescriptor)

    @pytest.mark.parametrize("layers", (0, 2))
    def test_a_set_has_exactly_one_layer(self, layers):
        _raw = manifest_dict()
        _raw["layers"] = _raw["layers"] * layers
        with pytest.raises(ValidationError, match="exactly one layer"):
            ParameterSetManifest.parse_metafile(json.dumps(_raw))

    def test_the_manifest_and_its_config_agree(self):
        _manifest = ParameterSetManifest.parse_metafile(json.dumps(manifest_dict()))
        _config = ParameterSetConfig.parse_metafile(json.dumps(config_dict()))
        _manifest.check_config(_config)

        with pytest.raises(ValueError, match="version"):
            _manifest.check_config(
                ParameterSetConfig.parse_metafile(json.dumps(config_dict(version="2")))
            )
        _empty = ParameterSetConfig.parse_metafile(
            json.dumps(config_dict(slots=[], diff_ids=[], files=[]))
        )
        with pytest.raises(ValueError, match="empty"):
            _manifest.check_config(_empty)

        _empty_manifest = ParameterSetManifest.parse_metafile(
            json.dumps(manifest_dict(empty=True))
        )
        _empty_manifest.check_config(_empty)
        with pytest.raises(ValueError, match="empty"):
            _empty_manifest.check_config(_config)


class TestIndex:
    def index_dict(self, entry: dict) -> dict:
        return {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [entry],
            "annotations": {BUILD_TOOL_VERSION: "test"},
        }

    def entry(self, **kw) -> dict:
        _e = {
            "mediaType": IMAGE_MANIFEST,
            "artifactType": PARAMETER_SET_ARTIFACT,
            "digest": "sha256:" + "5" * 64,
            "size": 900,
            "annotations": MANIFEST_ANNOTATIONS,
        }
        _e.update(kw)
        return _e

    def test_an_index_lists_a_parameter_set_as_the_ecus_payload(self):
        _index = ImageIndex.parse_metafile(json.dumps(self.index_dict(self.entry())))
        _found = _index.find_parameter_set(IMAGE_ID)
        assert isinstance(_found, ParameterSetManifest.Descriptor)
        assert _found.annotations.parameter_set_version == "2026.10.29-1"
        assert _index.find_image(IMAGE_ID) is None
        assert _index.find_partition_image(IMAGE_ID) is None
        assert _index.image_identifiers == [IMAGE_ID]
        assert _index.image_resource_table is None

        _exported = json.loads(_index.export_metafile())
        assert _exported["manifests"][0]["artifactType"] == PARAMETER_SET_ARTIFACT

    def test_a_parameter_image_carries_parameter_sets_only(self):
        _index = ImageIndex.parse_metafile(json.dumps(self.index_dict(self.entry())))
        _base = ImageManifest.Descriptor.model_validate(
            {
                "mediaType": IMAGE_MANIFEST,
                "digest": "sha256:" + "6" * 64,
                "size": 1,
                "annotations": {PLATFORM_ECU: "perception", OTA_RELEASE_KEY: "dev"},
            }
        )
        with pytest.raises(ValueError, match="parameter sets only"):
            _index.add_image(_base)

        # the sets of other ECUs go in
        _index.add_image(
            ParameterSetManifest.Descriptor.model_validate(
                {
                    **self.entry(),
                    "annotations": {**MANIFEST_ANNOTATIONS, PLATFORM_ECU: "perception"},
                }
            )
        )
        assert len(_index.image_identifiers) == 2

        _raw = self.entry()
        del _raw["artifactType"]
        _base_index = ImageIndex.parse_metafile(json.dumps(self.index_dict(_raw)))
        _set = ParameterSetManifest.Descriptor.model_validate(
            {
                **self.entry(),
                "annotations": {**MANIFEST_ANNOTATIONS, PLATFORM_ECU: "perception"},
            }
        )
        with pytest.raises(ValueError, match="parameter sets only"):
            _base_index.add_image(_set)

    def test_an_entry_without_artifact_type_is_a_file_based_payload(self):
        _raw = self.entry()
        del _raw["artifactType"]
        _index = ImageIndex.parse_metafile(json.dumps(self.index_dict(_raw)))
        assert _index.find_parameter_set(IMAGE_ID) is None
        assert _index.find_image(IMAGE_ID) is not None


#
# ------ the layer ------ #
#


class TestLayer:
    def test_the_layer_round_trips_and_is_deterministic(self, tmp_path: Path):
        _root = make_tree(tmp_path / "tree")
        _blob, _written = layer_bytes(_root)
        assert layer_bytes(_root)[0] == _blob, "the same tree makes the same layer"
        os.utime(_root / SLOT.relpath / "README", (1, 1))
        assert layer_bytes(_root)[0] == _blob, "times are not in the layer"

        _out = tmp_path / "out"
        _out.mkdir()
        _read = read_parameter_layer(
            io.BytesIO(_blob),
            [SLOT],
            extract_to=_out,
            blob_digest=_written.digest,
            diff_id=_written.diff_id,
        )
        assert _read.diff_id == _written.diff_id
        assert _read.files == _written.files
        assert len(_read.files) == 3
        assert _read.files_size == _written.files_size
        assert (
            _out / SLOT.relpath / "vehicle-0042" / "vehicle.param.yaml"
        ).read_text() == ("max_speed: 12\n")
        assert not (_out / SLOT.relpath / OPAQUE_WHITEOUT).exists()

        with tarfile.open(
            fileobj=zstandard.ZstdDecompressor().stream_reader(io.BytesIO(_blob)),
            mode="r|",
        ) as _tar:
            _members = list(_tar)
        assert [_m.name for _m in _members[:2]] == [
            SLOT.relpath,
            f"{SLOT.relpath}/{OPAQUE_WHITEOUT}",
        ]
        assert {(_m.uid, _m.gid, _m.mtime) for _m in _members} == {(0, 0, 0)}

    def test_the_order_slots_are_named_in_does_not_change_the_layer(
        self, tmp_path: Path
    ):
        _root = make_tree(make_tree(tmp_path / "tree"), OTHER_SLOT)
        assert (
            layer_bytes(_root, (OTHER_SLOT, SLOT))[0]
            == layer_bytes(_root, (SLOT, OTHER_SLOT))[0]
        )

    def test_the_writer_refuses_a_slot_behind_a_link(self, tmp_path: Path):
        """The tree's link would be followed on the build machine."""
        _elsewhere = make_tree(tmp_path / "elsewhere")
        _root = tmp_path / "tree"
        _root.mkdir()
        (_root / "opt").symlink_to(_elsewhere / "opt")
        with pytest.raises(ParameterLayerInvalid, match="behind a symbolic link"):
            layer_bytes(_root)

    def test_the_reader_unpacks_into_an_empty_target_only(self, tmp_path: Path):
        """What is there already could be a link out of the target."""
        _blob, _ = layer_bytes(make_tree(tmp_path / "tree"))
        _out = tmp_path / "out"
        _victim = tmp_path / "victim"
        _victim.write_text("untouched\n")
        _readme = _out / SLOT.relpath / "README"
        _readme.parent.mkdir(parents=True)
        _readme.symlink_to(_victim)
        with pytest.raises(ValueError, match="not empty"):
            read_parameter_layer(io.BytesIO(_blob), [SLOT], extract_to=_out)
        assert _victim.read_text() == "untouched\n"

        # a target that is not there yet is made
        read_parameter_layer(io.BytesIO(_blob), [SLOT], extract_to=tmp_path / "new")
        assert (tmp_path / "new" / SLOT.relpath / "README").is_file()

    def test_a_short_write_is_written_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """os.write may write less than asked, as a filesystem running out of room
        does: what was hashed must be what is on disk."""
        _root = make_tree(tmp_path / "tree")
        _data = os.urandom(300_000)
        (_root / SLOT.relpath / "big").write_bytes(_data)
        _blob, _ = layer_bytes(_root)

        _real_write = os.write

        def _short_write(fd: int, data) -> int:
            return _real_write(fd, bytes(data[: max(1, len(data) // 3)]))

        _out = tmp_path / "out"
        monkeypatch.setattr(layer_module.os, "write", _short_write)
        read_parameter_layer(io.BytesIO(_blob), [SLOT], extract_to=_out)
        monkeypatch.undo()
        assert (_out / SLOT.relpath / "big").read_bytes() == _data

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads any directory")
    def test_the_writer_refuses_a_directory_it_cannot_read(self, tmp_path: Path):
        """Its files would be left out of the layer without a word."""
        _root = make_tree(tmp_path / "tree")
        _locked = _root / SLOT.relpath / "default"
        _locked.chmod(0o300)
        try:
            with pytest.raises(ParameterLayerInvalid, match="cannot read"):
                layer_bytes(_root)
        finally:
            _locked.chmod(0o755)

    def test_a_directory_without_write_permission_is_filled(self, tmp_path: Path):
        _root = make_tree(tmp_path / "tree")
        _ro = _root / SLOT.relpath / "default"
        _ro.chmod(0o555)
        try:
            _blob, _ = layer_bytes(_root)
            _out = tmp_path / "out"
            read_parameter_layer(io.BytesIO(_blob), [SLOT], extract_to=_out)
            _unpacked = _out / SLOT.relpath / "default"
            assert (_unpacked / "vehicle.param.yaml").read_text() == "max_speed: 10\n"
            assert stat.S_IMODE(_unpacked.stat().st_mode) == 0o555
        finally:
            _ro.chmod(0o755)
            if (tmp_path / "out").exists():
                (tmp_path / "out" / SLOT.relpath / "default").chmod(0o755)

    def test_two_slots_in_one_layer(self, tmp_path: Path):
        _root = make_tree(make_tree(tmp_path / "tree"), OTHER_SLOT)
        _blob, _ = layer_bytes(_root, (OTHER_SLOT, SLOT))
        _info = read_parameter_layer(io.BytesIO(_blob), [SLOT, OTHER_SLOT])
        assert len(_info.files) == 6

    def test_the_permission_bits_are_kept(self, tmp_path: Path):
        _root = make_tree(tmp_path / "tree")
        os.chmod(_root / SLOT.relpath / "README", 0o600)
        _blob, _ = layer_bytes(_root)
        _out = tmp_path / "out"
        _out.mkdir()
        read_parameter_layer(io.BytesIO(_blob), [SLOT], extract_to=_out)
        assert stat.S_IMODE((_out / SLOT.relpath / "README").stat().st_mode) == 0o600

    @pytest.mark.parametrize(
        "spoil",
        (
            pytest.param(lambda p: (p / "link").symlink_to("README"), id="symlink"),
            pytest.param(lambda p: os.mkfifo(p / "fifo"), id="fifo"),
            pytest.param(
                lambda p: (p / ".wh.README").write_text(""), id="whiteout_name"
            ),
            pytest.param(lambda p: os.chmod(p / "README", 0o4755), id="setuid"),
        ),
    )
    def test_the_writer_refuses_what_a_set_does_not_hold(self, tmp_path: Path, spoil):
        _root = make_tree(tmp_path / "tree")
        spoil(_root / SLOT.relpath)
        with pytest.raises(ParameterLayerInvalid):
            layer_bytes(_root)

    def test_the_writer_refuses_a_missing_slot(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            layer_bytes(tmp_path)

    @pytest.mark.parametrize(
        "members, refusal",
        (
            pytest.param(
                [
                    *slot_members(),
                    member(f"{SLOT.relpath}/l", tarfile.SYMTYPE, linkname="x"),
                ],
                "only regular files and directories",
                id="symlink",
            ),
            pytest.param(
                [
                    *slot_members(),
                    member(f"{SLOT.relpath}/a", data=b"a"),
                    member(
                        f"{SLOT.relpath}/h",
                        tarfile.LNKTYPE,
                        linkname=f"{SLOT.relpath}/a",
                    ),
                ],
                "only regular files and directories",
                id="hardlink",
            ),
            pytest.param(
                [*slot_members(), member(f"{SLOT.relpath}/d", tarfile.CHRTYPE)],
                "only regular files and directories",
                id="device",
            ),
            pytest.param(
                [*slot_members(), member("etc/passwd", data=b"x")],
                "not in one of the set's slots",
                id="outside",
            ),
            pytest.param(
                [*slot_members(), member(f"{SLOT.relpath}/../../x", data=b"x")],
                "not a normalized path",
                id="dot_dot",
            ),
            pytest.param(
                [
                    *slot_members(),
                    member(f"{SLOT.relpath}/..", tarfile.DIRTYPE, mode=0o755),
                    member(f"{SLOT.relpath}/../evil", data=b"x"),
                ],
                "not a normalized path",
                id="dot_dot_after_its_dir",
            ),
            pytest.param(
                [*slot_members(), member(f"/{SLOT.relpath}/x")],
                "not a normalized path",
                id="absolute",
            ),
            pytest.param(
                [*slot_members(), member(f"{SLOT.relpath}/.wh.gone")],
                "the only whiteout",
                id="other_whiteout",
            ),
            pytest.param(
                [
                    *slot_members(),
                    member(f"{SLOT.relpath}/d", tarfile.DIRTYPE, mode=0o755),
                    member(f"{SLOT.relpath}/d/{OPAQUE_WHITEOUT}"),
                ],
                "the only whiteout",
                id="opaque_below_the_slot",
            ),
            pytest.param(
                [member(SLOT.relpath, tarfile.DIRTYPE, mode=0o755)],
                "lacks its directory or its opaque whiteout",
                id="no_opaque",
            ),
            pytest.param(
                [member(f"{SLOT.relpath}/{OPAQUE_WHITEOUT}")],
                "lacks its directory or its opaque whiteout",
                id="no_slot_dir",
            ),
            pytest.param(
                [
                    *slot_members(),
                    member(f"{SLOT.relpath}/x"),
                    member(f"{SLOT.relpath}/x"),
                ],
                "appears twice",
                id="twice",
            ),
            pytest.param(
                [*slot_members(), member(f"{SLOT.relpath}/x", mode=0o4755)],
                "setuid",
                id="setuid",
            ),
            pytest.param(
                [*slot_members(), member(f"{SLOT.relpath}/d/x")],
                "comes before its directory",
                id="before_its_dir",
            ),
            pytest.param(
                [
                    member(SLOT.relpath, tarfile.DIRTYPE, mode=0o755),
                    member(f"{SLOT.relpath}/{OPAQUE_WHITEOUT}", data=b"x"),
                ],
                "the only whiteout",
                id="opaque_with_contents",
            ),
        ),
    )
    def test_the_reader_refuses_what_a_set_does_not_hold(
        self, tmp_path: Path, members, refusal
    ):
        _out = tmp_path / "out"
        _out.mkdir()
        with pytest.raises(ParameterLayerInvalid, match=refusal):
            read_parameter_layer(io.BytesIO(zstd_tar(members)), [SLOT], extract_to=_out)
        # what came before the refused member may be there, for the caller to
        #   discard; nothing is written outside the slot, nor outside the target
        _written = [
            _p.relative_to(_out).as_posix() for _p in _out.rglob("*") if _p.is_file()
        ]
        assert all(_w.startswith(SLOT.relpath + "/") for _w in _written), _written
        assert sorted(_p.name for _p in tmp_path.iterdir()) == ["out"]

    def test_leading_dot_slash_and_trailing_slash_are_read(self):
        """Another writer may name members so; the paths are the same."""
        _members = [
            member(f"./{SLOT.relpath}/", tarfile.DIRTYPE, mode=0o755),
            member(f"./{SLOT.relpath}/{OPAQUE_WHITEOUT}"),
            member(f"./{SLOT.relpath}/d/", tarfile.DIRTYPE, mode=0o755),
            member(f"./{SLOT.relpath}/d/f", data=b"f"),
        ]
        _info = read_parameter_layer(io.BytesIO(zstd_tar(_members)), [SLOT])
        assert [_f.path for _f in _info.files] == [f"{SLOT.relpath}/d/f"]

    def test_a_layer_bigger_than_the_bound_is_refused(self, tmp_path: Path):
        _blob, _info = layer_bytes(make_tree(tmp_path / "tree"))
        with pytest.raises(ParameterLayerInvalid, match="exceed"):
            read_parameter_layer(
                io.BytesIO(_blob), [SLOT], max_size=_info.files_size - 1
            )
        read_parameter_layer(io.BytesIO(_blob), [SLOT], max_size=_info.files_size)

    def test_digests_that_do_not_match_are_refused(self, tmp_path: Path):
        _blob, _info = layer_bytes(make_tree(tmp_path / "tree"))
        _other = Sha256Digest("0" * 64)
        with pytest.raises(ParameterLayerInvalid, match="tar"):
            read_parameter_layer(io.BytesIO(_blob), [SLOT], diff_id=_other)
        with pytest.raises(ParameterLayerInvalid, match="blob"):
            read_parameter_layer(io.BytesIO(_blob), [SLOT], blob_digest=_other)

    def test_zero_padding_after_the_archive_is_read_and_hashed(self):
        """Past what the reader buffers, too: it is in the diff_id."""
        _members = [
            *slot_members(),
            member(f"{SLOT.relpath}/big", data=os.urandom(READ_SIZE // 2)),
        ]
        _raw = raw_tar(_members)
        _padded = _raw + b"\0" * (MAX_TAR_TRAILER - (len(_raw) - tar_members_end(_raw)))
        assert len(_padded) > READ_SIZE
        _info = read_parameter_layer(
            io.BytesIO(zstandard.ZstdCompressor().compress(_padded)),
            [SLOT],
            diff_id=Sha256Digest(sha256(_padded).hexdigest()),
        )
        assert len(_info.files) == 1

        with pytest.raises(ParameterLayerInvalid, match="after the last member"):
            read_parameter_layer(
                io.BytesIO(zstandard.ZstdCompressor().compress(_padded + b"\0")),
                [SLOT],
            )

    def test_what_follows_the_archive_is_refused(self):
        """A reader that reads past the end-of-archive marker would find it."""
        _smuggled = raw_tar(
            [member("etc/cron.d", tarfile.DIRTYPE), member("etc/cron.d/job", data=b"x")]
        )
        _layer = zstandard.ZstdCompressor().compress(
            raw_tar(slot_members()) + _smuggled
        )
        with pytest.raises(ParameterLayerInvalid, match="more than zero padding"):
            read_parameter_layer(io.BytesIO(_layer), [SLOT])

    def test_a_tar_cut_short_is_refused(self):
        """It ends at a member's end, where tarfile stops without a word."""
        _raw = raw_tar([*slot_members(), member(f"{SLOT.relpath}/a", data=b"a")])
        _cut = _raw[: tar_members_end(_raw)]
        with pytest.raises(ParameterLayerInvalid, match="end-of-archive"):
            read_parameter_layer(
                io.BytesIO(zstandard.ZstdCompressor().compress(_cut)), [SLOT]
            )

    def test_what_is_not_a_zstd_tar_is_refused(self):
        with pytest.raises(ParameterLayerInvalid):
            read_parameter_layer(io.BytesIO(b"not zstd at all"), [SLOT])
        with pytest.raises(ParameterLayerInvalid):
            read_parameter_layer(
                io.BytesIO(zstandard.ZstdCompressor().compress(b"not a tar" * 100)),
                [SLOT],
            )


#
# ------ the slots in the running base ------ #
#


def base_tree_at(root: Path) -> Path:
    """A base with both slots' directories and SLOT's apply."""
    (root / SLOT.relpath).mkdir(parents=True)
    (root / OTHER_SLOT.relpath).mkdir(parents=True)
    _apply = root / APPLY[1:]
    _apply.write_text("#!/bin/sh\n")
    _apply.chmod(0o755)
    return root


class TestInTheTree:
    def test_a_base_with_the_slots_and_the_apply(self, tmp_path: Path):
        check_slots_in_tree(base_tree_at(tmp_path / "rootfs"), [SLOT, OTHER_SLOT])

    def test_a_slot_the_base_has_no_directory_for(self, tmp_path: Path):
        _root = base_tree_at(tmp_path / "rootfs")
        shutil.rmtree(_root / SLOT.relpath)
        with pytest.raises(ValueError, match="no directory"):
            check_slots_in_tree(_root, [SLOT])
        (_root / SLOT.relpath).write_text("a file\n")
        with pytest.raises(ValueError, match="no directory"):
            check_slots_in_tree(_root, [SLOT])

    def test_an_apply_the_base_does_not_have(self, tmp_path: Path):
        _root = base_tree_at(tmp_path / "rootfs")
        (_root / APPLY[1:]).chmod(0o644)
        with pytest.raises(ValueError, match="not an executable"):
            check_slots_in_tree(_root, [SLOT])
        (_root / APPLY[1:]).unlink()
        (_root / APPLY[1:]).mkdir(mode=0o755)
        with pytest.raises(ValueError, match="not an executable"):
            check_slots_in_tree(_root, [SLOT])
        (_root / APPLY[1:]).rmdir()
        with pytest.raises(ValueError, match="no apply"):
            check_slots_in_tree(_root, [SLOT])
        # reboot needs no file
        check_slots_in_tree(_root, [OTHER_SLOT])

    def test_an_apply_whose_way_is_through_a_file(self, tmp_path: Path):
        """Another base may have a file where this one has a directory."""
        _root = base_tree_at(tmp_path / "rootfs")
        (_root / "opt" / "tools").write_text("a file\n")
        _slot = ParameterSlot(name="s", path=SLOT_PATH, apply="/opt/tools/apply.sh")
        with pytest.raises(ValueError, match="no apply"):
            check_slots_in_tree(_root, [_slot])

    def test_a_slot_over_what_this_consumer_reads_too(self, tmp_path: Path):
        _root = base_tree_at(tmp_path / "rootfs")
        check_slots_in_tree(_root, [SLOT], reserved=["/etc/ota"])
        with pytest.raises(ValueError, match="reads for itself"):
            check_slots_in_tree(
                _root, [SLOT], reserved=["/etc/ota", "/opt/autoware/vehicle"]
            )

    def test_links_on_the_way_are_refused(self, tmp_path: Path):
        """A link could lead out of the tree, or into a slot."""
        _root = base_tree_at(tmp_path / "rootfs")
        _real = _root / "opt" / "autoware" / "real_vehicle"
        os.replace(_root / SLOT.relpath, _real)
        (_root / SLOT.relpath).symlink_to(_real)
        with pytest.raises(ValueError, match="symbolic link"):
            check_slots_in_tree(_root, [SLOT])

        _root = base_tree_at(tmp_path / "rootfs2")
        _target = _root / OTHER_SLOT.relpath / "apply.sh"
        os.replace(_root / APPLY[1:], _target)
        (_root / APPLY[1:]).symlink_to(_target)
        with pytest.raises(ValueError, match="symbolic link"):
            check_slots_in_tree(_root, [SLOT])


#
# ------ laying a set over a base tree ------ #
#


def build_parameter_image(
    tmp_path: Path,
    *,
    tree: Path | None,
    config_update: dict | None = None,
    index_annotations: dict | None = None,
) -> Path:
    """A parameter image artifact with one set for ECU; an empty set when `tree` is
    None. `config_update` and `index_annotations` spoil the config and the index
    entry, unchecked."""
    _image_root = tmp_path / "parameter_image"
    _resource_dir = _image_root / RESOURCE_DIR
    _resource_dir.mkdir(parents=True)
    if tree is None:
        _layer = EmptyDescriptor.add_contents_to_resource_dir(EMPTY_JSON, _resource_dir)
        _config = ParameterSetConfig(name="p", version="2026.10.29-1")
    else:
        _out = io.BytesIO()
        _info = write_parameter_layer(tree, [SLOT], _out)
        _layer = ParameterLayerDescriptor.add_contents_to_resource_dir(
            _out.getvalue(), _resource_dir
        )
        _config = ParameterSetConfig(
            name="p",
            version="2026.10.29-1",
            slots=[SLOT],
            diff_ids=[_info.diff_id],
            files=_info.files,
        )
    if config_update:
        _config = _config.model_copy(update=config_update)
    _config_descriptor = ParameterSetConfig.Descriptor.export_metafile_to_resource_dir(
        _config, _resource_dir
    )
    _manifest = ParameterSetManifest(
        config=_config_descriptor,
        layers=[_layer],
        annotations=ParameterSetManifest.Annotations.model_validate(
            MANIFEST_ANNOTATIONS
        ),
    )
    _index = ImageIndex(
        manifests=[],
        annotations=ImageIndex.Annotations.model_validate({BUILD_TOOL_VERSION: "test"}),
    )
    _index.add_image(
        ParameterSetManifest.Descriptor.export_metafile_to_resource_dir(
            _manifest,
            _resource_dir,
            annotations=index_annotations or MANIFEST_ANNOTATIONS,
        )
    )
    (_image_root / IMAGE_INDEX_FNAME).write_text(_index.export_metafile())

    _artifact = tmp_path / "parameter_image.zip"
    with ZipFile(_artifact, "w", compression=ZIP_STORED) as zf:
        zf.write(_image_root / IMAGE_INDEX_FNAME, IMAGE_INDEX_FNAME)
        for _blob in sorted(_resource_dir.iterdir()):
            zf.write(_blob, f"{RESOURCE_DIR}/{_blob.name}")
    return _artifact


class TestOverlay:
    @pytest.fixture
    def base_tree(self, tmp_path: Path) -> Path:
        """A deployed base: the slot's defaults, one of them gone from the set."""
        _root = tmp_path / "rootfs"
        _slot = _root / SLOT.relpath
        (_slot / "default").mkdir(parents=True)
        (_slot / "default" / "vehicle.param.yaml").write_text("max_speed: 8\n")
        (_slot / "only_in_the_base").write_text("stale\n")
        (_root / OTHER_SLOT.relpath).mkdir(parents=True)
        (_root / OTHER_SLOT.relpath / "launch.xml").write_text("<launch/>\n")
        (_root / APPLY[1:]).write_text("#!/bin/sh\n")
        (_root / APPLY[1:]).chmod(0o755)
        return _root

    def overlay(self, tmp_path: Path, rootfs: Path, artifact: Path, **kw):
        _tmp = tmp_path / "tmp"
        _tmp.mkdir()
        _args = dict(
            rootfs_dir=rootfs,
            parameter_image=artifact,
            image_id=IMAGE_ID,
            tmp_dir=_tmp,
        )
        _args.update(kw)
        return overlay_parameter_set(**_args)

    def test_the_set_replaces_its_slot_and_leaves_the_others(
        self, tmp_path: Path, base_tree: Path
    ):
        _artifact = build_parameter_image(tmp_path, tree=make_tree(tmp_path / "set"))
        _config = self.overlay(tmp_path, base_tree, _artifact)

        assert _config.version == "2026.10.29-1"
        _slot = base_tree / SLOT.relpath
        assert (
            _slot / "default" / "vehicle.param.yaml"
        ).read_text() == "max_speed: 10\n"
        assert (_slot / "vehicle-0042" / "vehicle.param.yaml").exists()
        assert not (_slot / "only_in_the_base").exists(), "the slot is replaced whole"
        assert (base_tree / OTHER_SLOT.relpath / "launch.xml").exists()

    def test_an_empty_set_leaves_the_base_defaults(
        self, tmp_path: Path, base_tree: Path
    ):
        _artifact = build_parameter_image(tmp_path, tree=None)
        assert self.overlay(tmp_path, base_tree, _artifact).is_empty
        assert (base_tree / SLOT.relpath / "only_in_the_base").exists()

    def test_a_base_without_the_apply_is_not_laid(
        self, tmp_path: Path, base_tree: Path
    ):
        (base_tree / APPLY[1:]).unlink()
        _artifact = build_parameter_image(tmp_path, tree=make_tree(tmp_path / "set"))
        with pytest.raises(ParameterSetNotApplicable, match="no apply"):
            self.overlay(tmp_path, base_tree, _artifact)
        assert (base_tree / SLOT.relpath / "only_in_the_base").exists()

    def test_a_slot_behind_a_link_is_not_followed_out_of_the_tree(
        self, tmp_path: Path, base_tree: Path
    ):
        _outside = tmp_path / "outside"
        (_outside / "individual_params").mkdir(parents=True)
        (_outside / "individual_params" / "keep").write_text("host file\n")
        _slot = base_tree / SLOT.relpath
        shutil.rmtree(_slot)
        _slot.symlink_to(_outside / "individual_params")
        _artifact = build_parameter_image(tmp_path, tree=make_tree(tmp_path / "set"))
        with pytest.raises(ParameterSetNotApplicable, match="symbolic link"):
            self.overlay(tmp_path, base_tree, _artifact)
        assert (_outside / "individual_params" / "keep").read_text() == "host file\n"

    def test_files_the_config_lists_and_the_layer_does_not_hold(
        self, tmp_path: Path, base_tree: Path
    ):
        _set = make_tree(tmp_path / "set")
        _info = write_parameter_layer(_set, [SLOT], io.BytesIO())
        _files = [
            *_info.files,
            ParameterSetFileEntry(
                path=f"{SLOT.relpath}/not_in_the_layer",
                size=0,
                digest=Sha256Digest(sha256(b"").hexdigest()),
            ),
        ]
        _artifact = build_parameter_image(
            tmp_path, tree=_set, config_update={"files": _files}
        )
        with pytest.raises(ParameterSetInvalid, match="other files"):
            self.overlay(tmp_path, base_tree, _artifact)
        assert (base_tree / SLOT.relpath / "only_in_the_base").exists()

    def test_a_layer_that_is_not_the_configs_leaves_the_base(
        self, tmp_path: Path, base_tree: Path
    ):
        _artifact = build_parameter_image(
            tmp_path,
            tree=make_tree(tmp_path / "set"),
            config_update={"diff_ids": [Sha256Digest("0" * 64)]},
        )
        with pytest.raises(ParameterLayerInvalid, match="the tar is"):
            self.overlay(tmp_path, base_tree, _artifact)
        assert (base_tree / SLOT.relpath / "only_in_the_base").exists()

    def test_a_config_that_is_not_the_manifests_is_refused(self, tmp_path: Path):
        """A set that fills a slot, with the empty descriptor for its layer."""
        _artifact = build_parameter_image(
            tmp_path,
            tree=None,
            config_update={"slots": [SLOT], "diff_ids": [Sha256Digest("0" * 64)]},
        )
        with pytest.raises(ParameterSetInvalid, match="empty"):
            open_parameter_set(_artifact, IMAGE_ID)

    def test_an_index_entry_naming_another_version_is_refused(self, tmp_path: Path):
        _artifact = build_parameter_image(
            tmp_path,
            tree=None,
            index_annotations={**MANIFEST_ANNOTATIONS, PARAMETER_SET_VERSION: "0"},
        )
        with pytest.raises(ParameterSetInvalid, match="version"):
            open_parameter_set(_artifact, IMAGE_ID)

    def test_the_parameter_image_is_checked_without_a_base(self, tmp_path: Path):
        _artifact = build_parameter_image(tmp_path, tree=make_tree(tmp_path / "set"))
        assert open_parameter_set(_artifact, IMAGE_ID).slot(SLOT.name) == SLOT
        with pytest.raises(ParameterSetNotApplicable, match="no parameter set"):
            open_parameter_set(
                _artifact, ImageIdentifier("perception", OTAReleaseKey.dev)
            )
        with pytest.raises(ParameterSetInvalid, match="cannot open"):
            open_parameter_set(tmp_path / "missing.zip", IMAGE_ID)
        (tmp_path / "not_a_zip").write_text("x")
        with pytest.raises(ParameterSetInvalid, match="cannot open"):
            open_parameter_set(tmp_path / "not_a_zip", IMAGE_ID)

    def test_lookup_image_shows_the_set_config(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        _artifact = build_parameter_image(tmp_path, tree=make_tree(tmp_path / "set"))
        _lookup_image_from_artifact(
            image_root=_artifact, image_id=IMAGE_ID, show_image_config=True
        )
        _shown = json.loads(capsys.readouterr().out)
        assert _shown["slots"][0]["name"] == SLOT.name
        assert _shown["version"] == "2026.10.29-1"

    def test_list_image_names_the_kind(self, tmp_path: Path):
        _artifact = build_parameter_image(tmp_path, tree=None)
        _listed = _list_image_from_artifact(_artifact)
        assert "kind='parameter-set'" in _render_output(_listed)

    def test_another_ecu_has_no_set_here(self, tmp_path: Path, base_tree: Path):
        _artifact = build_parameter_image(tmp_path, tree=make_tree(tmp_path / "set"))
        with pytest.raises(ParameterSetNotApplicable, match="no parameter set"):
            self.overlay(
                tmp_path,
                base_tree,
                _artifact,
                image_id=ImageIdentifier("perception", OTAReleaseKey.dev),
            )
