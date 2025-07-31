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

from __future__ import annotations

from typing import Any

import jwt


def compose_jwt(
    payload: dict[str, Any],
    headers: dict[str, Any] | None = None,
    *,
    priv_key: bytes,
    alg: str,
) -> str:
    return jwt.encode(
        payload=payload,
        headers=headers,
        key=priv_key,
        algorithm=alg,
    )


def get_verified_jwt_payload(
    token: str,
    *,
    pub_key: bytes,
    allowed_algs: list[str],
) -> dict[str, str]:
    """Parse the input JWT, verify its signature and then return its payload."""
    return jwt.decode(
        token,
        key=pub_key,
        algorithms=allowed_algs,
        options={"verify_signature": True},
    )


def get_unverified_jwt_headers(
    token: str,
) -> dict[str, Any]:
    """Parse the input JWT and return its headers.

    This is for caller get the x5c header, perform the sign cert verification,
        and then use verified sign cert's pubkey to verify the JWS signature.
    """
    return jwt.get_unverified_header(token)
