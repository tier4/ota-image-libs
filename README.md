# OTA Image Libs

A Python library and CLI toolkit for creating, reading, verifying, and deploying Over-The-Air (OTA) system images, following the [OCI (Open Container Initiative)](https://opencontainers.org/) standards.

## Features

- **OCI-compliant image specification** - Image index, manifest, and config schemas based on OCI standards
- **Cryptographic signing and verification** - ES256 JWT signatures with X.509 certificate chain validation
- **Artifact packing and reading** - Reproducible ZIP-based artifact format with content-addressable blob storage
- **Multi-threaded deployment** - Concurrent image payload extraction and rootfs deployment
- **File and resource metadata** - SQLite-backed file table and resource table for efficient metadata queries
- **Compression support** - Zstandard (zstd) compression for databases and blob storage

## Installation

Install from source using [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/tier4/ota-image-libs.git
cd ota-image-libs
uv sync
```

Or install the wheel directly from the [GitHub Releases](https://github.com/tier4/ota-image-libs/releases):

```bash
# Download the .whl file from the latest release, then install it
pip install ota_image_libs-<version>-py3-none-any.whl
```

## CLI Usage

The `ota-image-tools` command provides subcommands for working with OTA images:

```bash
ota-image-tools [OPTIONS] <SUBCOMMAND>
```

### Global Options

| Option | Description |
| ------ | ----------- |
| `-d`, `--debug` | Enable debug logging |

### Subcommands

| Command | Description |
| ------- | ----------- |
| `version` | Print the ota-image-libs version |
| `deploy-image` | Deploy a system image payload from an OTA artifact to the filesystem |
| `list-image` | List all image payloads in an OTA image |
| `inspect-index` | Print the contents of index.json |
| `inspect-blob` | Extract and display blob contents from blob storage |
| `lookup-image` | Look up a specific image manifest |
| `verify-sign` | Verify an OTA image signature with X.509 certificate chain validation |
| `verify-resources` | Verify blob integrity with parallel SHA256 validation |

### Examples

```bash
# List images in an OTA artifact
ota-image-tools list-image /path/to/ota-image

# Verify the signature of an OTA image (signature only)
ota-image-tools verify-sign /path/to/ota-image

# Verify the signature with cert chain validation against CA certificates
ota-image-tools verify-sign --ca-dir /path/to/ca-certs /path/to/ota-image

# Deploy an image to a target directory
ota-image-tools deploy-image \
  --image /path/to/ota-image.zip \
  --ecu-id my-ecu \
  --rootfs-dir /path/to/rootfs
```

## Library Usage

The `ota_image_libs` package can be used as a library in your own Python projects:

```python
from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.image_index.schema import ImageIndex

# Read an OTA image artifact
with OTAImageArtifactReader("/path/to/ota-image.zip") as reader:
    index = reader.read_index()
    print(index)
```

## Documentation

Specification documents are available in the [docs/](docs/) directory:

| Document | Description |
| -------- | ----------- |
| [image_index.md](docs/image_index.md) | OCI image index specification for OTA images |
| [image_config.md](docs/image_config.md) | Per-image configuration schema |
| [annotations.md](docs/annotations.md) | Standard annotation key definitions |
| [index_jwt.md](docs/index_jwt.md) | JWT signing specification |
| [otaclient_package.md](docs/otaclient_package.md) | OTAClient release package format |

## Supported Python Versions

Python 3.8, 3.9, 3.10, 3.11, 3.12, 3.13

## Contributing

See [DEVELOPMENT.md](DEVELOPMENT.md) for development setup and guidelines.

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
