from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

SOURCE_EXTENSIONS = {
    ".lua", ".luau", ".json", ".json5", ".toml", ".yaml", ".yml", ".md", ".txt", ".xml",
}
PRIVATE_PATTERNS = (
    ".env*", "*.pem", "*.key", "*.pfx", "*.p12", "credentials*", "secrets.*", "tokens.*",
    "id_rsa*", "id_ed25519*", ".code-search.toml",
)
PRIVATE_DIRECTORIES = {".git", ".ssh", ".aws", "secrets", "browser-profile", "browser-profiles"}


def safe_source_file(file_path: str, project_root: Path, portable_root: Path) -> bool:
    path = Path(file_path)
    try:
        resolved = path.resolve()
        relative = path.relative_to(project_root)
        if not resolved.is_relative_to(project_root) or not path.is_file():
            return False
        if resolved.is_relative_to(portable_root / "data") or resolved.is_relative_to(portable_root / "runtime"):
            return False
        if any(part.casefold() in PRIVATE_DIRECTORIES for part in relative.parts[:-1]):
            return False
        if any(fnmatch.fnmatchcase(path.name.casefold(), pattern) for pattern in PRIVATE_PATTERNS):
            return False
        if path.suffix.casefold() not in SOURCE_EXTENSIONS:
            return False
        cursor = path
        while cursor != project_root:
            if cursor.is_symlink() or cursor.is_junction():
                return False
            cursor = cursor.parent
        return True
    except (OSError, ValueError):
        return False


def configure_upstream(project_root: Path, portable_root: Path, index_root: Path) -> Any:
    from mcp_code_search import indexer, languages, server
    from mcp_code_search.config import Config

    if not project_root.is_dir():
        raise RuntimeError("The configured project directory is unavailable.")
    if not index_root.is_relative_to(portable_root / "runtime" / "index" / "scoped"):
        raise RuntimeError("Index storage must remain inside Rubra.")

    def load_config(cls: Any, project_path: Path | None = None) -> Any:
        if project_path is not None and Path(project_path).resolve() != project_root:
            raise RuntimeError("The indexer cannot access another project.")
        config = cls()
        config.storage.base_path = index_root
        config.embedding.provider = "sentence-transformers"
        config.embedding.model = "all-MiniLM-L6-v2"
        config.indexing.max_file_size_kb = 750
        config.indexing.batch_size = 16
        config.indexing.max_chunk_lines = 60
        config.search.snippet_max_lines = 36
        config.indexing.ignore_patterns.extend(PRIVATE_PATTERNS)
        config.indexing.ignore_patterns.extend(sorted(PRIVATE_DIRECTORIES))
        if portable_root.is_relative_to(project_root):
            prefix = portable_root.relative_to(project_root)
            config.indexing.ignore_patterns.extend(
                (prefix / directory).as_posix() + "/" for directory in ("runtime", "data")
            )
        return config

    original_scan = indexer.Indexer._scan_files
    original_read = indexer.Indexer._read_file

    def scan_files(instance: Any, path: str) -> list[str]:
        if Path(path).resolve() != project_root:
            raise RuntimeError("The indexer cannot scan another project.")
        return [
            file_path for file_path in original_scan(instance, path)
            if safe_source_file(file_path, project_root, portable_root)
        ]

    def read_file(instance: Any, file_path: str) -> str | None:
        if not safe_source_file(file_path, project_root, portable_root):
            return None
        return original_read(instance, file_path)

    Config.load = classmethod(load_config)
    indexer.Indexer._scan_files = scan_files
    indexer.Indexer._read_file = read_file
    languages.EXTENSION_TO_LANGUAGE[".luau"] = "luau"
    server._indexer = indexer.Indexer(Config.load())
    return server


def main() -> None:
    project_root = Path(os.environ["RUBRA_PROJECT_ROOT"]).resolve()
    portable_root = Path(os.environ["RUBRA_PORTABLE_ROOT"]).resolve()
    index_root = Path(os.environ["RUBRA_INDEX_ROOT"]).resolve()
    server = configure_upstream(project_root, portable_root, index_root)
    server.main()


if __name__ == "__main__":
    main()
