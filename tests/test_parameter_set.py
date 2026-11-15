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
from ota_image_libs.v1.image_config.schema import ImageConfig
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
    OTA_IMAGE_ARTIFACT,
    PARAMETER_SET_ARTIFACT,
    PARAMETER_SET_CONFIG_JSON,
    PARTITION_IMAGE_ARTIFACT,
)
from ota_image_libs.v1.parameter_set.layer import (
    OPAQUE_WHITEOUT,
    ParameterLayerInvalid,
    read_parameter_layer,
    write_parameter_layer,
)
from ota_image_libs.v1.parameter_set.schema import (
    EmptyDescriptor,
    FileBasedSubjectDescriptor,
    ParameterLayerDescriptor,
    ParameterSetConfig,
    ParameterSetManifest,
    PartitionBasedSubjectDescriptor,
    check_against_base,
)
from ota_image_libs.v1.parameter_set.slots import (
    ParameterSlot,
    ParameterSlotRef,
    check_base_slots,
    check_slots_disjoint,
)
from ota_image_libs.v1.update_agent_package.schema import EMPTY_JSON
from ota_image_tools.cmds.list_image import _list_image_from_artifact, _render_output
from ota_image_tools.libs.deploy_parameter_set import (
    ParameterSetNotApplicable,
    overlay_parameter_set,
)

SLOT_PATH = "/opt/autoware/vehicle/vehicle.j6_gen2/individual_params"
OTHER_SLOT_PATH = "/opt/autoware/vehicle/vehicle.j6_gen2/j6_gen2_launch"
SLOT = ParameterSlotRef(name="individual_params", path=SLOT_PATH)
OTHER_SLOT = ParameterSlotRef(name="launch", path=OTHER_SLOT_PATH)
BASE_SLOTS = [
    ParameterSlot(
        name="individual_params",
        path=SLOT_PATH,
        apply="/opt/autoware/bin/apply-parameter-set",
    ),
    ParameterSlot(name="launch", path=OTHER_SLOT_PATH, apply="reboot"),
]
BASE_MANIFEST_DIGEST = Sha256Digest(sha256(b"the base payload manifest").hexdigest())
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
    (_slot_dir / "J6-0042").mkdir()
    (_slot_dir / "J6-0042" / "vehicle.param.yaml").write_text("max_speed: 12\n")
    (_slot_dir / "README").write_text("parameters\n")
    return root


def layer_bytes(root: Path, slots=(SLOT,)) -> tuple[bytes, object]:
    _out = io.BytesIO()
    _info = write_parameter_layer(root, list(slots), _out)
    return _out.getvalue(), _info


def zstd_tar(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    """A hand-made layer, for what the writer would never write."""
    _raw = io.BytesIO()
    with tarfile.open(fileobj=_raw, mode="w", format=tarfile.PAX_FORMAT) as _tar:
        for _ti, _data in members:
            _tar.addfile(_ti, io.BytesIO(_data) if _data is not None else None)
    return zstandard.ZstdCompressor().compress(_raw.getvalue())


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
    def test_a_base_declares_a_slot_with_how_it_takes_effect(self):
        _slot = ParameterSlot.model_validate(
            {"name": "individual_params", "path": SLOT_PATH, "apply": "reboot"}
        )
        assert _slot.relpath == SLOT_PATH[1:]

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
    def test_a_base_slot_is_not_over_what_the_consumer_reads(self, path):
        with pytest.raises(ValueError, match="reads for itself"):
            check_base_slots("t", [ParameterSlot(name="s", path=path, apply="reboot")])

    def test_a_base_slots_apply_is_not_inside_a_slot(self):
        """A set carries files only: it could replace an apply inside a slot."""
        with pytest.raises(ValueError, match="which a set replaces"):
            check_base_slots(
                "t",
                [
                    ParameterSlot(
                        name="s", path=SLOT_PATH, apply=f"{SLOT_PATH}/apply.sh"
                    )
                ],
            )
        with pytest.raises(ValueError, match="which a set replaces"):
            check_base_slots(
                "t",
                [
                    ParameterSlot(
                        name="a", path=SLOT_PATH, apply=f"{OTHER_SLOT_PATH}/x"
                    ),
                    ParameterSlot(name="b", path=OTHER_SLOT_PATH, apply="reboot"),
                ],
            )
        check_base_slots("t", BASE_SLOTS)

    def test_the_image_config_declares_them_and_an_old_one_has_none(self):
        _fixture = Path(__file__).parent / "data" / "ota-image.zip"
        with ZipFile(_fixture) as zf:
            _index = ImageIndex.parse_metafile(zf.read(IMAGE_INDEX_FNAME).decode())
            _descriptor = next(
                d for d in _index.manifests if isinstance(d, ImageManifest.Descriptor)
            )
            _manifest = ImageManifest.parse_metafile(
                zf.read(f"{RESOURCE_DIR}/{_descriptor.digest.digest_hex}").decode()
            )
            _raw = json.loads(
                zf.read(f"{RESOURCE_DIR}/{_manifest.config.digest.digest_hex}")
            )
        _plain = ImageConfig.model_validate_json(json.dumps(_raw))
        assert _plain.parameter_slots is None
        assert "parameter_slots" not in json.loads(_plain.export_metafile())

        _raw["parameter_slots"] = [_s.model_dump() for _s in BASE_SLOTS]
        _config = ImageConfig.parse_metafile(json.dumps(_raw))
        assert _config.parameter_slots == BASE_SLOTS
        assert json.loads(_config.export_metafile())["parameter_slots"][0] == {
            "name": "individual_params",
            "path": SLOT_PATH,
            "apply": "/opt/autoware/bin/apply-parameter-set",
        }

        _raw["parameter_slots"].append(
            {"name": "inner", "path": f"{SLOT_PATH}/x", "apply": "reboot"}
        )
        with pytest.raises(ValidationError, match="inside"):
            ImageConfig.parse_metafile(json.dumps(_raw))


#
# ------ config and manifest ------ #
#

DIFF_ID = "sha256:" + "1" * 64


def config_dict(**kw) -> dict:
    _d = {
        "schemaVersion": 1,
        "mediaType": PARAMETER_SET_CONFIG_JSON,
        "name": "j6_gen2_params",
        "version": "2026.10.29-1",
        "slots": [{"name": SLOT.name, "path": SLOT.path}],
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


def manifest_dict(
    *, empty: bool = False, subject_type: str = OTA_IMAGE_ARTIFACT
) -> dict:
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
        "subject": {
            "mediaType": IMAGE_MANIFEST,
            "artifactType": subject_type,
            "digest": str(BASE_MANIFEST_DIGEST),
            "size": 818,
        },
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
            pytest.param({"version": "1 0"}, id="version_with_a_space"),
            pytest.param({"name": ""}, id="no_name"),
            pytest.param(
                {"slots": [{"name": "a", "path": "/x"}, {"name": "b", "path": "/x/y"}]},
                id="nested_slots",
            ),
        ),
    )
    def test_a_config_that_does_not_add_up_is_refused(self, change):
        with pytest.raises(ValidationError):
            ParameterSetConfig.parse_metafile(json.dumps(config_dict(**change)))


class TestManifest:
    def test_a_manifest_carries_its_artifact_type_and_subject(self):
        _manifest = ParameterSetManifest.parse_metafile(json.dumps(manifest_dict()))
        assert isinstance(_manifest.subject, FileBasedSubjectDescriptor)
        assert _manifest.subject.digest == BASE_MANIFEST_DIGEST
        assert isinstance(_manifest.layer, ParameterLayerDescriptor)
        assert _manifest.version == "2026.10.29-1"
        assert _manifest.image_identifier == IMAGE_ID

        _exported = json.loads(_manifest.export_metafile())
        assert _exported["artifactType"] == PARAMETER_SET_ARTIFACT
        assert _exported["subject"]["artifactType"] == OTA_IMAGE_ARTIFACT
        assert (
            ParameterSetManifest.parse_metafile(_manifest.export_metafile())
            == _manifest
        )

    def test_a_set_for_a_partition_based_base(self):
        _manifest = ParameterSetManifest.parse_metafile(
            json.dumps(manifest_dict(subject_type=PARTITION_IMAGE_ARTIFACT))
        )
        assert isinstance(_manifest.subject, PartitionBasedSubjectDescriptor)

    def test_an_empty_set_carries_the_empty_descriptor(self):
        _manifest = ParameterSetManifest.parse_metafile(
            json.dumps(manifest_dict(empty=True))
        )
        assert _manifest.layer is None
        assert isinstance(_manifest.layers[0], EmptyDescriptor)

    def test_a_subject_names_the_kind_of_its_base(self):
        _raw = manifest_dict()
        del _raw["subject"]["artifactType"]
        with pytest.raises(ValidationError):
            ParameterSetManifest.parse_metafile(json.dumps(_raw))
        _raw["subject"]["artifactType"] = PARAMETER_SET_ARTIFACT
        with pytest.raises(ValidationError):
            ParameterSetManifest.parse_metafile(json.dumps(_raw))

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
        assert (_out / SLOT.relpath / "J6-0042" / "vehicle.param.yaml").read_text() == (
            "max_speed: 12\n"
        )
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

    def test_the_reader_does_not_write_through_a_link_in_the_target(
        self, tmp_path: Path
    ):
        _blob, _ = layer_bytes(make_tree(tmp_path / "tree"))
        _out = tmp_path / "out"
        _victim = tmp_path / "victim"
        _victim.write_text("untouched\n")
        _readme = _out / SLOT.relpath / "README"
        _readme.parent.mkdir(parents=True)
        _readme.symlink_to(_victim)
        with pytest.raises(OSError):
            read_parameter_layer(io.BytesIO(_blob), [SLOT], extract_to=_out)
        assert _victim.read_text() == "untouched\n"

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
        "members",
        (
            pytest.param(
                [
                    *slot_members(),
                    member(f"{SLOT.relpath}/l", tarfile.SYMTYPE, linkname="x"),
                ],
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
                id="hardlink",
            ),
            pytest.param(
                [*slot_members(), member(f"{SLOT.relpath}/d", tarfile.CHRTYPE)],
                id="device",
            ),
            pytest.param(
                [*slot_members(), member("etc/passwd", data=b"x")], id="outside"
            ),
            pytest.param(
                [*slot_members(), member(f"{SLOT.relpath}/../../x", data=b"x")],
                id="dot_dot",
            ),
            pytest.param(
                [*slot_members(), member(f"/{SLOT.relpath}/x")], id="absolute"
            ),
            pytest.param(
                [*slot_members(), member(f"{SLOT.relpath}/.wh.gone")],
                id="other_whiteout",
            ),
            pytest.param(
                [
                    *slot_members(),
                    member(f"{SLOT.relpath}/d", tarfile.DIRTYPE, mode=0o755),
                    member(f"{SLOT.relpath}/d/{OPAQUE_WHITEOUT}"),
                ],
                id="opaque_below_the_slot",
            ),
            pytest.param(
                [member(SLOT.relpath, tarfile.DIRTYPE, mode=0o755)], id="no_opaque"
            ),
            pytest.param(
                [member(f"{SLOT.relpath}/{OPAQUE_WHITEOUT}")], id="no_slot_dir"
            ),
            pytest.param(
                [
                    *slot_members(),
                    member(f"{SLOT.relpath}/x"),
                    member(f"{SLOT.relpath}/x"),
                ],
                id="twice",
            ),
            pytest.param(
                [*slot_members(), member(f"{SLOT.relpath}/x", mode=0o4755)], id="setuid"
            ),
            pytest.param(
                [*slot_members(), member(f"{SLOT.relpath}/d/x")], id="before_its_dir"
            ),
            pytest.param(
                [
                    member(SLOT.relpath, tarfile.DIRTYPE, mode=0o755),
                    member(f"{SLOT.relpath}/{OPAQUE_WHITEOUT}", data=b"x"),
                ],
                id="opaque_with_contents",
            ),
        ),
    )
    def test_the_reader_refuses_what_a_set_does_not_hold(self, tmp_path: Path, members):
        _out = tmp_path / "out"
        _out.mkdir()
        with pytest.raises(ParameterLayerInvalid):
            read_parameter_layer(io.BytesIO(zstd_tar(members)), [SLOT], extract_to=_out)
        # what came before the refused member may be there, for the caller to
        #   discard; nothing is written outside the slot
        _written = [
            _p.relative_to(_out).as_posix() for _p in _out.rglob("*") if _p.is_file()
        ]
        assert all(_w.startswith(SLOT.relpath + "/") for _w in _written), _written
        assert not (tmp_path / "etc").exists() and not (tmp_path / "x").exists()

    def test_a_layer_bigger_than_the_bound_is_refused(self, tmp_path: Path):
        _blob, _info = layer_bytes(make_tree(tmp_path / "tree"))
        with pytest.raises(ParameterLayerInvalid, match="exceed"):
            read_parameter_layer(
                io.BytesIO(_blob), [SLOT], max_size=_info.files_size - 1
            )

    def test_digests_that_do_not_match_are_refused(self, tmp_path: Path):
        _blob, _info = layer_bytes(make_tree(tmp_path / "tree"))
        _other = Sha256Digest("0" * 64)
        with pytest.raises(ParameterLayerInvalid, match="tar"):
            read_parameter_layer(io.BytesIO(_blob), [SLOT], diff_id=_other)
        with pytest.raises(ParameterLayerInvalid, match="blob"):
            read_parameter_layer(io.BytesIO(_blob), [SLOT], blob_digest=_other)

    def test_what_is_not_a_zstd_tar_is_refused(self):
        with pytest.raises(ParameterLayerInvalid):
            read_parameter_layer(io.BytesIO(b"not zstd at all"), [SLOT])
        with pytest.raises(ParameterLayerInvalid):
            read_parameter_layer(
                io.BytesIO(zstandard.ZstdCompressor().compress(b"not a tar" * 100)),
                [SLOT],
            )


#
# ------ the set against its base ------ #
#


class TestAgainstTheBase:
    def setup_method(self):
        self.manifest = ParameterSetManifest.parse_metafile(json.dumps(manifest_dict()))
        self.config = ParameterSetConfig.parse_metafile(json.dumps(config_dict()))

    def test_a_set_for_this_base_fills_its_declared_slots(self):
        assert check_against_base(
            self.manifest,
            self.config,
            base_manifest_digest=BASE_MANIFEST_DIGEST,
            base_slots=BASE_SLOTS,
        ) == [BASE_SLOTS[0]]

    def test_a_set_for_another_base_is_refused(self):
        with pytest.raises(ValueError, match="for base"):
            check_against_base(
                self.manifest,
                self.config,
                base_manifest_digest=Sha256Digest("0" * 64),
                base_slots=BASE_SLOTS,
            )

    def test_a_slot_the_base_does_not_declare_is_refused(self):
        with pytest.raises(ValueError, match="declares no slot"):
            check_against_base(
                self.manifest,
                self.config,
                base_manifest_digest=BASE_MANIFEST_DIGEST,
                base_slots=BASE_SLOTS[1:],
            )

    def test_a_slot_at_another_path_is_refused(self):
        _moved = [BASE_SLOTS[0].model_copy(update={"path": "/opt/elsewhere"})]
        with pytest.raises(ValueError, match="in the base"):
            check_against_base(
                self.manifest,
                self.config,
                base_manifest_digest=BASE_MANIFEST_DIGEST,
                base_slots=_moved,
            )


#
# ------ laying a set over a base tree ------ #
#


def build_parameter_image(tmp_path: Path, *, tree: Path | None) -> Path:
    """A parameter image artifact with one set for ECU, for the base digest above;
    an empty set when `tree` is None."""
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
    _config_descriptor = ParameterSetConfig.Descriptor.export_metafile_to_resource_dir(
        _config, _resource_dir
    )
    _manifest = ParameterSetManifest(
        config=_config_descriptor,
        layers=[_layer],
        subject=FileBasedSubjectDescriptor(size=818, digest=BASE_MANIFEST_DIGEST),
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
            _manifest, _resource_dir, annotations=MANIFEST_ANNOTATIONS
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
        return _root

    def overlay(self, tmp_path: Path, rootfs: Path, artifact: Path, **kw):
        _tmp = tmp_path / "tmp"
        _tmp.mkdir()
        _args = dict(
            rootfs_dir=rootfs,
            parameter_image=artifact,
            image_id=IMAGE_ID,
            base_manifest_digest=BASE_MANIFEST_DIGEST,
            base_slots=BASE_SLOTS,
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
        assert (_slot / "J6-0042" / "vehicle.param.yaml").exists()
        assert not (_slot / "only_in_the_base").exists(), "the slot is replaced whole"
        assert (base_tree / OTHER_SLOT.relpath / "launch.xml").exists()

    def test_an_empty_set_leaves_the_base_defaults(
        self, tmp_path: Path, base_tree: Path
    ):
        _artifact = build_parameter_image(tmp_path, tree=None)
        assert self.overlay(tmp_path, base_tree, _artifact).is_empty
        assert (base_tree / SLOT.relpath / "only_in_the_base").exists()

    def test_a_set_for_another_base_is_not_laid(self, tmp_path: Path, base_tree: Path):
        _artifact = build_parameter_image(tmp_path, tree=make_tree(tmp_path / "set"))
        with pytest.raises(ParameterSetNotApplicable, match="for base"):
            self.overlay(
                tmp_path,
                base_tree,
                _artifact,
                base_manifest_digest=Sha256Digest("0" * 64),
            )
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
