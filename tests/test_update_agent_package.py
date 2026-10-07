"""The update agent release package: one entry, several bundles, each for a consumer.

The generic form of the otaclient release package. What it has to get right is the
picking: a consumer must take only a bundle it implements and can run, because what it
does with one is install it and then execute it as root.
"""

from __future__ import annotations

import pytest

from ota_image_libs.v1.annotation_keys import (
    UPDATE_AGENT_ARCH,
    UPDATE_AGENT_TYPE,
    UPDATE_AGENT_VERSION,
)
from ota_image_libs.v1.media_types import UPDATE_AGENT_BUNDLE
from ota_image_libs.v1.update_agent_package.schema import (
    UpdateAgentBundleDescriptor,
    UpdateAgentPackageManifest,
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
    return UpdateAgentPackageManifest(layers=list(bundles))


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
        bundle("tier4.otaclient.squashfs.v1", "3.14.0", "x86_64", 1),
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
