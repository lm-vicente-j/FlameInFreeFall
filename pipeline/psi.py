"""Network boundary for PSI downloads.

All network access goes through an injectable ``Opener`` so tests never touch
the network. PSI serves files in two steps: an API call returns a short-lived
signed S3 URL as plain text, then the file is streamed from that URL. The
signed URL is only followed when it points at a known PSI bucket, so a changed
or hostile API response cannot redirect the download elsewhere.
"""
import contextlib
import hashlib
import os
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

USER_AGENT = "FlameInFreeFall-Pipeline/1.0"
API = "https://psi.nasa.gov/geode-py/ws/studies"
TRUSTED_PREFIXES = (
    "https://psi-repo-prod.s3.amazonaws.com/",
    "https://psi-curation-prod.s3.amazonaws.com/",
)
ATTEMPTS = 3
CHUNK_BYTES = 1 << 16
MAX_SIGNED_URL_BYTES = 16 * 1024


class Readable(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


Opener = Callable[[str, float], AbstractContextManager[Readable]]


class UntrustedUrlError(ValueError):
    """PSI returned a download URL outside the trusted buckets."""


class BudgetExceededError(RuntimeError):
    """A transfer would exceed the number of bytes it was allowed to write."""


class SizeMismatchError(RuntimeError):
    """The downloaded size differs from the size PSI declared."""


def _trusted_url(url: str) -> bool:
    return url.startswith((API + "/", *TRUSTED_PREFIXES)) and not any(
        character.isspace() or ord(character) < 32 for character in url
    )


class _TrustedRedirects(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if not _trusted_url(newurl):
            raise UntrustedUrlError("Redirect outside the PSI download allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_opener(url: str, timeout: float) -> AbstractContextManager[Readable]:
    if not _trusted_url(url):
        raise UntrustedUrlError("URL outside the PSI download allowlist")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    response: AbstractContextManager[Readable] = build_opener(_TrustedRedirects()).open(request, timeout=timeout)
    return response


def resolve_signed_url(
    accession: str,
    filename: str,
    version: int,
    opener: Opener,
    timeout: float,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    # PSI resolves files by bare filename and version, not by full key.
    query = urlencode({"file": filename, "version": version, "redirect": "false"})
    url = f"{API}/{accession}/download?{query}"
    for attempt in range(ATTEMPTS):
        try:
            with opener(url, timeout) as response:
                payload = response.read(MAX_SIGNED_URL_BYTES + 1)
                if len(payload) > MAX_SIGNED_URL_BYTES:
                    raise UntrustedUrlError("Signed-URL response exceeds 16 KiB")
                signed = payload.decode("utf-8").strip()
            break
        except HTTPError as error:
            if 400 <= error.code < 500 or attempt == ATTEMPTS - 1:
                raise
            sleep(2**attempt)
        except OSError:
            if attempt == ATTEMPTS - 1:
                raise
            sleep(2**attempt)
    if not signed.startswith(TRUSTED_PREFIXES) or not _trusted_url(signed):
        raise UntrustedUrlError(f"Invalid or untrusted download URL for {accession} {filename}")
    return signed


def download_to(
    url: str,
    destination: Path,
    expected_bytes: int,
    max_bytes: int,
    opener: Opener,
    timeout: float,
) -> tuple[int, str]:
    """Stream ``url`` to ``destination``; return (bytes written, sha256).

    The file appears at ``destination`` only after the size check passed, so a
    partial or oversized transfer never looks like a valid sample.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    written = 0
    try:
        with opener(url, timeout) as response, partial.open("wb") as stream:
            # Never ask for more than one byte past the cap: that byte proves an
            # oversized transfer without pulling a whole extra chunk over the budget.
            while chunk := response.read(min(CHUNK_BYTES, max_bytes - written + 1)):
                if written + len(chunk) > max_bytes:
                    raise BudgetExceededError(
                        f"{destination.name}: transfer would exceed the {max_bytes}-byte limit; aborted"
                    )
                stream.write(chunk)
                digest.update(chunk)
                written += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if written != expected_bytes:
            raise SizeMismatchError(
                f"{destination.name}: received {written} bytes, PSI declared {expected_bytes}"
            )
        os.replace(partial, destination)
    except BaseException:
        with contextlib.suppress(OSError):
            partial.unlink()
        raise
    return written, digest.hexdigest()
