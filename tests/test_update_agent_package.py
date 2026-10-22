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
"""The update agent release package: one entry, several bundles, each for a consumer.

The generic form of the otaclient release package. What it has to get right is the
picking: a consumer must take only a bundle it implements and can run, because what it
does with one is install it and then execute it as root.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from ota_image_libs.v1.annotation_keys import (
    BUILD_TOOL_VERSION,
    UPDATE_AGENT_ARCH,
    UPDATE_AGENT_TYPE,
    UPDATE_AGENT_VERSION,
)
from ota_image_libs.v1.image_index.schema import ImageIndex
from ota_image_libs.v1.media_types import (
    IMAGE_MANIFEST,
    OCI_EMPTY_JSON,
    UPDATE_AGENT_BUNDLE,
    UPDATE_AGENT_TYPE_OTACLIENT,
    UPDATE_AGENT_TYPE_PARTITION_AGENT,
)
from ota_image_libs.v1.update_agent_package.schema import (
    EMPTY_JSON,
    EmptyConfigDescriptor,
    UpdateAgentBundleDescriptor,
    UpdateAgentPackageManifest,
)
from ota_image_libs.v1.update_agent_package.utils import add_update_agent_package

EMPTY = EmptyConfigDescriptor(
    size=len(EMPTY_JSON), digest=f"sha256:{sha256(EMPTY_JSON).hexdigest()}"
)


def bundle(agent_type: str, version: str, arch: str | None, n: int = 1):
    ann = {UPDATE_AGENT_TYPE: agent_type, UPDATE_AGENT_VERSION: version}
    if arch:
        ann[UPDATE_AGENT_ARCH] = arch
    return UpdateAgentBundleDescriptor(
        mediaType=UPDATE_AGENT_BUNDLE,
        digest=f"sha256:{str(n) * 64}",
        size=n,
        annotations=ann,
    )


def manifest(*bundles):
    return UpdateAgentPackageManifest(config=EMPTY, layers=list(bundles))


def test_one_image_can_carry_the_agent_for_every_ecu_it_serves():
    m = manifest(
        bundle("tier4.ota.agent.v1", "1.2.0", "arm64", 1),
        bundle("tier4.ota.agent.v1", "1.2.0", "x86_64", 2),
        bundle("tier4.otaclient.squashfs.v1", "3.14.0", "x86_64", 3),
    )
    assert (
        m.find_bundle(agent_type="tier4.ota.agent.v1", architecture="arm64").size == 1
    )
    assert (
        m.find_bundle(agent_type="tier4.ota.agent.v1", architecture="x86_64").size == 2
    )
    assert (
        m.find_bundle(
            agent_type="tier4.otaclient.squashfs.v1", architecture="x86_64"
        ).size
        == 3
    )


def test_a_type_this_consumer_does_not_implement_is_not_offered_to_it():
    m = manifest(bundle("somebody.elses.agent.v1", "9.9.9", "arm64"))
    assert m.find_bundle(agent_type="tier4.ota.agent.v1", architecture="arm64") is None


def test_a_bundle_for_another_architecture_is_not_offered():
    m = manifest(bundle("tier4.ota.agent.v1", "1.2.0", "x86_64"))
    assert m.find_bundle(agent_type="tier4.ota.agent.v1", architecture="arm64") is None


def test_a_bundle_that_states_no_architecture_runs_anywhere():
    """That is the publisher saying so; a consumer asking for one still gets it."""
    m = manifest(bundle("tier4.ota.agent.v1", "1.2.0", None))
    assert (
        m.find_bundle(agent_type="tier4.ota.agent.v1", architecture="arm64") is not None
    )


def test_a_bundle_must_say_what_it_is_and_which_version():
    with pytest.raises(ValueError):
        UpdateAgentBundleDescriptor(
            mediaType=UPDATE_AGENT_BUNDLE,
            digest=f"sha256:{'a' * 64}",
            size=1,
            annotations={UPDATE_AGENT_TYPE: "tier4.ota.agent.v1"},
        )


@pytest.mark.parametrize(
    "shipped, asked",
    [
        ("arm64", "aarch64"),
        ("aarch64", "arm64"),
        ("x86_64", "amd64"),
        ("amd64", "x86_64"),
        ("ARM64", "aarch64"),
    ],
)
def test_the_same_machine_under_either_name_is_the_same_machine(shipped, asked):
    m = manifest(bundle("tier4.ota.agent.v1", "1.2.0", shipped))
    assert (
        m.find_bundle(agent_type="tier4.ota.agent.v1", architecture=asked) is not None
    )


def test_a_genuinely_different_machine_still_does_not_match():
    m = manifest(bundle("tier4.ota.agent.v1", "1.2.0", "riscv64"))
    assert m.find_bundle(agent_type="tier4.ota.agent.v1", architecture="arm64") is None


def test_a_consumer_told_which_version_to_become_gets_that_one_or_nothing():
    """otaclient is told by the campaign which version it is to be; an image shipping
    a different one must not be installed as if it were."""
    m = manifest(
        bundle("tier4.otaclient.squashfs.v1", "3.15.0", "x86_64", 2),
    )
    assert (
        m.find_bundle(
            agent_type="tier4.otaclient.squashfs.v1",
            architecture="x86_64",
            version="3.15.0",
        ).size
        == 2
    )
    assert (
        m.find_bundle(
            agent_type="tier4.otaclient.squashfs.v1",
            architecture="x86_64",
            version="9.9.9",
        )
        is None
    )


@pytest.mark.parametrize(
    "bundles",
    [
        # Two versions for one consumer: which one would be "the" agent is a guess.
        [("t", "3.14.0", "x86_64"), ("t", "3.15.0", "x86_64")],
        # The same machine under its two names.
        [("t", "1.0.0", "arm64"), ("t", "1.0.0", "aarch64")],
        # One that runs anywhere beside one for a machine, in either order.
        [("t", "1.0.0", None), ("t", "1.0.0", "arm64")],
        [("t", "1.0.0", "arm64"), ("t", "1.0.0", None)],
        [("t", "1.0.0", None), ("t", "2.0.0", None)],
    ],
)
def test_a_consumer_is_never_left_to_choose_between_two_bundles(bundles):
    with pytest.raises(ValidationError, match="more than one bundle of type 't'"):
        manifest(*(bundle(*b, n=i + 1) for i, b in enumerate(bundles)))


def test_the_manifest_is_an_oci_image_manifest_with_the_empty_config():
    raw = json.loads(manifest(bundle("t", "1.0.0", "arm64")).export_metafile())
    assert raw["schemaVersion"] == 2
    assert raw["mediaType"] == IMAGE_MANIFEST
    assert raw["config"]["mediaType"] == OCI_EMPTY_JSON
    assert raw["config"]["size"] == 2
    assert raw["config"]["digest"] == (
        "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    with pytest.raises(ValidationError, match="the empty descriptor names the blob"):
        EmptyConfigDescriptor(size=2, digest=f"sha256:{'0' * 64}")
    with pytest.raises(ValidationError):
        UpdateAgentPackageManifest.parse_metafile(
            json.dumps({k: v for k, v in raw.items() if k != "config"})
        )
    with pytest.raises(ValidationError):
        UpdateAgentPackageManifest.parse_metafile(
            json.dumps(dict(raw, schemaVersion=1))
        )


def _index() -> ImageIndex:
    return ImageIndex(
        manifests=[],
        annotations=ImageIndex.Annotations.model_validate({BUILD_TOOL_VERSION: "test"}),
    )


def test_what_the_builder_adds_is_what_a_consumer_finds(tmp_path: Path):
    """utils -> blobs and index entry -> index.json -> the consumer's lookup."""
    resource_dir = tmp_path / "data"
    resource_dir.mkdir()
    agent = tmp_path / "agent.tar.gz"
    agent.write_bytes(b"agent" * 100)
    otaclient = tmp_path / "otaclient.squashfs"
    otaclient.write_bytes(b"otaclient" * 100)
    descriptor = add_update_agent_package(
        [
            (agent, UPDATE_AGENT_TYPE_PARTITION_AGENT, "2.10.0", "arm64"),
            (otaclient, UPDATE_AGENT_TYPE_OTACLIENT, "3.15.0", "x86_64"),
        ],
        resource_dir=resource_dir,
    )
    index = _index()
    index.add_update_agent_package(descriptor)

    parsed = ImageIndex.parse_metafile(index.export_metafile())
    found = parsed.find_update_agent_package()
    assert isinstance(found, UpdateAgentPackageManifest.Descriptor)
    loaded = found.load_metafile_from_resource_dir(resource_dir)
    assert (resource_dir / loaded.config.digest.digest_hex).read_bytes() == EMPTY_JSON
    bundle_ = loaded.find_bundle(
        agent_type=UPDATE_AGENT_TYPE_PARTITION_AGENT, architecture="aarch64"
    )
    assert bundle_ is not None and bundle_.annotations.version == "2.10.0"
    assert (resource_dir / bundle_.digest.digest_hex).read_bytes() == agent.read_bytes()
    assert (
        loaded.find_bundle(agent_type=UPDATE_AGENT_TYPE_OTACLIENT, architecture="arm64")
        is None
    )


def test_the_builder_refuses_what_the_schema_would(tmp_path: Path):
    resource_dir = tmp_path / "data"
    resource_dir.mkdir()
    agent = tmp_path / "agent.tar.gz"
    agent.write_bytes(b"agent")
    with pytest.raises(ValueError, match="carries nothing"):
        add_update_agent_package([], resource_dir=resource_dir)
    with pytest.raises(ValidationError, match="more than one bundle"):
        add_update_agent_package(
            [(agent, "t", "1.0.0", "arm64"), (agent, "t", "1.0.1", "arm64")],
            resource_dir=resource_dir,
        )


def test_a_finalized_or_signed_image_takes_no_package(tmp_path: Path):
    resource_dir = tmp_path / "data"
    resource_dir.mkdir()
    agent = tmp_path / "agent.tar.gz"
    agent.write_bytes(b"agent")
    descriptor = add_update_agent_package(
        [(agent, "t", "1.0.0", None)], resource_dir=resource_dir
    )
    finalized = _index()
    finalized.finalize_image(total_blobs_count=1, total_blobs_size=1)
    with pytest.raises(ValueError, match="finalized image"):
        finalized.add_update_agent_package(descriptor)
    signed = _index()
    signed.annotations.signed_at = 1
    with pytest.raises(ValueError, match="finalized image"):
        signed.add_update_agent_package(descriptor)
    assert finalized.find_update_agent_package() is None
    assert signed.find_update_agent_package() is None
