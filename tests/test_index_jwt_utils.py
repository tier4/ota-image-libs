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

"""Tests for index_jwt utils module."""

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from ota_image_libs.common.oci_spec import Sha256Digest
from ota_image_libs.v1.image_index.schema import ImageIndex
from ota_image_libs.v1.index_jwt.utils import (
    compose_index_jwt,
    get_index_jwt_sign_cert_chain,
)


class TestIndexJWTUtils:
    def test_get_index_jwt_sign_cert_chain_missing_x5c(self):
        """Test extracting cert chain from JWT without x5c header."""
        # A simple JWT without x5c header (header.payload.signature format)
        # Header: {"alg": "ES256", "typ": "JWT"}
        # This is just for testing error handling
        fake_jwt = (
            "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZXN0IjoidGVzdCJ9.fake_signature"
        )

        with pytest.raises(ValueError):
            get_index_jwt_sign_cert_chain(fake_jwt)

    def test_get_index_jwt_sign_cert_chain_invalid_x5c_format(self):
        """Test extracting cert chain with invalid x5c format (not a list)."""
        # JWT with x5c as string instead of list
        # Header: {"alg": "ES256", "typ": "JWT", "x5c": "invalid"}
        import base64
        import json

        header = {"alg": "ES256", "typ": "JWT", "x5c": "not_a_list"}
        header_b64 = (
            base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
        )
        payload_b64 = base64.urlsafe_b64encode(b'{"test": "test"}').decode().rstrip("=")
        fake_jwt = f"{header_b64}.{payload_b64}.fake_signature"

        with pytest.raises(ValueError):
            get_index_jwt_sign_cert_chain(fake_jwt)


class TestComposeIndexJwt:
    def test_compose_index_jwt_with_invalid_key(self, mocker):
        """Test compose_index_jwt with an invalid private key."""
        # Create a mock descriptor
        descriptor = ImageIndex.Descriptor(
            digest=Sha256Digest("0" * 64),
            size=1234,
        )

        # Create a mock cert chain
        mock_cert_chain = mocker.MagicMock()
        mock_cert_chain.serializer.return_value = ["cert1", "cert2"]

        # Invalid key (not ECDSA)
        invalid_key = b"invalid_key_data"

        with pytest.raises(ValueError):
            compose_index_jwt(
                descriptor,
                sign_cert_chain=mock_cert_chain,
                sign_key=invalid_key,
            )

    def test_compose_index_jwt_with_valid_ecdsa_key(self, mocker):
        """Test compose_index_jwt with a valid ECDSA key."""
        # Generate a real ECDSA key
        private_key = ec.generate_private_key(ec.SECP256R1())
        private_key_pem = private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

        # Create a mock descriptor
        descriptor = ImageIndex.Descriptor(
            digest=Sha256Digest("1" * 64),
            size=1234,
        )

        # Create a mock cert chain
        mock_cert_chain = mocker.MagicMock()
        mock_cert_chain.serializer.return_value = ["cert1", "cert2"]

        # This should not raise an error and should return a JWT string
        jwt = compose_index_jwt(
            descriptor,
            sign_cert_chain=mock_cert_chain,
            sign_key=private_key_pem,
        )

        assert isinstance(jwt, str)
        assert jwt.count(".") == 2  # JWT has 3 parts separated by dots


class TestDecodeIndexJwtWithVerification:
    def test_decode_index_jwt_with_invalid_cert_chain(self, mocker):
        """Test decode with cert chain that has no end-entity cert."""
        fake_jwt = "fake.jwt.token"

        # Create mock cert chain without end-entity cert
        mock_cert_chain = mocker.MagicMock()
        mock_cert_chain.ee = None

        from ota_image_libs.v1.index_jwt.utils import decode_index_jwt_with_verification

        with pytest.raises(ValueError):
            decode_index_jwt_with_verification(fake_jwt, mock_cert_chain)

    def test_decode_index_jwt_with_non_ecdsa_cert(self, mocker):
        """Test decode with non-ECDSA certificate."""
        fake_jwt = "fake.jwt.token"

        # Create mock cert chain with non-ECDSA cert
        mock_cert_chain = mocker.MagicMock()
        mock_ee = mocker.MagicMock()
        mock_cert_chain.ee = mock_ee

        # Mock public_key to return non-ECDSA key
        from cryptography.hazmat.primitives.asymmetric import rsa

        mock_pubkey = mocker.MagicMock(spec=rsa.RSAPublicKey)
        mock_ee.public_key.return_value = mock_pubkey

        from ota_image_libs.v1.index_jwt.utils import decode_index_jwt_with_verification

        with pytest.raises(ValueError):
            decode_index_jwt_with_verification(fake_jwt, mock_cert_chain)
