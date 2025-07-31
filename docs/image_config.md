# Image Config

## Media Type

`application/vnd.tier4.ota.file-based-ota-image.config.v1+json`

## Image Config Schema

- **`schemaVersion`** *int*

    This REQUIRED field specifies the image_config's schema version.
    For `application/vnd.tier4.ota.file-based-ota-image.config.v1+json`, the value MUST be `1`.

- **`mediaType`** *string*

    This REQUIRED field specifies the media type of the image.
    The value MUST be `application/vnd.tier4.ota.file-based-ota-image.config.v1+json`.

- **`resource_digest_alg`** *string*

    This REQUIRED field specifies the digest algorithm used for the image resource.
    The value MUST be `sha256` for OTA Image version 1.

- **`description`** *string*

    This OPTIONAL field contains the description of this image payload.

- **`created`** *string*

    This OPTIONAL field specifies the date and time when the original system rootfs image was created, or the time when this image payload is added into the OTA image.
    The value MUST be in ISO8601 format (e.g., `2009-01-01T09:00:00Z`).

- **`architecture`** *string*

    This REQUIRED field specifies the architecture of the image payload.
    The value MUST be valid architecture code like: `x86_64`, `aarch64`, etc.

- **`os`** *string*

    This OPTIONAL field specifies the operating system of the image payload.
    The value MUST be valid OS code like: `linux`, `windows`, etc.

- **`os_version`** *string*

    This OPTIONAL field specifies the version of the operating system of the image payload, like `20.04`, `22.04` for Ubuntu based system, etc.

- **`sys_config`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)*

    This OPTIONAL field specifies an OCI desriptor points to a [sys_config](sys_config.md) bound to this image_config.

- **`file_table`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)*

    This REQUIRED field specifies an OCI descriptor points to [file_table](file_table.md) of the original system rootfs image this image_config based on.

- **`labels`** *string-string map*

    This REQUIRED field specifies the statistics of the original system rootfs image.
    See below chapter `Annotations for Image Config` for more details.

## Annotations for Image Config

- **`base_image`** *string*

    This REQUIRED annotation specifies the base image of the original system rootfs image.
    The value is corresponding to the `.webauto-ci.yml` file's `artifacts[].build.base_container_image` field.

- **`os`** *string*

    This OPTIONAL annotation specifies the operating system of the original system rootfs image.
    The value MUST be valid OS name like: `Ubuntu`, `Debian`, etc.

- **`os_version`** *string*

    This OPTIONAL annotation specifies the version of the operating system of the original system rootfs image, like `20.04`, `22.04` for Ubuntu based system, etc.

- **`vnd.tier4.ota.image.blobs-count`** *int*

  **`vnd.tier4.image.rootfs.unique-files-entries-count`** *int*

    This REQUIRED annotation specifies the number of blobs in the image payload.
    For file-based OTA image, these two fields have the same value.

- **`vnd.tier4.ota.image.blobs-size`** *int*

  **`vnd.tier4.image.rootfs.unique-files-entries-size`** *int*
    
    This REQUIRED annotation specifies the total size of all blobs in the image payload.
    For file-based OTA image, these two fields have the same value.

- **`vnd.tier4.image.rootfs.size`** *int*

    This REQUIRED annotation specifies the size of the original system rootfs image.

- **`vnd.tier4.image.rootfs.regular-files-count`** *int*

    This REQUIRED annotation specifies the number of regular files in the original system rootfs image.

- **`vnd.tier4.image.rootfs.dirs-count`** *int*

    This REQUIRED annotation specifies the number of directories in the original system rootfs image.

- **`vnd.tier4.image.rootfs.non-regular-files-count`** *int*

    This REQUIRED annotation specifies the number of non-regular files in the original system rootfs image.

## Example image_config

```json
{
  "resource_digest_alg": "sha256",
  "description": "Example OTA image with annotations for add-image cmd",
  "created": "2025-07-15T15:43:32Z",
  "architecture": "x86_64",
  "os": "Ubuntu",
  "os.version": "22.04",
  "sys_config": {
    "size": 45,
    "digest": "sha256:1e9e6d4088b9fa8c8e3dece14120be3047937e61248e4de89267cdb0f525e370",
    "mediaType": "application/vnd.tier4.ota.file-based-ota-image.config.v1+yaml"
  },
  "file_table": {
    "size": 49923445,
    "digest": "sha256:5743e31b0f245892d6203d7ca3c688fa8046c92721c4518cbc28371f05e1ac56",
    "mediaType": "application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3+zstd"
  },
  "labels": {
    "vnd.tier4.image.base-image": "ubuntu:22.04",
    "vnd.tier4.image.os": "Ubuntu",
    "vnd.tier4.image.os.version": "22.04",
    "vnd.tier4.ota.image.blobs-count": 347762,
    "vnd.tier4.ota.image.blobs-size": 22096030268,
    "vnd.tier4.image.rootfs.size": 355481,
    "vnd.tier4.image.rootfs.regular-files-count": 451762,
    "vnd.tier4.image.rootfs.non-regular-files-count": 51149,
    "vnd.tier4.image.rootfs.dirs-count": 107650,
    "vnd.tier4.image.rootfs.unique-files-entries-count": 355481,
    "vnd.tier4.image.rootfs.unique-files-entries-size": 355481
  },
  "schemaVersion": 1,
  "mediaType": "application/vnd.tier4.ota.file-based-ota-image.config.v1+json"
}
```