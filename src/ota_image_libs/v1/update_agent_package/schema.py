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
"""The update agent release package: the agent that applies an OTA image, shipped in it.

One campaign, two halves. A consumer whose own agent is older than the bundle here
installs it, hands over to it, and that one applies the payload; a consumer already
running something at least as new ignores it.

One entry may carry several bundles. A bundle says what it is (`type`, one of the
`UPDATE_AGENT_TYPE_*` values or another consumer's) and what it runs on
(`architecture`), and a consumer takes only the one it implements -- which is what
lets a single image serve ECUs running different agents. Specification:
spec/update_agent_package.md.

`otaclient_package` is the same concept for otaclient specifically and predates this.
"""

from __future__ import annotations

from hashlib import sha256
from typing import List, Union

from pydantic import Field, model_validator
from typing_extensions import Self

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
    OCI_EMPTY_JSON,
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


EMPTY_JSON = b"{}"
"""The content of the OCI empty descriptor's blob."""


class EmptyConfigDescriptor(OCIDescriptor):
    """The OCI empty descriptor: the config of a manifest that has nothing to configure,
    which an OCI image manifest names all the same."""

    MediaType = MediaType[OCI_EMPTY_JSON]

    @model_validator(mode="after")
    def _is_the_empty_blob(self) -> Self:
        if (
            self.size != len(EMPTY_JSON)
            or self.digest.digest_hex != sha256(EMPTY_JSON).hexdigest()
        ):
            raise ValueError(
                f"the empty descriptor names the blob {EMPTY_JSON!r}, not {self.digest}"
            )
        return self


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

    SchemaVersion = SchemaVersion[2]
    MediaType = MediaType[IMAGE_MANIFEST]
    ArtifactType = ArtifactType[UPDATE_AGENT_PACKAGE_ARTIFACT]

    config: EmptyConfigDescriptor
    layers: List[UpdateAgentBundleDescriptor]
    # fmt: on

    @model_validator(mode="after")
    def _one_bundle_per_consumer(self) -> Self:
        """At most one bundle per type and machine, and a bundle that names no machine
        is the only one of its type: a consumer is never left to choose between two."""
        if not self.layers:
            raise ValueError("an update agent package with no bundles carries nothing")
        _seen: dict = {}
        for _b in self.layers:
            _type = _b.annotations.type
            _arch = normalize_arch(_b.annotations.architecture)
            _taken = _seen.setdefault(_type, set())
            if None in _taken or (_taken and _arch is None) or _arch in _taken:
                raise ValueError(
                    f"more than one bundle of type {_type!r} for "
                    f"{_arch or 'any machine'}: a consumer could take either"
                )
            _taken.add(_arch)
        return self

    def find_bundle(
        self,
        *,
        agent_type: str,
        architecture: Union[str, None] = None,
        version: Union[str, None] = None,
    ) -> Union[UpdateAgentBundleDescriptor, None]:
        """The bundle this consumer can run, or None.

        There is at most one per type and machine, so this is that one, whatever its
        version: comparing it with what runs is the consumer's business. `version`
        takes it only when it is exactly that one, for a consumer told by the campaign
        which version it is to become.

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
