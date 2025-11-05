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
"""Test JWT utilities."""

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ota_image_libs._crypto.jwt_utils import (
    compose_jwt,
    get_unverified_jwt_headers,
    get_verified_jwt_payload,
)


@pytest.fixture
def rsa_keypair():
    """Generate RSA key pair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


class TestJWTUtils:
    """Test JWT utility functions."""

    def test_compose_jwt(self, rsa_keypair):
        """Test JWT composition."""
        private_key, _ = rsa_keypair
        payload = {"sub": "1234567890", "name": "Test User"}
        headers = {"typ": "JWT"}

        token = compose_jwt(
            payload=payload, headers=headers, priv_key=private_key, alg="RS256"
        )

        assert isinstance(token, str)
        assert len(token.split(".")) == 3  # JWT has 3 parts

    def test_get_verified_jwt_payload(self, rsa_keypair):
        """Test JWT payload verification."""
        private_key, public_key = rsa_keypair
        payload = {"sub": "1234567890", "name": "Test User", "admin": True}

        token = compose_jwt(payload=payload, priv_key=private_key, alg="RS256")

        verified_payload = get_verified_jwt_payload(
            token, pub_key=public_key, allowed_algs=["RS256"]
        )

        assert verified_payload["sub"] == "1234567890"
        assert verified_payload["name"] == "Test User"
        assert verified_payload["admin"] is True

    def test_get_verified_jwt_payload_wrong_key(self, rsa_keypair):
        """Test JWT payload verification with wrong key."""
        private_key, _ = rsa_keypair
        payload = {"sub": "1234567890", "name": "Test User"}

        token = compose_jwt(payload=payload, priv_key=private_key, alg="RS256")

        # Generate different key pair
        wrong_private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        wrong_public_key = wrong_private_key.public_key()
        wrong_public_pem = wrong_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        # Should raise an exception when verifying with wrong key
        with pytest.raises((ValueError, TypeError, Exception)):
            get_verified_jwt_payload(
                token, pub_key=wrong_public_pem, allowed_algs=["RS256"]
            )

    def test_get_unverified_jwt_headers(self, rsa_keypair):
        """Test getting unverified JWT headers."""
        private_key, _ = rsa_keypair
        payload = {"sub": "1234567890"}
        headers = {"typ": "JWT", "alg": "RS256", "kid": "test-key-id"}

        token = compose_jwt(
            payload=payload, headers=headers, priv_key=private_key, alg="RS256"
        )

        unverified_headers = get_unverified_jwt_headers(token)

        assert unverified_headers["typ"] == "JWT"
        assert unverified_headers["alg"] == "RS256"
        assert unverified_headers["kid"] == "test-key-id"

    def test_compose_jwt_with_different_algorithms(self, rsa_keypair):
        """Test JWT composition with different algorithms."""
        private_key, public_key = rsa_keypair
        payload = {"test": "data"}

        for alg in ["RS256", "RS384", "RS512"]:
            token = compose_jwt(payload=payload, priv_key=private_key, alg=alg)
            verified = get_verified_jwt_payload(
                token, pub_key=public_key, allowed_algs=[alg]
            )
            assert verified["test"] == "data"
