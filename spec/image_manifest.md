# Image Manifest

The OTA image spec version 1 image manifest is an OCI image manifest with `artifactType` set to `application/vnd.tier4.ota.file-based-ota-image.v1`, which represents an OTA image payload within the OTA image.
An image manifest is uniquely identified by the combination of `ecu_id` and `ota_release_key` in its annotations.

Schema as code: [`image_manifest/schema.py`](../src/ota_image_libs/v1/image_manifest/schema.py)

## Media Type

`application/vnd.oci.image.manifest.v1+json`

## Image Manifest Schema

- **`schemaVersion`** *int*

    This REQUIRED field specifies the image_manifest's schema version.
    For OTA image version 1, the value MUST be `2`.

- **`mediaType`** *string*

    This REQUIRED field specifies the media type of the image manifest.
    The value MUST be `application/vnd.oci.image.manifest.v1+json` for OTA image version 1.

- **`artifactType`** *string*

    This REQUIRED field specifies the artifact type of the image manifest.
    The value MUST be `application/vnd.tier4.ota.file-based-ota-image.v1`.

- **`config`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)*

    This REQUIRED field specifies an OCI descriptor that points to the [image_config](image_config.md) for this image payload.

- **`layers`** *array of [OCI descriptors](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)*

    This REQUIRED field specifies a list of OCI descriptors.
    For OTA image payload manifest, the array MUST contain exactly one entry, which points to the [file_table](file_table.md) of this image payload.
    The mediaType of the descriptor is either `application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3` for uncompressed, or `application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3+zstd` for zstd-compressed.

- **`annotations`** *string-string map*

    This REQUIRED field specifies the annotations for this image manifest.
    See below chapter `Annotations for Image Manifest` for more details.

## Annotations for Image Manifest

### Required Annotations

- **`vnd.tier4.pilot-auto.platform.ecu`** *string*

    This REQUIRED annotation specifies the ECU identifier for this image payload.
    Together with `vnd.tier4.ota.release-key`, this combination uniquely identifies an image manifest in the OTA image.

- **`vnd.tier4.ota.release-key`** *string*

    This REQUIRED annotation specifies the release key for this image payload.
    The value MUST be either `dev` or `prd`.
    Defaults to `dev` if not specified.

- **`vnd.tier4.pilot-auto.platform.ecu.architecture`** *string*

    This REQUIRED annotation specifies the CPU architecture of the ECU.
    The value MUST be a valid architecture name like `x86_64`, `aarch64`, etc.

### Optional Annotations

- **`vnd.tier4.pilot-auto.platform`** *string*

    This OPTIONAL annotation specifies the code name of the pilot-auto platform.

- **`vnd.tier4.pilot-auto.platform.ecu.hardware-model`** *string*

    This OPTIONAL annotation specifies the hardware model of the ECU.

- **`vnd.tier4.pilot-auto.platform.ecu.hardware-series`** *string*

    This OPTIONAL annotation specifies the hardware series of the ECU.

- **`vnd.nvidia.jetson.bsp_ver`** *string*

    This OPTIONAL annotation specifies the NVIDIA Jetson BSP version, if applicable.

## Example image_manifest

```json
{
  "config": {
    "size": 712,
    "digest": "sha256:a1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef",
    "mediaType": "application/vnd.tier4.ota.file-based-ota-image.config.v1+json"
  },
  "layers": [
    {
      "size": 49923445,
      "digest": "sha256:5743e31b0f245892d6203d7ca3c688fa8046c92721c4518cbc28371f05e1ac56",
      "mediaType": "application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3+zstd"
    }
  ],
  "annotations": {
    "vnd.tier4.pilot-auto.platform.ecu": "autoware",
    "vnd.tier4.ota.release-key": "prd",
    "vnd.tier4.pilot-auto.platform": "example-platform",
    "vnd.tier4.pilot-auto.platform.ecu.architecture": "x86_64",
    "vnd.tier4.pilot-auto.platform.ecu.hardware-model": "orin-agx",
    "vnd.tier4.pilot-auto.platform.ecu.hardware-series": "orin"
  },
  "schemaVersion": 2,
  "mediaType": "application/vnd.oci.image.manifest.v1+json",
  "artifactType": "application/vnd.tier4.ota.file-based-ota-image.v1"
}
```
