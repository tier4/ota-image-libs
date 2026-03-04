# Sys Config

The sys_config is a YAML file that describes post OTA configuration for the target device.
It is optionally referenced by the [image_config](image_config.md).

OTA client MAY only support a subset of the features described in the schema.
For minimum requirement, `hostname` and `persist_files` SHOULD be supported.

## Media Type

`application/vnd.tier4.ota.sys-config.v1+yaml`

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
    Each line should be in `<key>=<value>` format.

- **`persist_files`** *array of strings*

    This OPTIONAL field specifies file paths that should be persisted across OTA updates.

- **`network`** *object*

    This OPTIONAL field contains network configuration for the target system.
    It MUST be an object of a valid netplan configuration YAML.

- **`otaclient.ecu_info`** *object*

    This OPTIONAL field contains a copy of OTAClient ecu_info.yaml configuration.

- **`otaclient.proxy_info`** *object*

    This OPTIONAL field contains a copy of OTAClient proxy_info.yaml configuration.

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
  size: 6 # GiB
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
