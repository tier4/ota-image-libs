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

import logging
from typing import Any, Dict

from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509 import (
    BasicConstraints,
    Certificate,
    Name,
    load_pem_x509_certificate,
)
from cryptography.x509.verification import (
    Criticality,
    ExtensionPolicy,
    PolicyBuilder,
    Store,
)
from pydantic import (
    ModelWrapValidatorHandler,
    PlainSerializer,
    WrapValidator,
    model_serializer,
    model_validator,
)
from typing_extensions import Annotated, Self

from ota_image_tools._utils import exit_with_err_msg

logger = logging.getLogger(__name__)

MAX_CHAIN_LENGTH = 6


def cert_from_pem_validator(
    data: Any, handler: ModelWrapValidatorHandler[Certificate]
) -> Certificate:
    if isinstance(data, Certificate):
        return data
    if isinstance(data, str):
        return load_pem_x509_certificate(data.encode("utf-8"))
    return handler(data)


def cert_to_pem_serializer(cert: Certificate) -> str:
    return cert.public_bytes(Encoding.PEM).decode("utf-8")


X509PEM = Annotated[
    Certificate,
    WrapValidator(cert_from_pem_validator),
    PlainSerializer(cert_to_pem_serializer),
]


class CACertStore(Dict[Name, Certificate]):
    """ "Represents a store of X.509 CA certificates.

    Dict key is the subject of the certificate, and value is the Certificate inst.
    """

    def add_cert(self, cert: Certificate) -> None:
        self[cert.subject] = cert

    def add_raw_cert(self, _input: bytes) -> None:
        cert = load_pem_x509_certificate(_input)
        self.add_cert(cert)

    def internal_check(self) -> None:
        """Do an internal check to see if this CACertStore is valid.

        Currently one check will be performed:
        1. at least one root cert should be presented in the store.

        Raises:
            ValueError on failed check.
        """
        for _, cert in self.items():
            if cert.issuer == cert.subject:
                return
        raise ValueError("invalid chain: no root cert is presented")

    def verify(self, sign_cert: Certificate, *, interm_cas: list[Certificate]) -> None:
        """Verify the sign_cert against the CA certs in this store.

        Args:
            sign_cert: The certificate to verify.
            interm_cas: A list of intermediate CA certificates to use for verification.

        Returns:
            True if the sign_cert is verified by one of the CA certs in this store.
        """
        cert_store = Store(list(self.values()))
        verify_policy = PolicyBuilder().store(cert_store)

        # specify how we verify the extensions
        # NOTE: since we are not CA for signing a web server certificates,
        #       we only check the minimum extension requirements for CA certs,
        #       which is BasicConstraints with Criticality.CRITICAL.
        _ca_permit_all = ExtensionPolicy.permit_all()
        _ca_policy = _ca_permit_all.require_present(
            BasicConstraints,
            Criticality.CRITICAL,
            None,
        )
        updated_verify_policy = verify_policy.extension_policies(
            ee_policy=ExtensionPolicy.permit_all(),
            ca_policy=_ca_policy,
        )
        verifier = updated_verify_policy.build_client_verifier()

        try:
            verifier.verify(sign_cert, intermediates=interm_cas)
        except Exception as e:
            logger.debug(f"failed to verify sign certificate: {e}", exc_info=e)
            exit_with_err_msg(f"Sign certificate verification failed: {e}")


class X509CertChain:
    """Represents a chain of X.509 certificates."""

    def __init__(self) -> None:
        self._ee: Certificate | None = None
        self._interms: list[Certificate] = []

    @property
    def ee(self) -> Certificate:
        if not self._ee:
            raise ValueError("End-entity certificate is not set")
        return self._ee

    @property
    def interms(self) -> list[Certificate]:
        return self._interms.copy()

    def add_ee(self, cert: Certificate) -> None:
        """Add a certificate to the chain."""
        if self._ee:
            raise ValueError("End-entity certificate is already set")
        self._ee = cert

    def add_interms(self, *certs: Certificate) -> None:
        """Add an intermediate certificate to the chain."""
        if not self._ee:
            raise ValueError("End-entity certificate MUST be set first")
        for cert in certs:
            if cert.subject == cert.issuer:
                raise ValueError("Reject adding root CA into cert chain")
        if len(self._interms) >= MAX_CHAIN_LENGTH:
            raise ValueError(
                f"Reject adding more than {MAX_CHAIN_LENGTH} intermediate certs"
            )
        self._interms.extend(certs)

    @classmethod
    def validator(cls, data: Any, handler: Any = None) -> Self:
        if not isinstance(data, list):
            raise ValueError("Expected a list of certificates")

        issuer_cert_map: dict[str, Certificate] = {}
        subject_cert_map: dict[str, Certificate] = {}
        for raw_cert in data:
            if len(issuer_cert_map) >= MAX_CHAIN_LENGTH:
                raise ValueError(f"Exceeded maximum chain length ({MAX_CHAIN_LENGTH})")
            if isinstance(raw_cert, str):
                cert = load_pem_x509_certificate(raw_cert.encode("utf-8"))
            elif isinstance(raw_cert, bytes):
                cert = load_pem_x509_certificate(raw_cert)
            elif isinstance(raw_cert, Certificate):
                cert = raw_cert
            else:
                raise ValueError("Invalid input cert")

            if cert.subject == cert.issuer:
                raise ValueError("Reject adding root CA into cert chain")
            issuer_cert_map[cert.issuer.rfc4514_string()] = cert
            subject_cert_map[cert.subject.rfc4514_string()] = cert

        # finding the ee cert, ee cert is not the issuer of any other certs
        ee = None
        for _, cert in issuer_cert_map.items():
            if cert.subject.rfc4514_string() not in issuer_cert_map:
                ee = cert
                break
        else:
            raise ValueError("End-entity certificate not found in the chain")

        # form the intermediate chain
        _cur_issuer, interms = ee.issuer.rfc4514_string(), []
        _depth_count = 0
        while _cur_issuer in subject_cert_map:
            _depth_count += 1
            if _depth_count > MAX_CHAIN_LENGTH:
                raise ValueError(
                    f"Exceeded maximum chain length ({MAX_CHAIN_LENGTH}) while finding intermediates, "
                    f"{_cur_issuer=}"
                )

            _issuer_cert = subject_cert_map[_cur_issuer]
            interms.append(_issuer_cert)
            _cur_issuer = _issuer_cert.issuer.rfc4514_string()

        # sanity check, only one chain should be presented in the input chain
        if len(issuer_cert_map) != len(interms) + 1:
            raise ValueError("Invalid certificate chain, multiple chains found")

        res = cls()
        res.add_ee(ee)
        res.add_interms(*interms)
        return res

    _pydantic_validator = model_validator(mode="wrap")(validator)

    def serializer(self) -> list[str]:
        """Serialize the certificate chain to a list of PEM-encoded strings."""
        result = []
        if self._ee is None:
            raise ValueError("End-entity certificate must be set")
        result.append(cert_to_pem_serializer(self._ee))

        for cert in self._interms:
            result.append(cert_to_pem_serializer(cert))
        return result

    _pydantic_serializer = model_serializer(mode="plain")(serializer)
