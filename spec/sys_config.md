# Sys Config

## Media Type

`application/vnd.tier4.ota.sys-config.v1+yaml`

For backward compatibility, `application/vnd.tier4.ota.file-based-ota-image.config.v1+yaml` is also accepted.

The sys_config is a YAML file that describes system-level configuration for the target device. It is optionally referenced by the [image_config](image_config.md).

## Sys Config Schema

- **`hostname`** *string*

    This REQUIRED field specifies the hostname of the target system.

- **`extra_mount`** *array of MountCfg*

    This OPTIONAL field specifies additional mount points for the target system.
    Each element is a mount configuration object with the following fields:

  - **`file_system`** *string* — The filesystem device or path.
  - **`mount_point`** *string* — The mount point path.
  - **`type`** *string* — The filesystem type (e.g., `ext4`, `btrfs`).
  - **`options`** *string* — OPTIONAL mount options.

- **`swap`** *SwapCfg*

    This OPTIONAL field specifies swap configuration for the target system.
    The swap configuration object has the following fields:

  - **`filepath`** *string* — Path to the swap file.
  - **`size`** *int* — Swap size in GiB.

- **`sysctl`** *array of strings*

    This OPTIONAL field specifies sysctl settings to apply on the target system.

- **`persist_files`** *array of strings*

    This OPTIONAL field specifies file paths that should be persisted across OTA updates.

- **`network`** *object*

    This OPTIONAL field specifies network configuration for the target system.

- **`otaclient.ecu_info`** *object*

    This OPTIONAL field specifies OTAClient ECU information configuration.

- **`otaclient.proxy_info`** *object*

    This OPTIONAL field specifies OTAClient proxy information configuration.

## Example sys_config

```yaml
hostname: example-host
extra_mount:
  - file_system: /dev/sda1
    mount_point: /mnt/data
    type: ext4
    options: defaults
swap:
  filepath: /swapfile
  size: 4
sysctl:
  - vm.swappiness=10
persist_files:
  - /etc/machine-id
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
otaclient.ecu_info:
  ecu_id: autoware
  ip_addr: 192.168.1.100
otaclient.proxy_info:
  gateway: 192.168.1.1
```
