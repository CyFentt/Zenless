from __future__ import annotations

import hashlib
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath


class AttachmentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ArchiveKind(StrEnum):
    ZIP = "ZIP"
    RAR = "RAR"
    SEVEN_ZIP = "7Z"


@dataclass(frozen=True, slots=True)
class AttachmentInfo:
    path: Path
    name: str
    extension: str
    mime: str
    size: int
    sha256: str
    archive: ArchiveKind | None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "extension": self.extension,
            "mime": self.mime,
            "size": self.size,
            "sha256": self.sha256,
            "archive": self.archive,
        }


@dataclass(frozen=True, slots=True)
class ArchivePolicy:
    max_files: int = 2_000
    max_file_size: int = 128 * 1024 * 1024
    max_total_size: int = 512 * 1024 * 1024
    max_compression_ratio: float = 200.0

    def __post_init__(self) -> None:
        if self.max_files < 1 or self.max_file_size < 1 or self.max_total_size < 1:
            raise ValueError("Archive limits must be positive.")
        if self.max_compression_ratio < 1:
            raise ValueError("Archive compression ratio must be at least one.")


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    path: PurePosixPath
    size: int
    compressed_size: int


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    root: Path
    files: tuple[Path, ...]
    bytes_extracted: int


@dataclass(frozen=True, slots=True)
class ProviderFileCapability:
    max_count: int
    max_file_size: int
    accepted_mime: tuple[str, ...] = ()
    accepted_extensions: tuple[str, ...] = ()
    accepts_archives: bool = False

    def __post_init__(self) -> None:
        if self.max_count < 1 or self.max_file_size < 1:
            raise ValueError("Provider file limits must be positive.")


@dataclass(frozen=True, slots=True)
class RejectedAttachment:
    name: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class AttachmentRoute:
    batches: tuple[tuple[AttachmentInfo, ...], ...]
    rejected: tuple[RejectedAttachment, ...]
    extraction_roots: tuple[Path, ...]


class AttachmentInspector:
    _MAGIC: tuple[tuple[bytes, str, ArchiveKind | None], ...] = (
        (b"\x37\x7a\xbc\xaf\x27\x1c", "application/x-7z-compressed", ArchiveKind.SEVEN_ZIP),
        (b"Rar!\x1a\x07", "application/vnd.rar", ArchiveKind.RAR),
        (b"\x89PNG\r\n\x1a\n", "image/png", None),
        (b"\xff\xd8\xff", "image/jpeg", None),
        (b"GIF87a", "image/gif", None),
        (b"GIF89a", "image/gif", None),
        (b"%PDF-", "application/pdf", None),
    )
    _TEXT_EXTENSIONS = {
        ".c",
        ".cpp",
        ".css",
        ".csv",
        ".h",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".lua",
        ".luau",
        ".md",
        ".py",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }

    def __init__(self, *, max_file_size: int = 512 * 1024 * 1024) -> None:
        if max_file_size < 1:
            raise ValueError("Attachment size limit must be positive.")
        self.max_file_size = max_file_size

    def inspect(self, path: Path) -> AttachmentInfo:
        resolved = path.resolve()
        if not resolved.is_file():
            raise AttachmentError("ATTACHMENT_NOT_FOUND", f"Attachment not found: {path.name}")
        size = resolved.stat().st_size
        if size > self.max_file_size:
            raise AttachmentError("ATTACHMENT_TOO_LARGE", f"Attachment exceeds {self.max_file_size} bytes.")
        with resolved.open("rb") as stream:
            sample = stream.read(8_192)
            hasher = hashlib.sha256()
            hasher.update(sample)
            while chunk := stream.read(1024 * 1024):
                hasher.update(chunk)
        mime, archive = self._detect(sample, resolved.suffix.casefold())
        return AttachmentInfo(
            path=resolved,
            name=resolved.name,
            extension=resolved.suffix.casefold(),
            mime=mime,
            size=size,
            sha256=hasher.hexdigest(),
            archive=archive,
        )

    def _detect(self, sample: bytes, extension: str) -> tuple[str, ArchiveKind | None]:
        if sample.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            return "application/zip", ArchiveKind.ZIP
        for marker, mime, archive in self._MAGIC:
            if sample.startswith(marker):
                return mime, archive
        if sample.startswith(b"RIFF") and sample[8:12] == b"WEBP":
            return "image/webp", None
        if extension in self._TEXT_EXTENSIONS or self._is_text(sample):
            return "text/plain", None
        return "application/octet-stream", None

    @staticmethod
    def _is_text(sample: bytes) -> bool:
        if b"\x00" in sample:
            return False
        try:
            sample.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False


class ArchiveExtractor:
    _WINDOWS_RESERVED = {
        "AUX",
        "CON",
        "NUL",
        "PRN",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
    _WINDOWS_INVALID = re.compile(r"[<>:\"|?*]")

    def __init__(self, policy: ArchivePolicy | None = None) -> None:
        self.policy = policy or ArchivePolicy()

    def inspect(self, archive: Path) -> tuple[ArchiveEntry, ...]:
        kind = AttachmentInspector().inspect(archive).archive
        if kind is not ArchiveKind.ZIP:
            label = kind or "UNKNOWN"
            raise AttachmentError("ARCHIVE_UNSUPPORTED", f"Safe extraction is unavailable for {label} archives.")
        try:
            with zipfile.ZipFile(archive) as source:
                return self._validate(source.infolist())
        except zipfile.BadZipFile as exc:
            raise AttachmentError("ARCHIVE_INVALID", "The ZIP archive is invalid.") from exc

    def extract(self, archive: Path, destination: Path) -> ExtractionResult:
        archive = archive.resolve()
        destination = destination.resolve(strict=False)
        if destination.exists():
            raise AttachmentError("ARCHIVE_DESTINATION_EXISTS", "Archive destination must not already exist.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".zenless-extract-", dir=destination.parent)).resolve()
        entries: tuple[ArchiveEntry, ...] = ()
        extracted = 0
        try:
            with zipfile.ZipFile(archive) as source:
                entries = self._validate(source.infolist())
                members = {self._normalize(info.filename): info for info in source.infolist() if not info.is_dir()}
                for entry in entries:
                    target = (staging / Path(*entry.path.parts)).resolve(strict=False)
                    if not self._within(target, staging):
                        raise AttachmentError(
                            "ARCHIVE_PATH_TRAVERSAL", "Archive entry escapes the extraction directory."
                        )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    written = 0
                    with source.open(members[entry.path], "r") as reader, target.open("xb") as writer:
                        while chunk := reader.read(1024 * 1024):
                            written += len(chunk)
                            extracted += len(chunk)
                            if written > entry.size or written > self.policy.max_file_size:
                                raise AttachmentError(
                                    "ARCHIVE_SIZE_LIMIT", "An archive entry exceeded its declared size."
                                )
                            if extracted > self.policy.max_total_size:
                                raise AttachmentError(
                                    "ARCHIVE_SIZE_LIMIT", "The archive exceeded the extraction size limit."
                                )
                            writer.write(chunk)
            staging.replace(destination)
        except Exception:
            self._remove_staging(staging, destination.parent)
            raise
        files = tuple(destination / Path(*entry.path.parts) for entry in entries)
        return ExtractionResult(destination, files, extracted)

    def _validate(self, infos: list[zipfile.ZipInfo]) -> tuple[ArchiveEntry, ...]:
        entries: list[ArchiveEntry] = []
        files: set[str] = set()
        total_size = 0
        total_compressed = 0
        for info in infos:
            path = self._normalize(info.filename)
            self._validate_path(path)
            self._validate_type(info)
            if info.flag_bits & 1:
                raise AttachmentError("ARCHIVE_ENCRYPTED", "Encrypted archive entries are not supported.")
            if info.is_dir():
                continue
            key = path.as_posix().casefold()
            if key in files or any(parent.as_posix().casefold() in files for parent in path.parents if parent.parts):
                raise AttachmentError("ARCHIVE_PATH_COLLISION", "Archive entries contain a path collision.")
            if any(existing.startswith(f"{key}/") for existing in files):
                raise AttachmentError("ARCHIVE_PATH_COLLISION", "Archive entries contain a path collision.")
            files.add(key)
            if len(files) > self.policy.max_files:
                raise AttachmentError("ARCHIVE_FILE_LIMIT", "The archive contains too many files.")
            if info.file_size > self.policy.max_file_size:
                raise AttachmentError("ARCHIVE_SIZE_LIMIT", "An archive entry exceeds the file size limit.")
            ratio = (
                float("inf")
                if info.compress_size == 0 and info.file_size
                else info.file_size / max(1, info.compress_size)
            )
            if ratio > self.policy.max_compression_ratio:
                raise AttachmentError("ARCHIVE_RATIO_LIMIT", "An archive entry has a suspicious compression ratio.")
            total_size += info.file_size
            total_compressed += info.compress_size
            if total_size > self.policy.max_total_size:
                raise AttachmentError("ARCHIVE_SIZE_LIMIT", "The archive exceeds the extraction size limit.")
            entries.append(ArchiveEntry(path, info.file_size, info.compress_size))
        total_ratio = float("inf") if total_compressed == 0 and total_size else total_size / max(1, total_compressed)
        if total_ratio > self.policy.max_compression_ratio:
            raise AttachmentError("ARCHIVE_RATIO_LIMIT", "The archive has a suspicious compression ratio.")
        return tuple(entries)

    @staticmethod
    def _normalize(name: str) -> PurePosixPath:
        return PurePosixPath(name.replace("\\", "/"))

    def _validate_path(self, path: PurePosixPath) -> None:
        raw = path.as_posix()
        if not path.parts or raw.startswith("/") or raw.startswith("//") or re.match(r"^[A-Za-z]:", raw):
            raise AttachmentError("ARCHIVE_ABSOLUTE_PATH", "Archive entries must use relative paths.")
        if any(part in {"", ".", ".."} for part in path.parts):
            raise AttachmentError("ARCHIVE_PATH_TRAVERSAL", "Archive entries contain an unsafe path segment.")
        for part in path.parts:
            if part != part.rstrip(" .") or self._WINDOWS_INVALID.search(part):
                raise AttachmentError("ARCHIVE_UNSAFE_NAME", "Archive entries contain an unsafe Windows name.")
            stem = part.split(".", 1)[0].upper()
            if stem in self._WINDOWS_RESERVED:
                raise AttachmentError("ARCHIVE_UNSAFE_NAME", "Archive entries contain a reserved Windows name.")

    @staticmethod
    def _validate_type(info: zipfile.ZipInfo) -> None:
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise AttachmentError("ARCHIVE_SYMLINK", "Archive symbolic links are not allowed.")
        kind = stat.S_IFMT(mode)
        if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise AttachmentError("ARCHIVE_SPECIAL_FILE", "Archive special files are not allowed.")

    @staticmethod
    def _within(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    @classmethod
    def _remove_staging(cls, staging: Path, parent: Path) -> None:
        if staging.parent == parent.resolve() and staging.name.startswith(".zenless-extract-"):
            shutil.rmtree(staging, ignore_errors=True)


class AttachmentRouter:
    _PRIORITY_EXTENSIONS = {
        ".lua": 0,
        ".luau": 0,
        ".json": 1,
        ".toml": 1,
        ".yaml": 1,
        ".yml": 1,
        ".md": 2,
        ".txt": 2,
    }

    def __init__(self, inspector: AttachmentInspector | None = None, extractor: ArchiveExtractor | None = None) -> None:
        self.inspector = inspector or AttachmentInspector()
        self.extractor = extractor or ArchiveExtractor()

    def route(
        self,
        paths: list[Path],
        capability: ProviderFileCapability,
        *,
        extraction_root: Path | None = None,
    ) -> AttachmentRoute:
        accepted: list[AttachmentInfo] = []
        rejected: list[RejectedAttachment] = []
        extraction_roots: list[Path] = []
        pending = list(paths)
        while pending:
            path = pending.pop(0)
            try:
                info = self.inspector.inspect(path)
                if info.archive and not capability.accepts_archives:
                    if extraction_root is None:
                        raise AttachmentError(
                            "ARCHIVE_EXTRACTION_REQUIRED", "The provider does not accept this archive."
                        )
                    target = extraction_root.resolve() / uuid.uuid4().hex
                    result = self.extractor.extract(info.path, target)
                    extraction_roots.append(result.root)
                    pending[0:0] = list(result.files)
                    continue
                self._validate_provider(info, capability)
                accepted.append(info)
            except AttachmentError as exc:
                rejected.append(RejectedAttachment(path.name, exc.code, str(exc)))
        accepted.sort(key=self._rank)
        batches = tuple(
            tuple(accepted[index : index + capability.max_count])
            for index in range(0, len(accepted), capability.max_count)
        )
        return AttachmentRoute(batches, tuple(rejected), tuple(extraction_roots))

    @staticmethod
    def _validate_provider(info: AttachmentInfo, capability: ProviderFileCapability) -> None:
        if info.size > capability.max_file_size:
            raise AttachmentError("PROVIDER_FILE_TOO_LARGE", "The attachment exceeds the provider file size limit.")
        extensions = {value.casefold() for value in capability.accepted_extensions}
        mime_patterns = {value.casefold() for value in capability.accepted_mime}
        extension_allowed = not extensions or info.extension in extensions
        mime_allowed = (
            not mime_patterns
            or info.mime.casefold() in mime_patterns
            or any(
                pattern.endswith("/*") and info.mime.casefold().startswith(pattern[:-1]) for pattern in mime_patterns
            )
        )
        if not extension_allowed or not mime_allowed:
            raise AttachmentError(
                "PROVIDER_FILE_TYPE_UNSUPPORTED", "The provider does not accept this attachment type."
            )

    def _rank(self, info: AttachmentInfo) -> tuple[int, int, str]:
        priority = self._PRIORITY_EXTENSIONS.get(info.extension, 3 if info.mime.startswith("text/") else 4)
        return priority, info.size, info.name.casefold()
