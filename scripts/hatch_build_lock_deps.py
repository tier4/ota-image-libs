# Copyright 2022 TIER IV, INC. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# A custom metadata hook implementation that overwrites dependencies with locked version
#   from uv.lock file.
#
# reference https://github.com/pga2rn/py_deps_locked_build_demo

from __future__ import annotations

import subprocess
from pprint import pformat

from hatchling.metadata.plugin.interface import MetadataHookInterface

# fmt: off
UV_EXPORT_FREEZED_CMD = (
    "uv", "export", "--frozen", "--color=never",
    "--no-dev", "--no-editable", "--no-hashes", "--no-emit-project",
)
# fmt: on


def _uv_export_locked_requirements() -> list[str]:
    print(
        f"metahook: generate locked deps list with: {' '.join(UV_EXPORT_FREEZED_CMD)}"
    )
    _uv_export_res = subprocess.run(UV_EXPORT_FREEZED_CMD, capture_output=True)
    _res: list[str] = []
    for _dep_line in _uv_export_res.stdout.decode().splitlines():
        _dep_line = _dep_line.strip()
        if _dep_line.startswith("#"):
            continue
        _res.append(_dep_line)
    return _res


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata) -> None:
        print("metahook: add optional dependencies `pinned`.")
        _locked_deps = _uv_export_locked_requirements()
        print(f"metahook: locked deps: {pformat(_locked_deps)}")
        metadata["optional-dependencies"] = {"pinned": _locked_deps}
