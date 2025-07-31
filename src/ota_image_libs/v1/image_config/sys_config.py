from __future__ import annotations

from typing import Any, Dict, List, Union

from pydantic import BaseModel, Field

from ota_image_libs.common.metafile_base import MetaFileBase, MetaFileDescriptor
from ota_image_libs.common.model_spec import MediaType
from ota_image_libs.v1.media_types import SYS_CONFIG_YAML


class SysConfig(MetaFileBase):
    class Descriptor(MetaFileDescriptor["SysConfig"]):
        MediaType = MediaType[SYS_CONFIG_YAML]

    MediaType = MediaType[SYS_CONFIG_YAML]

    hostname: str
    extra_mount: Union[List[MountCfg], None] = None
    swap: Union[SwapCfg, None] = None
    sysctl: Union[List[str], None] = None
    persist_files: Union[List[str], None] = None
    network: Union[Dict[str, Any], None] = None
    otaclient_ecu_info: Union[Dict[str, Any], None] = Field(
        alias="otaclient.ecu_info", default=None
    )
    otaclient_proxy_info: Union[Dict[str, Any], None] = Field(
        alias="otaclient.proxy_info", default=None
    )


class SwapCfg(BaseModel):
    filepath: str
    size: int  # in GiB


class MountCfg(BaseModel):
    file_system: str
    mount_point: str
    type: str
    options: Union[str, None] = None
