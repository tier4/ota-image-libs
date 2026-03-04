# OTA Image Distribution

For the built OTA images, for different purposes, we can distribute it differently:

- For OTA image hosting, directly host the contents of the OTA image at the file server.

- For other use cases(build flash package with OTA image, local direct deploy, etc.), the specification defines a portable artifact format for packing the OTA image into a single file.

## OTA Image Layout

An OTA image has the following directory layout:

```text
<image_root>/
├── index.json          # Image index (entry point)
├── index.jwt           # Signed JWT for the image index
└── blobs/
    └── sha256/
        ├── <digest_1>  # Resource blob identified by SHA256 hex digest
        ├── <digest_2>
        └── ...
```

- **`index.json`** — The [image index](image_index.md), serving as the entry point for discovering all manifests and metadata in the OTA image.
- **`index.jwt`** — The [index JWT](index_jwt.md) that authenticates the image index. May be absent for unsigned images.
- **`blobs/sha256/`** — The blob storage directory. Each blob is a file named by its SHA256 hex digest.

## OTA Image Hosting

The simplest distribution method is to host the OTA image directory directly on a file server (e.g., HTTP/HTTPS).
The server serves the OTA image directory structure as-is, and the client accesses individual files by URL path.
No special packaging or transformation is needed.

## OTA Image Artifact Specification

For portability (e.g., transferring between systems, offline delivery, or archival), the OTA image can be packaged into a single ZIP archive called the **OTA image artifact**.
The artifact is a strict subset of the [ZIP archive format](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT) with additional constraints to ensure reproducibility and compatibility.

Reference implementation: [`artifact/`](../src/ota_image_libs/v1/artifact/)

The artifact build is fully reproducible.
From the same OTA image build MUST always produce a byte-identical artifact.
This is achieved by aligning to the following constrains:

- **ZIP manifest** — The first entry(and second entry) of the archive MUST be:

    - **`index.json`** MUST be the first file entry in the ZIP archive (see [ZIP manifest](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT) chapter 4.1.11).
    - **`index.jwt`** If presented, MUST be the second file entry in the ZIP archive.

- **No ZIP-level compression** — All file entries MUST be stored without ZIP-level compression (`ZIP_STORED`).
  Resource-level compression (e.g., zstd) is applied during image build, not by the ZIP archive.

- **Fixed permission bits** — All file entries MUST have fixed permission bits: `0644` (`rw-r--r--`) for regular files, `0755` (`rwxr-xr-x`) for directories.

- **Fixed timestamps** — All file entries MUST have a fixed date-time of `2009-01-01 00:00:00`.

- **Alphabetical ordering** — All files and dires are ordered alphabetically, except for the `index.json` and `index.jwt`.

