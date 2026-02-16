from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ota_image_libs.common.metafile_base import MetaFileBase, MetaFileDescriptor
from ota_image_libs.common.model_spec import MediaTypeWithAlt as MediaTypeWithAltT
from ota_image_libs.v1.media_types import (
    SYS_CONFIG_YAML,
    SYS_CONFIG_YAML_BACKWARD_COMPATIBLE,
)


class SysConfig(MetaFileBase):
    # NOTE(20260116): for fixing the issue of using wrong media_type previously.
    class Descriptor(MetaFileDescriptor["SysConfig"]):
        MediaType = MediaTypeWithAltT[
            SYS_CONFIG_YAML, SYS_CONFIG_YAML_BACKWARD_COMPATIBLE
        ]

    MediaType = MediaTypeWithAltT[SYS_CONFIG_YAML, SYS_CONFIG_YAML_BACKWARD_COMPATIBLE]

    hostname: str
    extra_mount: list[MountCfg] | None = None
    swap: SwapCfg | None = None
    sysctl: list[str] | None = None
    persist_files: list[str] | None = None
    network: dict[str, Any] | None = None
    otaclient_ecu_info: dict[str, Any] | None = Field(
        alias="otaclient.ecu_info", default=None
    )
    otaclient_proxy_info: dict[str, Any] | None = Field(
        alias="otaclient.proxy_info", default=None
    )


class SwapCfg(BaseModel):
    filepath: str
    size: int  # in GiB


class MountCfg(BaseModel):
    file_system: str
    mount_point: str
    type: str
    options: str | None = None
