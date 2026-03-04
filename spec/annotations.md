# Pre-defined Annotations for OTA Image

OTA image v1 can be annotated/labelled with rich extra metadata to make the image self-explanatory.
The specification currently supports the following pre-defined annotations, and can be extended to support more in the future.

## Required Annotations

The required annotations are annotations that MUST be added to the OTA image.

Except for those explicitly stated, the required annotations SHOULD be provided by the caller of OTA image builder.

- **`vnd.tier4.ota.ota-image-builder.version`** *string*

  Version of the OTA image builder used to create the image.
  The OTA image builder will automatically add this annotation to the image.

- **`vnd.tier4.ota.release-key`** *string*

  The release key for this OTA image.

- **`vnd.tier4.pilot-auto.platform.ecu`** *string*

  The ECU ID of the pilot-auto platform.
  Together with `vnd.tier4.ota.release-key`, these combinations uniquely identify an image_manifest in the OTA image.

- **`vnd.tier4.pilot-auto.platform.ecu.architecture`** *string*

  The architecture of the ECU, MUST be a valid architecture name like `x86_64`, `aarch64`, etc.

- **`vnd.tier4.image.base-image`** *string*

  The base image that the original system rootfs image is built from.
  The value is corresponding to the `.webauto-ci.yml` file's `artifacts[].build.base_container_image` field.

## Optional Annotations

The optional annotations are annotations that MAY be added to the OTA image.
It is recommended to add these annotations to the OTA image to make the OTA image more self-descriptive and self-contained.

Except for those explicitly stated, the optional annotations SHOULD be provided by the caller of OTA image builder.

- **`vnd.tier4.pilot-auto.project`** *string*

  OPTIONAL, recommended. The pilot-auto project name.

- **`vnd.tier4.pilot-auto.platform`** *string*

  OPTIONAL, recommended. The code name of the pilot-auto project.

- **`vnd.tier4.pilot-auto.project.source-repo`** *string*

  OPTIONAL, recommended. The source code repository for the corresponding pilot-auto project.

- **`vnd.tier4.pilot-auto.project.version`** *string*

  OPTIONAL. The version of the pilot-auto project.

- **`vnd.tier4.pilot-auto.project.release-commit`** *string*

  OPTIONAL, recommended. The git commit of the pilot-auto project from which this OTA image is built.

- **`vnd.tier4.pilot-auto.project.release-branch`** *string*

  OPTIONAL, recommended. The git branch of the pilot-auto project from which this OTA image is built.

- **`vnd.tier4.web-auto.project`** *string*

  OPTIONAL, recommended. The web-auto project name.

- **`vnd.tier4.web-auto.project-id`** *string*

  OPTIONAL. The web-auto project ID.

- **`vnd.tier4.web-auto.catalog`** *string*

  OPTIONAL. The web-auto catalog name.

- **`vnd.tier4.web-auto.catalog-id`** *string*

  OPTIONAL. The web-auto catalog ID.

- **`vnd.tier4.web-auto.env`** *string*

  OPTIONAL, recommended. The web-auto environment name, like `dev`, `stg`, `prd`.

- **`vnd.tier4.web-auto.cicd.release-id`** *string*

  OPTIONAL, recommended. The release ID for this build on the evaluator firmware release.

- **`vnd.tier4.web-auto.cicd.release-name`** *string*

  OPTIONAL, recommended. The release display name for this build on the evaluator firmware release.

- **`vnd.tier4.pilot-auto.platform.ecu.hardware-model`** *string*

  OPTIONAL, recommended. The hardware model of the ECU. This information should be provided by the user.

- **`vnd.tier4.pilot-auto.platform.ecu.hardware-series`** *string*

  OPTIONAL, recommended. The hardware series of the ECU. This information should be provided by the user.

- **`vnd.tier4.image.os`** *string*

  OPTIONAL, recommended. The operating system of the original system rootfs image, like `Ubuntu`, `Debian`, etc.

- **`vnd.tier4.image.os.version`** *string*

  OPTIONAL, recommended. The version of the operating system of the original system rootfs image. For `Ubuntu`, like `20.04`, `22.04`, etc.

## Internal Used Annotations

The internal used annotations are annotations that are automatically populated by the OTA image builder.
These annotations SHOULD NOT be provided by the caller.

- **`vnd.tier4.ota.image.created-at`** *integer*

  The Unix timestamp when the OTA image is created.
  This is used by OTA image builder to indicate the image has been finalized.

- **`vnd.tier4.ota.image.signed-at`** *integer*

  The Unix timestamp when the OTA image is signed.

- **`vnd.tier4.ota.image.blobs-count`** *integer*

  The total number of blobs in this OTA image's blob storage.

- **`vnd.tier4.ota.image.blobs-size`** *integer*

  The total size in bytes of all blobs in the OTA image.

- **`vnd.nvidia.jetson.bsp_ver`** *string*

  (If this OTA image payload is for NVIDIA Jetson device) The NVIDIA Jetson BSP version of the image.

- **`vnd.tier4.image.rootfs.regular-files-count`** *integer*

  The number of regular files in the original system rootfs of this OTA image payload.

- **`vnd.tier4.image.rootfs.non-regular-files-count`** *integer*

  The number of non-regular files (symlinks, etc.) in the original system rootfs of this OTA image payload.

- **`vnd.tier4.image.rootfs.dirs-count`** *integer*

  The number of directories in the original system rootfs of this OTA image payload.

- **`vnd.tier4.image.rootfs.unique-files-entries-count`** *integer*

  The number of unique file entries (deduplicated by SHA256) in the original system rootfs of this OTA image payload.

- **`vnd.tier4.image.rootfs.unique-files-entries-size`** *integer*

  The total size in bytes of all unique file entries in the original system rootfs of this OTA image payload.

- **`vnd.tier4.image.rootfs.size`** *integer*

  The total size in bytes of the original system rootfs of this OTA image payload.

