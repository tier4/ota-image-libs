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
"""Tests for x509_utils module."""

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ota_image_libs._crypto.x509_utils import (
    CACertStore,
    X5cX509CertChain,
    cert_to_b64_encoded_der_serializer,
    load_cert_from_x5c,
)


class TestLoadCertFromX5c:
    """Test load_cert_from_x5c function."""

    def test_load_pem_certificate(self, root_ca_cert):
        """Test loading PEM-encoded certificate."""
        cert, _ = root_ca_cert
        pem_bytes = cert.public_bytes(serialization.Encoding.PEM)

        loaded_cert = load_cert_from_x5c(pem_bytes)
        assert loaded_cert.subject == cert.subject
        assert loaded_cert.issuer == cert.issuer

    def test_load_pem_certificate_from_string(self, root_ca_cert):
        """Test loading PEM-encoded certificate from string."""
        cert, _ = root_ca_cert
        pem_str = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")

        loaded_cert = load_cert_from_x5c(pem_str)
        assert loaded_cert.subject == cert.subject

    def test_load_base64_encoded_der_certificate(self, root_ca_cert):
        """Test loading base64-encoded DER certificate (standard x5c format)."""
        cert, _ = root_ca_cert
        der_bytes = cert.public_bytes(serialization.Encoding.DER)
        b64_der = base64.b64encode(der_bytes)

        loaded_cert = load_cert_from_x5c(b64_der)
        assert loaded_cert.subject == cert.subject

    def test_load_base64_encoded_der_certificate_from_string(self, root_ca_cert):
        """Test loading base64-encoded DER certificate from string."""
        cert, _ = root_ca_cert
        der_bytes = cert.public_bytes(serialization.Encoding.DER)
        b64_der_str = base64.b64encode(der_bytes).decode("utf-8")

        loaded_cert = load_cert_from_x5c(b64_der_str)
        assert loaded_cert.subject == cert.subject

    def test_load_raw_der_certificate(self, root_ca_cert):
        """Test loading raw DER certificate."""
        cert, _ = root_ca_cert
        der_bytes = cert.public_bytes(serialization.Encoding.DER)

        loaded_cert = load_cert_from_x5c(der_bytes)
        assert loaded_cert.subject == cert.subject

    def test_backward_compatibility_pem_format(self, root_ca_cert):
        """Test backward compatibility: ensure PEM format is still supported."""
        cert, _ = root_ca_cert
        pem_bytes = cert.public_bytes(serialization.Encoding.PEM)

        # This should work even though x5c spec requires base64 DER
        loaded_cert = load_cert_from_x5c(pem_bytes)
        assert loaded_cert.subject == cert.subject
        assert loaded_cert.issuer == cert.issuer


class TestCertToB64EncodedDerSerializer:
    """Test cert_to_b64_encoded_der_serializer function."""

    def test_serialize_certificate(self, root_ca_cert):
        """Test serializing certificate to base64-encoded DER."""
        cert, _ = root_ca_cert

        serialized = cert_to_b64_encoded_der_serializer(cert)
        assert isinstance(serialized, str)

        # Verify it can be decoded back
        decoded_der = base64.b64decode(serialized.encode("utf-8"))
        reloaded_cert = x509.load_der_x509_certificate(decoded_der)
        assert reloaded_cert.subject == cert.subject


class TestCACertStore:
    """Test CACertStore class."""

    def test_add_cert(self, root_ca_cert):
        """Test adding certificate to store."""
        cert, _ = root_ca_cert
        store = CACertStore()

        store.add_cert(cert)
        assert cert.subject in store
        assert store[cert.subject] == cert

    def test_add_raw_cert(self, root_ca_cert):
        """Test adding raw PEM certificate to store."""
        cert, _ = root_ca_cert
        pem_bytes = cert.public_bytes(serialization.Encoding.PEM)

        store = CACertStore()
        store.add_raw_cert(pem_bytes)

        assert cert.subject in store

    def test_internal_check_valid_store(self, root_ca_cert):
        """Test internal check with valid store containing root cert."""
        cert, _ = root_ca_cert
        store = CACertStore()
        store.add_cert(cert)

        # Should not raise
        store.internal_check()

    def test_internal_check_invalid_store_no_root(self, intermediate_ca_cert):
        """Test internal check fails when no root cert is present."""
        cert, _ = intermediate_ca_cert
        store = CACertStore()
        store.add_cert(cert)

        with pytest.raises(ValueError, match="no root cert is presented"):
            store.internal_check()

    def test_verify_valid_chain(
        self, root_ca_cert, intermediate_ca_cert, end_entity_cert
    ):
        """Test verifying a valid certificate chain."""
        root_cert, _ = root_ca_cert
        intermediate_cert, _ = intermediate_ca_cert
        ee_cert, _ = end_entity_cert

        store = CACertStore()
        store.add_cert(root_cert)

        # Should not raise
        store.verify(ee_cert, interm_cas=[intermediate_cert])

    def test_verify_invalid_chain_wrong_root(self, root_ca_cert, end_entity_cert):
        """Test verifying with wrong root CA."""
        _, _ = root_ca_cert
        ee_cert, _ = end_entity_cert

        # Create a different root CA
        different_root_key = ec.generate_private_key(ec.SECP256R1())
        different_root_subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "Different Root CA"),
            ]
        )
        different_root_cert = (
            x509.CertificateBuilder()
            .subject_name(different_root_subject)
            .issuer_name(different_root_subject)
            .public_key(different_root_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None),
                critical=True,
            )
            .sign(different_root_key, hashes.SHA256())
        )

        store = CACertStore()
        store.add_cert(different_root_cert)

        with pytest.raises(ValueError, match="Sign certificate verification failed"):
            store.verify(ee_cert, interm_cas=[])


class TestX5cX509CertChain:
    """Test X5cX509CertChain class."""

    def test_validator_with_certificate_objects(
        self, root_ca_cert, intermediate_ca_cert, end_entity_cert
    ):
        """Test validator with Certificate objects."""
        _, _ = root_ca_cert
        intermediate_cert, _ = intermediate_ca_cert
        ee_cert, _ = end_entity_cert

        chain = X5cX509CertChain.validator([ee_cert, intermediate_cert])

        assert chain.ee == ee_cert
        assert len(chain.interms) == 1
        assert chain.interms[0] == intermediate_cert

    def test_validator_with_pem_encoded_certs(
        self, root_ca_cert, intermediate_ca_cert, end_entity_cert
    ):
        """Test validator with PEM-encoded certificates."""
        _, _ = root_ca_cert
        intermediate_cert, _ = intermediate_ca_cert
        ee_cert, _ = end_entity_cert

        ee_pem = ee_cert.public_bytes(serialization.Encoding.PEM)
        intermediate_pem = intermediate_cert.public_bytes(serialization.Encoding.PEM)

        chain = X5cX509CertChain.validator([ee_pem, intermediate_pem])

        assert chain.ee.subject == ee_cert.subject
        assert len(chain.interms) == 1
        assert chain.interms[0].subject == intermediate_cert.subject

    def test_validator_with_base64_der_encoded_certs(
        self, root_ca_cert, intermediate_ca_cert, end_entity_cert
    ):
        """Test validator with base64-encoded DER certificates (standard x5c format)."""
        _, _ = root_ca_cert
        intermediate_cert, _ = intermediate_ca_cert
        ee_cert, _ = end_entity_cert

        ee_der = base64.b64encode(
            ee_cert.public_bytes(serialization.Encoding.DER)
        ).decode("utf-8")
        intermediate_der = base64.b64encode(
            intermediate_cert.public_bytes(serialization.Encoding.DER)
        ).decode("utf-8")

        chain = X5cX509CertChain.validator([ee_der, intermediate_der])

        assert chain.ee.subject == ee_cert.subject
        assert len(chain.interms) == 1

    def test_backward_compatibility_pem_in_x5c(
        self, root_ca_cert, intermediate_ca_cert, end_entity_cert
    ):
        """Test backward compatibility: x5c header containing PEM certs.

        Although RFC 7515 specifies x5c should contain base64-encoded DER,
        we maintain backward compatibility by also accepting PEM format.
        """
        _, _ = root_ca_cert
        intermediate_cert, _ = intermediate_ca_cert
        ee_cert, _ = end_entity_cert

        # Create x5c array with PEM certs (backward compatibility)
        ee_pem = ee_cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
        intermediate_pem = intermediate_cert.public_bytes(
            serialization.Encoding.PEM
        ).decode("utf-8")

        # This should work despite not being RFC-compliant
        chain = X5cX509CertChain.validator([ee_pem, intermediate_pem])

        assert chain.ee.subject == ee_cert.subject
        assert len(chain.interms) == 1
        assert chain.interms[0].subject == intermediate_cert.subject

    def test_validator_rejects_root_cert(self, root_ca_cert):
        """Test validator rejects root CA in chain."""
        root_cert, _ = root_ca_cert

        with pytest.raises(ValueError, match="Reject adding root CA"):
            X5cX509CertChain.validator([root_cert])

    def test_validator_rejects_empty_list(self):
        """Test validator rejects empty certificate list."""
        with pytest.raises(ValueError, match="End-entity certificate not found"):
            X5cX509CertChain.validator([])

    def test_validator_rejects_invalid_chain_multiple_chains(
        self, intermediate_ca_cert, end_entity_cert
    ):
        """Test validator rejects multiple independent chains."""
        intermediate_cert, _ = intermediate_ca_cert
        ee_cert, _ = end_entity_cert

        # Create an unrelated certificate
        unrelated_key = ec.generate_private_key(ec.SECP256R1())
        unrelated_issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Unrelated CA")]
        )
        unrelated_subject = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Unrelated Cert")]
        )
        unrelated_cert = (
            x509.CertificateBuilder()
            .subject_name(unrelated_subject)
            .issuer_name(unrelated_issuer)
            .public_key(unrelated_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=90))
            .sign(unrelated_key, hashes.SHA256())
        )

        with pytest.raises(ValueError, match="multiple chains found"):
            X5cX509CertChain.validator([ee_cert, intermediate_cert, unrelated_cert])

    def test_validator_exceeds_max_chain_length(self):
        """Test validator rejects chains exceeding MAX_CHAIN_LENGTH."""
        from ota_image_libs._crypto.x509_utils import MAX_CHAIN_LENGTH

        # Create a chain that exceeds max length
        certs = []
        prev_key = ec.generate_private_key(ec.SECP256R1())
        prev_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CA 0")])

        for i in range(MAX_CHAIN_LENGTH + 1):
            key = ec.generate_private_key(ec.SECP256R1())
            subject = x509.Name(
                [x509.NameAttribute(NameOID.COMMON_NAME, f"CA {i + 1}")]
            )

            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(prev_subject)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.now(timezone.utc))
                .not_valid_after(datetime.now(timezone.utc) + timedelta(days=90))
                .sign(prev_key, hashes.SHA256())
            )
            certs.append(cert)
            prev_key = key
            prev_subject = subject

        with pytest.raises(ValueError, match="Exceeded maximum chain length"):
            X5cX509CertChain.validator(certs)

    def test_serializer_returns_base64_der(
        self, root_ca_cert, intermediate_ca_cert, end_entity_cert
    ):
        """Test serializer returns list of base64-encoded DER certificates."""
        _, _ = root_ca_cert
        intermediate_cert, _ = intermediate_ca_cert
        ee_cert, _ = end_entity_cert

        chain = X5cX509CertChain.validator([ee_cert, intermediate_cert])
        serialized = chain.serializer()

        assert isinstance(serialized, list)
        assert len(serialized) == 2

        # Each should be a valid base64-encoded DER
        for cert_str in serialized:
            assert isinstance(cert_str, str)
            decoded = base64.b64decode(cert_str.encode("utf-8"))
            reloaded = x509.load_der_x509_certificate(decoded)
            assert reloaded is not None

    def test_serializer_without_ee_raises(self):
        """Test serializer raises when end-entity cert is not set."""
        chain = X5cX509CertChain()

        with pytest.raises(ValueError, match="End-entity certificate must be set"):
            chain.serializer()

    def test_add_ee(self, end_entity_cert):
        """Test adding end-entity certificate."""
        ee_cert, _ = end_entity_cert
        chain = X5cX509CertChain()

        chain.add_ee(ee_cert)
        assert chain.ee == ee_cert

    def test_add_ee_twice_raises(self, end_entity_cert):
        """Test adding end-entity certificate twice raises error."""
        ee_cert, _ = end_entity_cert
        chain = X5cX509CertChain()

        chain.add_ee(ee_cert)
        with pytest.raises(ValueError, match="already set"):
            chain.add_ee(ee_cert)

    def test_add_interms(self, intermediate_ca_cert, end_entity_cert):
        """Test adding intermediate certificates."""
        intermediate_cert, _ = intermediate_ca_cert
        ee_cert, _ = end_entity_cert
        chain = X5cX509CertChain()

        chain.add_ee(ee_cert)
        chain.add_interms(intermediate_cert)

        assert len(chain.interms) == 1
        assert chain.interms[0] == intermediate_cert

    def test_add_interms_without_ee_raises(self, intermediate_ca_cert):
        """Test adding intermediate cert without end-entity cert raises error."""
        intermediate_cert, _ = intermediate_ca_cert
        chain = X5cX509CertChain()

        with pytest.raises(ValueError, match="MUST be set first"):
            chain.add_interms(intermediate_cert)

    def test_add_interms_rejects_root_ca(self, root_ca_cert, end_entity_cert):
        """Test adding root CA as intermediate is rejected."""
        root_cert, _ = root_ca_cert
        ee_cert, _ = end_entity_cert
        chain = X5cX509CertChain()

        chain.add_ee(ee_cert)
        with pytest.raises(ValueError, match="Reject adding root CA"):
            chain.add_interms(root_cert)

    def test_roundtrip_serialization(
        self, root_ca_cert, intermediate_ca_cert, end_entity_cert
    ):
        """Test roundtrip: serialize and deserialize chain."""
        _, _ = root_ca_cert
        intermediate_cert, _ = intermediate_ca_cert
        ee_cert, _ = end_entity_cert

        # Create chain
        chain1 = X5cX509CertChain.validator([ee_cert, intermediate_cert])

        # Serialize
        serialized = chain1.serializer()

        # Deserialize
        chain2 = X5cX509CertChain.validator(serialized)

        # Verify they're equivalent
        assert chain2.ee.subject == chain1.ee.subject
        assert len(chain2.interms) == len(chain1.interms)
        assert chain2.interms[0].subject == chain1.interms[0].subject
