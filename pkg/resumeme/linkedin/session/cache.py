"""
Encrypt and authenticate bounded browser-profile archives using dedicated RSA PEM keys.
"""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from attrs import frozen
from cryptography.exceptions import InvalidSignature, InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from resumeme.exceptions import SessionCacheError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["CacheKeys", "archive_profile", "open_archive", "restore_profile", "seal_archive"]

_MAGIC = b"RESUMEME-SESSION-1\x00"
_MAX_BYTES = 256 * 1024 * 1024
_SKIP = frozenset({"cache2", "Cache", "Code Cache", "GPUCache", "shader-cache", "startupCache", "crashes"})


@frozen
class CacheKeys:
    """
    Hold a matching RSA key pair without writing private material to the workspace.

    Attributes:
        private (rsa.RSAPrivateKey): Dedicated cache key, also used to authenticate cache writers.
        public (rsa.RSAPublicKey): Matching public key used for encryption and signature verification.
    """

    private: rsa.RSAPrivateKey
    public: rsa.RSAPublicKey

    @classmethod
    def from_pem(cls, private_pem: bytes, public_pem: bytes, password: bytes | None = None) -> CacheKeys:
        """
        Load ssh-keygen RSA PEM output and reject unsupported, weak, or mismatched keys.

        Args:
            private_pem (bytes): Complete RSA private key in PEM format.
            public_pem (bytes): Complete public key in PEM format.
            password (bytes | None): Optional password for encrypted private PEM data.

        Returns:
            CacheKeys: Validated RSA pair with at least 3072 bits.

        Raises:
            SessionCacheError: Key format, password, size, or correspondence is invalid.
        """
        try:
            private = serialization.load_pem_private_key(private_pem, password)
            public = serialization.load_pem_public_key(public_pem)
        except (ValueError, TypeError, UnsupportedAlgorithm) as error:
            raise SessionCacheError("Cannot read cache PEM keys; check the cache key secrets and optional password.") from error

        if not isinstance(private, rsa.RSAPrivateKey) or not isinstance(public, rsa.RSAPublicKey):
            raise SessionCacheError("Session cache encryption requires RSA PEM keys generated with ssh-keygen.")

        if private.key_size < 3072 or private.public_key().public_numbers() != public.public_numbers():
            raise SessionCacheError("Session cache keys must match and use RSA with at least 3072 bits.")

        return cls(private, public)

    def fingerprint(self) -> str:
        """
        Bind cache lookup to a public-key identity so rotation cannot restore ciphertext from an old key.

        Returns:
            str: SHA-256 digest of the DER public key.
        """
        return hashlib.sha256(
            self.public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        ).hexdigest()


def seal_archive(data: bytes, keys: CacheKeys, context: bytes) -> bytes:
    """
    Encrypt with a fresh AES-256-GCM key and authenticate the complete envelope with RSA-PSS.

    Args:
        data (bytes): Compressed profile archive held in memory.
        keys (CacheKeys): Dedicated cache encryption and signing pair.
        context (bytes): Repository, profile owner, browser, and platform identity bound to this ciphertext.

    Returns:
        bytes: Versioned, signed ciphertext containing the RSA-OAEP-wrapped data key.

    Raises:
        SessionCacheError: The archive exceeds the supported memory bound.
    """
    if len(data) > _MAX_BYTES:
        raise SessionCacheError("Browser session archive exceeds the 256 MiB cache limit.")

    # A new data key and nonce are generated for every write, including unchanged browser state.
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    wrapped = keys.public.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=context))
    header = _MAGIC + wrapped + nonce
    envelope = header + AESGCM(key).encrypt(nonce, data, context + header)

    # Public-key encryption alone does not authenticate the writer; reject forged cache entries before decrypting.
    signature = keys.private.sign(
        context + envelope, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256()
    )
    return envelope + signature


def open_archive(data: bytes, keys: CacheKeys, context: bytes) -> bytes:
    """
    Verify and decrypt a cache envelope before any archive contents reach disk.

    Args:
        data (bytes): Untrusted encrypted cache bytes.
        keys (CacheKeys): Matching RSA pair.
        context (bytes): Expected repository, profile owner, browser, and platform identity.

    Returns:
        bytes: Authenticated compressed archive.

    Raises:
        SessionCacheError: Version, size, signature, ownership context, or ciphertext authentication is invalid.
    """
    size = keys.public.key_size // 8

    if not data.startswith(_MAGIC) or not len(_MAGIC) + 2 * size + 28 <= len(data) <= _MAX_BYTES + 2 * size + 128:
        raise SessionCacheError("Session cache has an invalid envelope or exceeds its size limit.")

    envelope, signature = data[:-size], data[-size:]
    offset = len(_MAGIC)
    wrapped, nonce = envelope[offset : offset + size], envelope[offset + size : offset + size + 12]
    header = envelope[: offset + size + 12]

    try:
        keys.public.verify(
            signature,
            context + envelope,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        key = keys.private.decrypt(wrapped, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=context))
        return AESGCM(key).decrypt(nonce, envelope[len(header) :], context + header)
    except (InvalidSignature, InvalidTag, ValueError) as error:
        raise SessionCacheError("Session cache authentication failed; no cached browser state was loaded.") from error


def archive_profile(profile: Path) -> bytes:
    """
    Collect regular browser files in memory without archiving runtime locks, symlinks, or disposable browser caches.

    Args:
        profile (Path): Closed browser profile owned by the current job.

    Returns:
        bytes: Gzip-compressed tar archive with bounded regular-file contents.

    Raises:
        SessionCacheError: The profile is absent or its regular files exceed the cache limit.
    """
    if not profile.is_dir():
        raise SessionCacheError("Cannot cache a browser profile that was not created.")

    buffer = io.BytesIO()
    total = 0

    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(profile.rglob("*")):
            relative = path.relative_to(profile)

            if path.is_symlink() or not path.is_file() or any(part in _SKIP for part in relative.parts):
                continue

            if path.name in {"lock", ".parentlock", "parent.lock"} or path.name.startswith("Singleton"):
                continue

            total += path.stat().st_size

            if total > _MAX_BYTES:
                raise SessionCacheError("Browser profile exceeds the 256 MiB cache limit.")

            archive.add(path, arcname=relative.as_posix(), recursive=False)

    return buffer.getvalue()


def restore_profile(data: bytes, profile: Path) -> None:
    """
    Validate the whole authenticated archive before extracting regular files into a new temporary profile.

    Args:
        data (bytes): Authenticated compressed archive.
        profile (Path): Empty private directory that the caller removes when the command finishes.

    Returns:
        None: The browser profile is restored with private file and directory permissions.

    Raises:
        SessionCacheError: Members escape the profile, contain links or devices, duplicate names, or exceed size bounds.
    """
    if profile.exists() and any(profile.iterdir()):
        raise SessionCacheError("Session cache must restore into an empty browser profile.")

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members = archive.getmembers()
            total, names = 0, set()

            # Validate all entries before writing any file; links and duplicate paths can otherwise redirect later extraction.
            for member in members:
                name = PurePosixPath(member.name)
                total += member.size

                if (
                    name.is_absolute()
                    or ".." in name.parts
                    or "\\" in member.name
                    or member.name in {"", "."}
                    or not (member.isfile() or member.isdir())
                    or member.size < 0
                    or total > _MAX_BYTES
                    or str(name) in names
                ):
                    raise SessionCacheError("Session cache contains an unsafe archive member.")

                names.add(str(name))

            profile.mkdir(parents=True, exist_ok=True, mode=0o700)

            for member in members:
                path = profile / member.name
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

                if member.isdir():
                    path.mkdir(exist_ok=True, mode=0o700)
                    continue

                stream = archive.extractfile(member)
                if stream is None:
                    raise SessionCacheError("Session cache member cannot be read.")

                with stream, path.open("xb") as output:
                    path.chmod(0o600)
                    output.write(stream.read())
    except (tarfile.TarError, OSError) as error:
        raise SessionCacheError("Session cache archive could not be restored.") from error
