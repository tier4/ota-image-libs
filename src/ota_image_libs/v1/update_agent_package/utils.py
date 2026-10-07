"""Putting an update agent release package into an OTA image."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple, Union

from ota_image_libs.v1.annotation_keys import (
    UPDATE_AGENT_ARCH,
    UPDATE_AGENT_TYPE,
    UPDATE_AGENT_VERSION,
)
from ota_image_libs.v1.update_agent_package.schema import (
    UpdateAgentBundleDescriptor,
    UpdateAgentPackageManifest,
)


def add_update_agent_package(
    bundles: Iterable[Tuple[Path, str, str, Union[str, None]]],
    *,
    resource_dir: Path,
) -> UpdateAgentPackageManifest.Descriptor:
    """Add one entry carrying every bundle given.

    Each bundle is (file, type, version, architecture).
    """
    _layers = []
    for _file, _type, _version, _arch in bundles:
        _annotations = {UPDATE_AGENT_TYPE: _type, UPDATE_AGENT_VERSION: _version}
        if _arch:
            _annotations[UPDATE_AGENT_ARCH] = _arch
        _layers.append(
            UpdateAgentBundleDescriptor.add_file_to_resource_dir(
                _file, resource_dir, annotations=_annotations
            )
        )
    if not _layers:
        raise ValueError("an update agent package with no bundles carries nothing")
    return UpdateAgentPackageManifest.Descriptor.export_metafile_to_resource_dir(
        UpdateAgentPackageManifest(layers=_layers), resource_dir
    )
