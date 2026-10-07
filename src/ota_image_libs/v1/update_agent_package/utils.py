"""Putting an update agent release package into an OTA image."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple, Union

from ota_image_libs.v1.annotation_keys import (
    UPDATE_AGENT_ARCH,
    UPDATE_AGENT_TYPE,
    UPDATE_AGENT_VERSION,
)
from ota_image_libs.v1.media_types import UPDATE_AGENT_TYPE_OTACLIENT
from ota_image_libs.v1.otaclient_package.schema import (
    SQUASHFS,
    OTAClientOriginManifest,
)
from ota_image_libs.v1.otaclient_package.utils import MANIFEST_JSON
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


def bundles_from_otaclient_release(
    release_dir: Path,
) -> list[Tuple[Path, str, str, str]]:
    """The squashfs images an otaclient release directory holds, as bundles.

    Its manifest.json is read for what is in the directory and then left behind: the
    entry says everything a consumer needs on each bundle itself, so there is nothing
    for a second metadata file to add.
    """
    _manifest = OTAClientOriginManifest.model_validate_json(
        (release_dir / MANIFEST_JSON).read_text()
    )
    return [
        (
            release_dir / _p.filename,
            UPDATE_AGENT_TYPE_OTACLIENT,
            _p.version,
            _p.architecture,
        )
        for _p in _manifest.packages
        if _p.type == SQUASHFS
    ]
