"""Digital-signature provider adapter.

Contract (PROJECT_CONTEXT §13.2): prepare → sign(hash) → validate(signature, expected_hash) → evidence.

`DevLocalCAProvider` is a *development / demonstration* provider: it creates a local RSA CA and per-user
certificates under ELM_PKI_DIR (never in the database or image) and produces real RSA-PSS/SHA-256 signatures
over the revision SHA-256. Production must plug in the ADA-approved PKI / HSM / token provider (TBD by ADA).
"""
from __future__ import annotations

import base64
import datetime as dt
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from app.core.config import get_settings


@dataclass
class SignatureResult:
    provider: str
    algorithm: str
    signature_b64: str
    certificate_pem: str
    certificate_subject: str
    certificate_serial: str
    signed_at: dt.datetime
    is_cryptographic: bool = True


@dataclass
class ValidationResult:
    valid: bool
    reason: str
    chain_ok: bool = False
    hash_ok: bool = False


class SignatureProvider(Protocol):
    code: str

    def sign(self, payload_sha256_hex: str, signer_username: str, signer_name: str) -> SignatureResult: ...

    def validate(self, signature_b64: str, certificate_pem: str, expected_sha256_hex: str) -> ValidationResult: ...


class DevLocalCAProvider:
    code = "dev_local_ca"
    _lock = threading.Lock()

    def __init__(self, base: Path | None = None):
        self.base = base or get_settings().pki_dir
        self.base.mkdir(parents=True, exist_ok=True)

    # -- CA ---------------------------------------------------------------
    def _ca(self) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
        kp, cp = self.base / "ca.key.pem", self.base / "ca.cert.pem"
        with self._lock:
            if not kp.exists():
                key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
                name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ADA-ELM DEV"), x509.NameAttribute(NameOID.COMMON_NAME, "ADA-ELM Development CA (NOT FOR PRODUCTION)")])
                now = dt.datetime.now(dt.timezone.utc)
                cert = (
                    x509.CertificateBuilder()
                    .subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
                    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                    .sign(key, hashes.SHA256())
                )
                kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
                cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                kp.chmod(0o600)
        key = serialization.load_pem_private_key(kp.read_bytes(), password=None)
        cert = x509.load_pem_x509_certificate(cp.read_bytes())
        return key, cert  # type: ignore[return-value]

    def _user(self, username: str, full_name: str) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
        safe = "".join(c for c in username if c.isalnum() or c in "._-")
        kp, cp = self.base / f"user-{safe}.key.pem", self.base / f"user-{safe}.cert.pem"
        if not kp.exists():
            ca_key, ca_cert = self._ca()
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            now = dt.datetime.now(dt.timezone.utc)
            cert = (
                x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ADA"), x509.NameAttribute(NameOID.COMMON_NAME, full_name), x509.NameAttribute(NameOID.USER_ID, username)]))
                .issuer_name(ca_cert.subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=730))
                .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False, data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
                .sign(ca_key, hashes.SHA256())
            )
            kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            kp.chmod(0o600)
            cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key = serialization.load_pem_private_key(kp.read_bytes(), password=None)
        return key, x509.load_pem_x509_certificate(cp.read_bytes())  # type: ignore[return-value]

    # -- contract ---------------------------------------------------------
    def sign(self, payload_sha256_hex: str, signer_username: str, signer_name: str) -> SignatureResult:
        key, cert = self._user(signer_username, signer_name)
        sig = key.sign(bytes.fromhex(payload_sha256_hex), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
        return SignatureResult(
            provider=self.code,
            algorithm="RSA-PSS-SHA256",
            signature_b64=base64.b64encode(sig).decode(),
            certificate_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
            certificate_subject=cert.subject.rfc4514_string(),
            certificate_serial=format(cert.serial_number, "x"),
            signed_at=dt.datetime.now(dt.timezone.utc),
        )

    def validate(self, signature_b64: str, certificate_pem: str, expected_sha256_hex: str) -> ValidationResult:
        try:
            cert = x509.load_pem_x509_certificate(certificate_pem.encode())
            _, ca = self._ca()
            try:
                ca.public_key().verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm)  # type: ignore[arg-type]
                chain_ok = True
            except Exception:
                return ValidationResult(False, "Certificate is not issued by the trusted CA.")
            now = dt.datetime.now(dt.timezone.utc)
            if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
                return ValidationResult(False, "Certificate is outside its validity period.", chain_ok=chain_ok)
            cert.public_key().verify(  # type: ignore[union-attr]
                base64.b64decode(signature_b64), bytes.fromhex(expected_sha256_hex),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256(),
            )
            return ValidationResult(True, "Signature valid; document hash matches.", chain_ok=True, hash_ok=True)
        except Exception:
            return ValidationResult(False, "Signature does not match the document content.", chain_ok=True)


_providers: dict[str, SignatureProvider] = {}


def get_provider() -> SignatureProvider:
    code = get_settings().signature_provider
    if code not in _providers:
        if code == "dev_local_ca":
            _providers[code] = DevLocalCAProvider()
        else:  # pragma: no cover - production adapters registered by ADA integration
            raise RuntimeError(f"Signature provider '{code}' is not installed.")
    return _providers[code]
