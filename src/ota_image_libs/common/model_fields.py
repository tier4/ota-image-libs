# Copyright 2025 TIER IV, INC. All rights reserved.
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
"""Common shared utils and libs for parsing and generating OTA images metadata."""

from typing import Any


class NotDefinedField:
    """A sentinel labelling a field that is not defined.

    This is for MetaFile that doesn't define SchemaVersion.
    """

    field_name: str = ""

    def __set_name__(self, owner, name: str):
        self.field_name = name

    def __get__(self, obj, objtype=None) -> Any:
        return None

    def __set__(self, obj, value):
        raise ValueError(
            f"cannot set {self.field_name} on {obj} as this field is not defined"
        )


class ConstFieldMeta(type):
    """Meta class for ConstField."""

    expected: Any
    field_name: str = ""

    def __set_name__(self, owner, name: str):
        self.field_name = name

    def __get__(self, obj, objtype=None):
        return self.expected

    def __set__(self, obj, value):
        raise ValueError(f"{self.__name__} reject override pre-defined const value")
