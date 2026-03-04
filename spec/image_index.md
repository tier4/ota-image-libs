# Image Index

Image index is the top-level entry point of an OTA image.
It is an [OCI image index](https://github.com/opencontainers/image-spec/blob/main/image-index.md)(`index.json`) that lists all manifests and metadata for the OTA image.

Schema as code: [`image_index/schema.py`](../src/ota_image_libs/v1/image_index/schema.py)

## Media Type

`application/vnd.oci.image.index.v1+json`

## Image Index Schema

- **`schemaVersion`** *int*

    This REQUIRED field specifies the OCI image index schema version.
    The value MUST be `2` (following the OCI image index specification).

- **`mediaType`** *string*

    This REQUIRED field specifies the media type of the image index.
    The value MUST be `application/vnd.oci.image.index.v1+json` for OTA image index.

- **`manifests`** *array of [OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)*

    This REQUIRED field lists all manifest entries in this OTA image. Each entry is an OCI descriptor that may be one of the following types:

    - **OTA image payload** — An [image manifest](image_manifest.md) descriptor with `artifactType` set to `application/vnd.tier4.ota.file-based-ota-image.v1`.
    Each descriptor MUST have `annotations` containing `vnd.tier4.pilot-auto.platform.ecu` and `vnd.tier4.ota.release-key`, which together uniquely identify the payload. Multiple image payloads can be included in a single OTA image.
    OTAClient uses it to update the target ECU.

    - **OTAClient release package** — An [OTAClient package manifest](otaclient_package.md) descriptor with `artifactType` set to `application/vnd.tier4.otaclient.release-package.v1`.
    OTAClient can use this to update itself before performing the OTA.

    - **Resource table** — A [resource table](resource_table.md) descriptor identified by its `mediaType` (`application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3` or `application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3+zstd`). At most one resource table entry exists in the manifests list.

- **`annotations`** *string-string map*

    This REQUIRED field contains annotations for the OTA image as a whole. See the [Annotations for Image Index](#annotations-for-image-index) section below.

## Annotations for Image Index

The image index annotations describe the OTA image as a whole. All annotation keys are documented in [annotations.md](annotations.md).

### Internal (automatically populated)

The following annotations SHOULD be set by the OTA image builder implementation:

- **`vnd.tier4.ota.ota-image-builder.version`** *string*:
  Version of the OTA image builder.
  This annotation SHOULD be set by the OTA image builder for this OTA image.

- **`vnd.tier4.ota.image.created-at`** *integer*:
  Unix timestamp when the image is finalized.
  Presence of this field indicates the image is finalized and no further payloads can be added.

- **`vnd.tier4.ota.image.signed-at`** *integer*":
  Unix timestamp when the image is signed.

- **`vnd.tier4.ota.image.blobs-count`** *integer*:
  Total number of blobs in the blob storage.

- **`vnd.tier4.ota.image.blobs-size`** *integer*:
  Total size in bytes of all blobs in the blob storage.

### Optional

- **`vnd.tier4.pilot-auto.platform`** *string* — The pilot-auto platform code name.
- **`vnd.tier4.pilot-auto.project.source-repo`** *string* — Build source code repository URL.
- **`vnd.tier4.pilot-auto.project.version`** *string* — Project version.
- **`vnd.tier4.pilot-auto.project.release-commit`** *string* — Git commit hash for the build source.
- **`vnd.tier4.pilot-auto.project.release-branch`** *string* — Git branch name for the build source.
- **`vnd.tier4.web-auto.project`** *string* — Web-auto project name.
- **`vnd.tier4.web-auto.project-id`** *string* — Web-auto project ID.
- **`vnd.tier4.web-auto.catalog`** *string* — Web-auto catalog name.
- **`vnd.tier4.web-auto.catalog-id`** *string* — Web-auto catalog ID.
- **`vnd.tier4.web-auto.env`** *string* — Web-auto environment name (e.g., `dev`, `stg`, `prd`).
- **`vnd.tier4.web-auto.cicd.release-id`** *string* — CI/CD release ID.
- **`vnd.tier4.web-auto.cicd.release-name`** *string* — CI/CD release display name.

## Example index.json

```json
{
  "manifests": [
    {
      "size": 818,
      "digest": "sha256:f9e86a954815e8969fee280a9570e0312f388e0efe51a3a094f4ce80abbfe327",
      "annotations": {
        "vnd.tier4.pilot-auto.platform.ecu": "autoware",
        "vnd.tier4.ota.release-key": "prd"
      },
      "mediaType": "application/vnd.oci.image.manifest.v1+json",
      "artifactType": "application/vnd.tier4.ota.file-based-ota-image.v1"
    },
    {
      "size": 819,
      "digest": "sha256:07465d7c1effe5a8029f211d8d9939cc7e4e842d206dbe4db37d586d4569c79e",
      "annotations": {
        "vnd.tier4.pilot-auto.platform.ecu": "autoware2",
        "vnd.tier4.ota.release-key": "prd"
      },
      "mediaType": "application/vnd.oci.image.manifest.v1+json",
      "artifactType": "application/vnd.tier4.ota.file-based-ota-image.v1"
    },
    {
      "size": 818,
      "digest": "sha256:5dec2a9e72c5f954fac558ddbafb7dcc851d280b7a910940e3299b28fefe9182",
      "annotations": {
        "vnd.tier4.pilot-auto.platform.ecu": "autoware",
        "vnd.tier4.ota.release-key": "dev"
      },
      "mediaType": "application/vnd.oci.image.manifest.v1+json",
      "artifactType": "application/vnd.tier4.ota.file-based-ota-image.v1"
    },
    {
      "size": 819,
      "digest": "sha256:b09b80bc2d44aaf4311376c30fdfc5e7471d8b06d542d4de263bd83477c90ed0",
      "annotations": {
        "vnd.tier4.pilot-auto.platform.ecu": "autoware2",
        "vnd.tier4.ota.release-key": "dev"
      },
      "mediaType": "application/vnd.oci.image.manifest.v1+json",
      "artifactType": "application/vnd.tier4.ota.file-based-ota-image.v1"
    },
    {
      "size": 1045,
      "digest": "sha256:2f096d6eeb6f6e64d2ead16c4ac9d1219609d8b2af61706c641e48d450a23132",
      "mediaType": "application/vnd.tier4.otaclient.release-package.manifest.v1+json",
      "artifactType": "application/vnd.tier4.otaclient.release-package.v1"
    },
    {
      "size": 41942700,
      "digest": "sha256:37c3be53351291653792bb20c1a70562163518cad39da0a3f103d9cb381707cc",
      "mediaType": "application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3+zstd"
    }
  ],
  "annotations": {
    "vnd.tier4.ota.ota-image-builder.version": "1.0.0",
    "vnd.tier4.ota.image.created-at": 1753436298,
    "vnd.tier4.ota.image.signed-at": 1753436298,
    "vnd.tier4.ota.image.blobs-count": 246893,
    "vnd.tier4.ota.image.blobs-size": 9734227234,
    "vnd.tier4.pilot-auto.platform": "example-platform",
    "vnd.tier4.pilot-auto.project.source-repo": "https://github.com/tier4/ota-image-libs",
    "vnd.tier4.pilot-auto.project.version": "1.0.0",
    "vnd.tier4.pilot-auto.project.release-commit": "abcdef1234567890",
    "vnd.tier4.pilot-auto.project.release-branch": "main",
    "vnd.tier4.web-auto.project": "some-project",
    "vnd.tier4.web-auto.catalog": "some-catalog",
    "vnd.tier4.web-auto.env": "dev"
  },
  "schemaVersion": 2,
  "mediaType": "application/vnd.oci.image.index.v1+json"
}
```
