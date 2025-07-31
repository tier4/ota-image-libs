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
"""Verify the signing of the OTA image."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ota_image_libs._crypto.x509_utils import CACertStore
from ota_image_libs.v1.consts import INDEX_JWT_FNAME
from ota_image_libs.v1.image_index.utils import ImageIndexHelper
from ota_image_libs.v1.index_jwt.utils import (
    decode_index_jwt_with_verification,
    get_index_jwt_sign_cert_chain,
)
from ota_image_libs.v1.utils import check_if_valid_ota_image
from ota_image_tools._utils import exit_with_err_msg

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction


logger = logging.getLogger(__name__)


def verify_sign_cmd_args(
    sub_arg_parser: _SubParsersAction[ArgumentParser], *parent_parser: ArgumentParser
) -> None:
    verify_sign_arg_parser = sub_arg_parser.add_parser(
        name="verify-sign",
        help=(_help_txt := "Verify the signature of the OTA image"),
        description=_help_txt,
        parents=parent_parser,
    )
    verify_sign_arg_parser.add_argument(
        "--ca-dir",
        help="Folder that holds the CA certificates for verifying the sign cert.",
    )
    verify_sign_arg_parser.add_argument(
        "image_root",
        help="Folder that holds the OTA image.",
    )
    verify_sign_arg_parser.set_defaults(handler=verify_sign_cmd)


def verify_sign_cmd(args: Namespace) -> None:
    logger.debug(f"calling {verify_sign_cmd.__name__} with {args}")
    image_root = Path(args.image_root)
    if not check_if_valid_ota_image(image_root):
        exit_with_err_msg(f"{image_root} doesn't hold a valid OTA image.")
    print(f"Verifying the signature of OTA image at {image_root} ...")

    _index_helper = ImageIndexHelper(image_root)
    if not _index_helper.image_index.image_signed:
        exit_with_err_msg(f"OTA image on {image_root} is not signed.")

    _index_jwt_f = image_root / INDEX_JWT_FNAME
    if not _index_jwt_f.is_file():
        exit_with_err_msg(f"{_index_jwt_f} doesn't exist, broken OTA image?")
    _index_jwt = _index_jwt_f.read_text()

    _sign_cert_chain = get_index_jwt_sign_cert_chain(_index_jwt)

    _ca_dir = args.ca_dir
    if _ca_dir is None:
        logger.warning(
            "WARNING: no ca_dir is provided, will SKIP verifying the sign cert!"
        )
    else:
        _ca_dir = Path(_ca_dir)
        if not _ca_dir.is_dir():
            exit_with_err_msg(f"{_ca_dir=} is not a directry.")

        print("Verifying the sign cert against specified root-of-trust ...")
        _ca_store = CACertStore()
        for _cert_f in _ca_dir.glob("*"):
            if not _cert_f.is_file():
                continue
            _ca_store.add_raw_cert(_cert_f.read_bytes())
        _ca_store.verify(_sign_cert_chain.ee, interm_cas=_sign_cert_chain.interms)

    print("Verifying the index.jwt signature ...")
    _verified_claims = decode_index_jwt_with_verification(_index_jwt, _sign_cert_chain)
    _formated_json = _verified_claims.model_dump_json(
        by_alias=True, exclude_none=True, indent=2
    )
    print("Verified index.jwt claims:")
    print(_formated_json)
