# Pre-defined Annotations for OTA Image

## Required Annotations

The required annotations are annotations that MUST be added to the OTA image.

Except for explictly stated, the required annotations SHOULD be provided by the caller of OTA image builder.

- **`vnd.tier4.ota.ota-image-builder.version`** *string*

  Version of the OTA image builder used to create the image.
  The OTA image builder will automatically add this annotation to the image.

- **`vnd.tier4.ota.release-key`** *string*  

  The release key for this OTA image.

- **`vnd.tier4.pilot-auto.platform.ecu`** *string*  

  The ECU ID of the pilot-auto platform.
  Together with `vnd.tier4.ota.release-key`, these combinations uniquely identify an image_manifest in the OTA image.

- **`vnd.tier4.pilot-auto.platform.ecu.architecture`** *string*  

  The architecture of the ECU, MUST be valid architecture name like `x86_64`, `aarch64`, etc.

- **`vnd.tier4.image.base-image`** *string*

  The base image of the original system rootfs image built from.
  The value is corresponding to the `.webauto-ci.yml` file's `artifacts[].build.base_container_image` field.

## Optional Annotations

The optional annotations are annotations that MAY be added to the OTA image.
It is recommended to add these annotations to the OTA image to make the OTA image more self-descriptive and self-contained.

Except for explictly stated, the required annotations SHOULD be provided by the caller of OTA image builder.

- **`vnd.tier4.pilot-auto.platform`** *string*

  OPTIONAL, recommended. The code name of pilot-auto project.

- **`vnd.tier4.pilot-auto.project.source-repo`** *string*

  OPTIONAL, recommended. The source code repository for the corresponding pilot-auto project.

- **`vnd.tier4.pilot-auto.project.version`** *string*

  OPTIONAL. The version of the pilot-auto project.

- **`vnd.tier4.pilot-auto.project.release-commit`** *string*

  OPTIONAL, recommended. The git commit of the pilot-auto project which this OTA image built from.

- **`vnd.tier4.pilot-auto.project.release-branch`** *string*

  OPTIONAL, recommended. The git branch of the pilot-auto project which this OTA image built from.

- **`vnd.tier4.web-auto.project`** *string*  

  OPTIONAL, recommended. The web auto project name.

- **`vnd.tier4.web-auto.project.id`** *string*

  OPTIONAL. The web-auto project ID.

- **`vnd.tier4.web-auto.catalog`** *string*

  OPTIONAL. The web-auto catalog name.

- **`vnd.tier4.web-auto.catalog.id`** *string*  

  OPTIONAL. The web-auto catalog ID.

- **`vnd.tier4.web-auto.env`** *string*  

  OPTIONAL. The web-auto environment name, like `dev`, `stg`, `prd`.

- **`vnd.tier4.pilot-auto.platform.ecu.hardware-model`** *string*  

  OPTIONAL. The hardware model of the ECU.

- **`vnd.tier4.pilot-auto.platform.ecu.hardware-series`** *string*  

  OPTIONAL. The hardware series of the ECU.

- **`vnd.tier4.image.os`** *string*  
  OPTIONAL, recommended. The operating system of the original system rootfs image, like `Ubuntu`, `Debian`, etc.

- **`vnd.tier4.image.os.version`** *string*  

  OPTIONAL, recommended. The version of the operating system of the original system rootfs image. For `Ubuntu`, like `20.04`, `22.04`, etc.

- **`description`** *string*  

  OPTIONAL. The description for this OTA image, or for the original system rootfs image.

- **`created`** *string*  

  OPTIONAL. The date when the original system rootfs image is built.
  If not specified, it will be the date when the system rootfs image is added to this OTA image.
