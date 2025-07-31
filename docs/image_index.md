# Image Index

For OTA Image version 1, the image index.json is a valid OCI image index. The mediaType is still `application/vnd.oci.image.index.v1+json`.

## Typeical index.json for OTA Image version 1

A typical OTA image contains the following types of artifacts:

- **OTA image payload**

  Payload that can be used by OTAClient to update an ECU.
  The artifactType of the payload is `application/vnd.tier4.ota.file-based-ota-image.v1`.

  Multiple image payloads can be included in an OTA image.
  Image payload can be uniquely identified by the `ecu_id` and `ota_release_key`.

- **OTAClient release package**

  Payload of the OTAClient release package. The artifactType of the payload is `application/vnd.tier4.otaclient.release-package.v1`.

  OTAClient can use this payload to first update itself before actually doing the OTA.

- **resource_table**

  Payload of the OTA image blob storage `resource_table`. 
  The `resource_table` is a SQLite3 database that contains the information of all the resources(blobs) in this OTA image, including the digest, size, and filter_applied if this OTA image is optimized when finalized.

  The artifactType of the payload is `application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3`, normally it will be compressed with `zstd`, which can be identified by the suffix `+zstd` in the artifactType.

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
