# Copyright 2025 TIER IV, INC. All rights reserved.
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
#
# fmt: off

#
# ------ OCI specific media types ------ #
#
# ref: https://github.com/opencontainers/image-spec/blob/main/media-types.md

IMAGE_INDEX = "application/vnd.oci.image.index.v1+json"
IMAGE_MANIFEST = "application/vnd.oci.image.manifest.v1+json"

#
# ------ OTA specific media types ------ #
#

OTA_IMAGE_ARTIFACT = "application/vnd.tier4.ota.file-based-ota-image.v1"
OTA_IMAGE_FILETABLE = "application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3"
OTA_IMAGE_FILETABLE_ZSTD = "application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3+zstd"
OTA_IMAGE_RESOURCETABLE = "application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3"
OTA_IMAGE_RESOURCETABLE_ZSTD = "application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3+zstd"
OTA_IMAGE_CONFIG_JSON = "application/vnd.tier4.ota.file-based-ota-image.config.v1+json"
SYS_CONFIG_YAML_INCORRECT = "application/vnd.tier4.ota.file-based-ota-image.config.v1+yaml"
SYS_CONFIG_YAML = "application/vnd.tier4.ota.sys-config.v1+yaml"

#
# ------ OTAClient Package media types ------ #
#
OTACLIENT_PACKAGE_ARTIFACT = "application/vnd.tier4.otaclient.release-package.v1"
OTACLIENT_PACKAGE_MANIFEST = "application/vnd.tier4.otaclient.release-package.manifest.v1+json"
OTACLIENT_APP_IMAGE = "application/vnd.tier4.otaclient.release-package.v1.squashfs"
