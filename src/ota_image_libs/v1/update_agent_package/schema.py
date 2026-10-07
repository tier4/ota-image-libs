"""The update agent release package: the agent that applies an OTA image, shipped in it.

One campaign, two halves. A consumer whose own agent is older than the bundle here
installs it, hands over to it, and that one applies the payload; a consumer already
running something at least as new ignores it.

One entry may carry several bundles. A bundle says what it is (`type`, opaque to the
image) and what it runs on (`architecture`), and a consumer takes only the one it
implements -- which is what lets a single image serve ECUs running different agents.

`otaclient_package` is the same concept for otaclient specifically and predates this.
"""

from __future__ import annotations

from typing import List, Union

from pydantic import Field

from ota_image_libs.common import (
    AliasEnabledModel,
    MediaType,
    MetaFileBase,
    MetaFileDescriptor,
    OCIDescriptor,
    SchemaVersion,
)
from ota_image_libs.common.model_spec import ArtifactType
from ota_image_libs.v1.annotation_keys import (
    UPDATE_AGENT_ARCH,
    UPDATE_AGENT_TYPE,
    UPDATE_AGENT_VERSION,
)
from ota_image_libs.v1.media_types import (
    IMAGE_MANIFEST,
    UPDATE_AGENT_BUNDLE,
    UPDATE_AGENT_PACKAGE_ARTIFACT,
    UPDATE_AGENT_PACKAGE_MANIFEST,
)

ARCH_ALIASES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "arm64",
    "arm64": "arm64",
}
"""The same machine under the names the tools in this stack use for it."""


def normalize_arch(arch: Union[str, None]) -> Union[str, None]:
    """One name per machine, or the name as given when it is not one we know."""
    if arch is None:
        return None
    return ARCH_ALIASES.get(arch.lower(), arch)


# fmt: off
class UpdateAgentBundleDescriptor(OCIDescriptor):
    """One agent, as this image ships it."""

    class Annotations(AliasEnabledModel):
        type: str = Field(alias=UPDATE_AGENT_TYPE)
        version: str = Field(alias=UPDATE_AGENT_VERSION)
        architecture: Union[str, None] = Field(alias=UPDATE_AGENT_ARCH, default=None)

    MediaType = MediaType[UPDATE_AGENT_BUNDLE]

    annotations: Annotations = Field(...)


class UpdateAgentPackageManifest(MetaFileBase):
    class Descriptor(MetaFileDescriptor["UpdateAgentPackageManifest"]):
        MediaType = MediaType[UPDATE_AGENT_PACKAGE_MANIFEST]
        ArtifactType = ArtifactType[UPDATE_AGENT_PACKAGE_ARTIFACT]

    SchemaVersion = SchemaVersion[1]
    MediaType = MediaType[IMAGE_MANIFEST]
    ArtifactType = ArtifactType[UPDATE_AGENT_PACKAGE_ARTIFACT]

    layers: List[UpdateAgentBundleDescriptor]
    # fmt: on

    def find_bundle(
        self,
        *,
        agent_type: str,
        architecture: Union[str, None] = None,
        version: Union[str, None] = None,
    ) -> Union[UpdateAgentBundleDescriptor, None]:
        """The bundle this consumer can run, or None.

        `version` pins it to exactly that one, for a consumer told by the campaign
        which version it is to become. Left out, the newest thing the image ships for
        this consumer is returned and comparing it is the consumer's business.

        Architecture is matched only when the bundle states one: a bundle that does not
        is one the publisher says runs anywhere. Names go through `normalize_arch`.
        """
        _want = normalize_arch(architecture)
        for _b in self.layers:
            if _b.annotations.type != agent_type:
                continue
            if version is not None and _b.annotations.version != version:
                continue
            _have = normalize_arch(_b.annotations.architecture)
            if _want is not None and _have is not None and _have != _want:
                continue
            return _b
        return None
