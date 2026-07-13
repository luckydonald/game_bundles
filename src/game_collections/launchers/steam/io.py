"""Locked, fail-closed Steam file staging, replacement, and restoration."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from game_collections.launchers.base import PlannedCollectionChange, SyncPlan
from game_collections.launchers.steam.discovery import account_id_from_steam_id, parse_login_users
from game_collections.launchers.steam.models import (
    CloudStorageEntry,
    CloudStorageNamespaceFile,
    CloudStorageNamespacesFile,
    LoginUsersFile,
    ModifiedKeysFile,
    SteamCollectionPayload,
    SteamPidFile,
    StrictModel,
    parse_json_strict,
)


MAX_STEAM_FILE_SIZE = 4 * 1024 * 1024
NAMESPACE_NAME = "cloud-storage-namespace-1.json"
MODIFIED_NAME = "cloud-storage-namespace-1.modified.json"
MANIFEST_NAME = "manifest.json"
STEAM_USER_COLLECTION_ID_PATTERN = re.compile(r"^uc-[A-Za-z0-9*+_-]+$")
MANUAL_COLLECTION_HINT = (
    "To create it in Steam: open your Library, select all games (click the first, "
    "scroll to the bottom, shift-click the last), then click and hold any highlighted "
    "tile and drag it into the main pane. Hover the 'DRAG and HOLD HERE to view All "
    "Collections' area top-left, then drop onto the collection (or onto '+ DRAG HERE TO "
    "CREATE A NEW COLLECTION' and name it), then close Steam."
)


class SteamIoError(RuntimeError):
    """A Steam IO invariant failed before or during a guarded operation."""

# end class SteamIoError


class FileIdentity(StrictModel):
    """Metadata and content identity captured from an open file descriptor."""

    path: str
    device: int
    inode: int
    owner: int
    group: int
    mode: int
    links: int
    size: int
    mtime_ns: int
    sha256: str

# end class FileIdentity


class ReplacementRecord(StrictModel):
    """One source/candidate/backup relationship in a staged transaction."""

    source: FileIdentity
    candidate_name: str
    candidate_sha256: str
    backup_name: str
    backup_sha256: str

# end class ReplacementRecord


class StagingManifest(StrictModel):
    """Self-contained, validated description of a Steam replacement transaction."""

    format_version: int = Field(default=1)
    launcher: str
    steam_root: str
    steam_id: str
    account_id: int
    created_at: str
    replacements: list[ReplacementRecord]
    changes: list[PlannedCollectionChange]
    status: str = "staged"

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.format_version != 1 or self.launcher != "steam":
            raise ValueError("unsupported staging manifest")
        # end if
        names = [Path(record.source.path).name for record in self.replacements]
        if names != [NAMESPACE_NAME, MODIFIED_NAME]:
            raise ValueError(f"unexpected Steam replacement set: {names}")
        # end if
        return self
    # end def validate_manifest

# end class StagingManifest


@dataclass(frozen=True, slots=True)
class LockedFileSnapshot:
    """Bytes and descriptor-derived identity from one guarded read."""

    identity: FileIdentity
    data: bytes

# end class LockedFileSnapshot


@dataclass(frozen=True, slots=True)
class SteamSnapshot:
    """All validated Steam state needed for a pure candidate transformation."""

    users: LoginUsersFile
    namespaces: CloudStorageNamespacesFile
    namespace: CloudStorageNamespaceFile
    modified: ModifiedKeysFile
    namespace_file: LockedFileSnapshot
    modified_file: LockedFileSnapshot

# end class SteamSnapshot


class SteamFileGateway:
    """The sole code path allowed to read or replace Steam configuration files."""

    def __init__(self, steam_root: Path, steam_id: str) -> None:
        self.steam_root = steam_root.resolve(strict=True)
        self.steam_id = steam_id
        self.account_id = account_id_from_steam_id(steam_id)
        self.cloud_root = (
            self.steam_root / "userdata" / str(self.account_id) / "config/cloudstorage"
        ).resolve(strict=True)
        self._require_contained(self.cloud_root, self.steam_root)
        self.paths = {
            "login": self.steam_root / "config/loginusers.vdf",
            "namespaces": self.cloud_root / "cloud-storage-namespaces.json",
            "namespace": self.cloud_root / NAMESPACE_NAME,
            "modified": self.cloud_root / MODIFIED_NAME,
        }
    # end def __init__

    @classmethod
    def discover(cls, steam_root: Path, steam_id: str | None = None) -> Self:
        """Select an account through the same locked file reader used for synchronization."""
        resolved_root = steam_root.resolve(strict=True)
        probe = object.__new__(cls)
        probe.steam_root = resolved_root
        login = probe._read_locked(resolved_root / "config/loginusers.vdf")
        try:
            users = parse_login_users(login.data)
        except ValueError as error:
            raise SteamIoError(f"unsupported loginusers.vdf: {error}") from error
        # end try
        selected = steam_id or users.most_recent_steam_id
        if selected not in users.root:
            raise SteamIoError("selected SteamID is absent from loginusers.vdf")
        # end if
        return cls(resolved_root, selected)
    # end def discover

    def load_snapshot(self) -> SteamSnapshot:
        """Read and validate every format used to compose a candidate."""
        login = self._read_locked(self.paths["login"])
        namespaces_file = self._read_locked(self.paths["namespaces"])
        namespace_file = self._read_locked(self.paths["namespace"])
        modified_file = self._read_locked(self.paths["modified"])
        try:
            users = parse_login_users(login.data)
            namespaces = parse_json_strict(namespaces_file.data, CloudStorageNamespacesFile)
            namespace = parse_json_strict(namespace_file.data, CloudStorageNamespaceFile)
            modified = parse_json_strict(modified_file.data, ModifiedKeysFile)
            self._validate_snapshot(users, namespace, modified)
        except ValueError as error:
            raise SteamIoError(f"unsupported Steam format; refusing IO: {error}") from error
        # end try
        return SteamSnapshot(
            users=users,
            namespaces=namespaces,
            namespace=namespace,
            modified=modified,
            namespace_file=namespace_file,
            modified_file=modified_file,
        )
    # end def load_snapshot

    def read_collection(self, name: str) -> SteamCollectionPayload:
        """Read a single named local Steam collection (case-insensitive) for use as an ownership source."""
        by_name = {payload.name.casefold(): payload for payload in self.read_collections()}
        match = by_name.get(name.casefold())
        if match is None:
            available = ", ".join(sorted(payload.name for payload in by_name.values())) or "(none found locally)"
            raise SteamIoError(
                f"Steam collection {name!r} not found locally; available collections: {available}.\n"
                f"{MANUAL_COLLECTION_HINT}"
            )
        # end if
        if match.filterSpec is not None:
            raise SteamIoError(
                f"Steam collection {name!r} is a dynamic (filter-based) collection; "
                "only a manually curated (static) collection can be used as an ownership source"
            )
        # end if
        return match
    # end def read_collection

    def read_collections(self) -> tuple[SteamCollectionPayload, ...]:
        """Read every active Steam collection through the validated gateway snapshot."""
        snapshot = self.load_snapshot()
        payloads: list[SteamCollectionPayload] = []
        for key, entry in snapshot.namespace.root:
            if not key.startswith("user-collections.") or entry.is_deleted:
                continue
            # end if
            payloads.append(SteamCollectionPayload.from_entry(entry))
        # end for
        return tuple(payloads)
    # end def read_collections

    def stage(self, plan: SyncPlan, output_root: Path) -> Path:
        """Write candidates and backups outside Steam without modifying Steam."""
        if plan.launcher != "steam" or plan.account != self.steam_id:
            raise SteamIoError("sync plan account or launcher does not match gateway")
        # end if
        snapshot = self.load_snapshot()
        namespace, modified = self._build_candidates(snapshot, plan)
        namespace_bytes = _render_root_model(namespace)
        modified_bytes = _render_root_model(modified)
        self._validate_candidate_pair(namespace_bytes, modified_bytes)

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        staged_dir = output_root.expanduser().resolve() / f"game-collections-steam-{stamp}"
        staged_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        candidates = {
            NAMESPACE_NAME: namespace_bytes,
            MODIFIED_NAME: modified_bytes,
        }
        originals = {
            NAMESPACE_NAME: snapshot.namespace_file,
            MODIFIED_NAME: snapshot.modified_file,
        }
        replacements: list[ReplacementRecord] = []
        for name in (NAMESPACE_NAME, MODIFIED_NAME):
            original = originals[name]
            candidate_name = f"candidate-{name}"
            backup_name = f"backup-{name}"
            self._write_new_staged_file(staged_dir / candidate_name, candidates[name])
            self._write_new_staged_file(staged_dir / backup_name, original.data)
            replacements.append(
                ReplacementRecord(
                    source=original.identity,
                    candidate_name=candidate_name,
                    candidate_sha256=_sha256(candidates[name]),
                    backup_name=backup_name,
                    backup_sha256=_sha256(original.data),
                )
            )
        # end for
        manifest = StagingManifest(
            launcher="steam",
            steam_root=str(self.steam_root),
            steam_id=self.steam_id,
            account_id=self.account_id,
            created_at=datetime.now(UTC).isoformat(),
            replacements=replacements,
            changes=plan.changes,
        )
        self._write_new_staged_file(
            staged_dir / MANIFEST_NAME,
            (json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode(),
        )
        report = self._render_report(manifest)
        self._write_new_staged_file(staged_dir / "README.txt", report.encode())
        return staged_dir
    # end def stage

    def apply(self, staged_dir: Path, confirm: Callable[[str], str]) -> None:
        """Revalidate and atomically install a staged two-file transaction."""
        staged = staged_dir.resolve(strict=True)
        manifest = self._load_manifest(staged)
        self._validate_manifest_target(manifest)
        self.require_steam_stopped()
        preliminary = {
            NAMESPACE_NAME: self._read_locked(self.paths["namespace"]),
            MODIFIED_NAME: self._read_locked(self.paths["modified"]),
        }
        for record in manifest.replacements:
            name = Path(record.source.path).name
            if preliminary[name].identity != record.source:
                raise SteamIoError(f"Steam source changed after staging: {record.source.path}")
            # end if
        # end for
        current = self.load_snapshot()
        current_by_name = {
            NAMESPACE_NAME: current.namespace_file,
            MODIFIED_NAME: current.modified_file,
        }
        candidate_bytes: dict[str, bytes] = {}
        for record in manifest.replacements:
            name = Path(record.source.path).name
            live = current_by_name[name]
            if live.identity != record.source or live.identity != preliminary[name].identity:
                raise SteamIoError(f"Steam source changed after staging: {record.source.path}")
            # end if
            candidate = self._read_staged(staged, record.candidate_name, record.candidate_sha256)
            backup = self._read_staged(staged, record.backup_name, record.backup_sha256)
            if backup != live.data:
                raise SteamIoError(f"backup no longer matches Steam source: {record.source.path}")
            # end if
            candidate_bytes[name] = candidate
        # end for
        self._validate_candidate_pair(candidate_bytes[NAMESPACE_NAME], candidate_bytes[MODIFIED_NAME])
        answer = confirm("Type REPLACE to replace the two validated Steam files")
        if answer != "REPLACE":
            raise SteamIoError("replacement confirmation declined")
        # end if
        self.require_steam_stopped()
        replaced_namespace = False
        try:
            self._atomic_replace(self.paths["namespace"], candidate_bytes[NAMESPACE_NAME], current.namespace_file.identity)
            replaced_namespace = True
            self._atomic_replace(self.paths["modified"], candidate_bytes[MODIFIED_NAME], current.modified_file.identity)
        except Exception as error:
            if replaced_namespace:
                self._atomic_replace(
                    self.paths["namespace"],
                    current.namespace_file.data,
                    current.namespace_file.identity,
                )
            # end if
            raise SteamIoError(f"Steam replacement failed; rollback attempted: {error}") from error
        # end try
        self._verify_installed(candidate_bytes)
        self._write_completion_manifest(staged, manifest, "applied")
    # end def apply

    def restore(self, staged_dir: Path, confirm: Callable[[str], str]) -> None:
        """Restore both verified backups from a completed staging directory."""
        staged = staged_dir.resolve(strict=True)
        manifest = self._load_manifest(staged)
        self._validate_manifest_target(manifest)
        self.require_steam_stopped()
        backups: dict[str, bytes] = {}
        identities: dict[str, FileIdentity] = {}
        for record in manifest.replacements:
            name = Path(record.source.path).name
            backups[name] = self._read_staged(staged, record.backup_name, record.backup_sha256)
            identities[name] = record.source
        # end for
        self._validate_candidate_pair(backups[NAMESPACE_NAME], backups[MODIFIED_NAME])
        answer = confirm("Type RESTORE to restore both Steam backups")
        if answer != "RESTORE":
            raise SteamIoError("restore confirmation declined")
        # end if
        self.require_steam_stopped()
        current_namespace = self._read_locked(self.paths["namespace"])
        try:
            self._atomic_replace(self.paths["namespace"], backups[NAMESPACE_NAME], identities[NAMESPACE_NAME])
            self._atomic_replace(self.paths["modified"], backups[MODIFIED_NAME], identities[MODIFIED_NAME])
        except Exception as error:
            self._atomic_replace(
                self.paths["namespace"],
                current_namespace.data,
                current_namespace.identity,
            )
            raise SteamIoError(f"Steam restoration failed; rollback attempted: {error}") from error
        # end try
        self._verify_installed(backups)
        self._write_completion_manifest(staged, manifest, "restored")
    # end def restore

    def require_steam_stopped(self) -> None:
        """Fail if Steam's PID or IPC pipe indicates a live client."""
        global_steam = Path.home() / ".steam"
        use_global_signals = False
        global_root = global_steam / "root"
        if global_root.exists():
            try:
                use_global_signals = global_root.resolve(strict=True) == self.steam_root
            except OSError:
                use_global_signals = False
            # end try
        # end if
        pid_paths = [self.steam_root / "steam.pid"]
        if use_global_signals:
            pid_paths.append(global_steam / "steam.pid")
        # end if
        for pid_path in pid_paths:
            if not pid_path.exists():
                continue
            # end if
            try:
                pid = SteamPidFile.model_validate(int(pid_path.read_text(encoding="ascii").strip())).root
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except (OSError, ValueError) as error:
                raise SteamIoError(f"cannot prove Steam is stopped from {pid_path}: {error}") from error
            # end try
            raise SteamIoError(f"Steam process {pid} is still running; close Steam before continuing")
        # end for
        pipe_paths = [self.steam_root / "steam.pipe"]
        if use_global_signals:
            pipe_paths.append(global_steam / "steam.pipe")
        # end if
        for pipe_path in pipe_paths:
            if pipe_path.exists():
                raise SteamIoError(f"Steam IPC pipe still exists: {pipe_path}")
            # end if
        # end for
    # end def require_steam_stopped

    def _build_candidates(
        self,
        snapshot: SteamSnapshot,
        plan: SyncPlan,
    ) -> tuple[CloudStorageNamespaceFile, ModifiedKeysFile]:
        entries = list(snapshot.namespace.root)
        entry_map = dict(entries)
        payloads: dict[str, SteamCollectionPayload] = {}
        names: dict[str, str] = {}
        for key, entry in entries:
            if not key.startswith("user-collections.") or entry.is_deleted:
                continue
            # end if
            payload = SteamCollectionPayload.from_entry(entry)
            payloads[payload.id] = payload
            names[payload.name.casefold()] = payload.id
        # end for
        bootstrap = entry_map.get("collection-bootstrap-complete")
        if bootstrap is None or bootstrap.value != "true":
            raise SteamIoError("Steam collection bootstrap is not complete")
        # end if
        modified = list(snapshot.modified.root)
        timestamp = max(int(time.time()), max(entry.timestamp for _key, entry in entries) + 1)
        targets = [change.target_id for change in plan.changes]
        if len(targets) != len(set(targets)):
            raise SteamIoError("Steam sync plan contains duplicate collection targets")
        # end if
        for change in plan.changes:
            collection_id = change.target_id
            if not STEAM_USER_COLLECTION_ID_PATTERN.fullmatch(collection_id):
                raise SteamIoError(f"Steam sync plan has an unsafe collection target: {collection_id!r}")
            # end if
            key = f"user-collections.{collection_id}"
            existing = payloads.get(collection_id)
            if change.action == "delete":
                if existing is None:
                    continue
                # end if
                if existing.name != change.name:
                    raise SteamIoError(
                        f"managed Steam collection changed before deletion: {change.name!r}"
                    )
                # end if
                if existing.filterSpec is not None:
                    raise SteamIoError(f"managed Steam collection became dynamic: {change.name!r}")
                # end if
                entry = CloudStorageEntry(
                    key=key,
                    timestamp=timestamp,
                    is_deleted=True,
                    conflictResolutionMethod="custom",
                    strMethodId="union-collections",
                )
                timestamp += 1
                index = next(index for index, pair in enumerate(entries) if pair[0] == key)
                entries[index] = (key, entry)
                entry_map[key] = entry
                del payloads[collection_id]
                names.pop(existing.name.casefold(), None)
                if key not in modified:
                    modified.append(key)
                # end if
                continue
            # end if
            if change.list_id is None or collection_id != steam_collection_id(change.list_id):
                raise SteamIoError(f"Steam sync plan has an invalid collection target: {collection_id!r}")
            # end if
            collision = names.get(change.name.casefold())
            if collision is not None and collision != collection_id:
                raise SteamIoError(f"Steam collection name already exists: {change.name!r}")
            # end if
            if existing is not None and existing.filterSpec is not None:
                raise SteamIoError(f"managed Steam collection became dynamic: {change.name!r}")
            # end if
            desired = {_parse_steam_compact_id(raw) for raw in change.added_ids}
            added = sorted(desired | set(existing.added if existing else []))
            removed = sorted(set(existing.removed if existing else []) - desired)
            payload = SteamCollectionPayload(
                id=collection_id,
                name=change.name,
                added=added,
                removed=removed,
            )
            entry = CloudStorageEntry(
                key=key,
                timestamp=timestamp,
                value=json.dumps(payload.model_dump(exclude_none=True), separators=(",", ":")),
                conflictResolutionMethod="custom",
                strMethodId="union-collections",
            )
            timestamp += 1
            if key in entry_map:
                index = next(index for index, pair in enumerate(entries) if pair[0] == key)
                entries[index] = (key, entry)
            else:
                entries.append((key, entry))
            # end if
            entry_map[key] = entry
            if existing is not None:
                names.pop(existing.name.casefold(), None)
            # end if
            payloads[collection_id] = payload
            names[payload.name.casefold()] = payload.id
            if key not in modified:
                modified.append(key)
            # end if
        # end for
        return CloudStorageNamespaceFile(root=entries), ModifiedKeysFile(root=modified)
    # end def _build_candidates

    def _validate_snapshot(
        self,
        users: LoginUsersFile,
        namespace: CloudStorageNamespaceFile,
        modified: ModifiedKeysFile,
    ) -> None:
        if self.steam_id not in users.root:
            raise SteamIoError("selected SteamID is absent from loginusers.vdf")
        # end if
        namespace_keys = {key for key, _entry in namespace.root}
        unknown_dirty = set(modified.root) - namespace_keys
        if unknown_dirty:
            raise SteamIoError(f"modified keys are missing from namespace: {sorted(unknown_dirty)}")
        # end if
        for key, entry in namespace.root:
            if key.startswith("user-collections.") and not entry.is_deleted:
                SteamCollectionPayload.from_entry(entry)
            # end if
        # end for
    # end def _validate_snapshot

    def _validate_candidate_pair(self, namespace_data: bytes, modified_data: bytes) -> None:
        namespace = parse_json_strict(namespace_data, CloudStorageNamespaceFile)
        modified = parse_json_strict(modified_data, ModifiedKeysFile)
        keys = {key for key, _entry in namespace.root}
        if set(modified.root) - keys:
            raise SteamIoError("candidate modified keys do not exist in candidate namespace")
        # end if
        for key, entry in namespace.root:
            if key.startswith("user-collections.") and not entry.is_deleted:
                payload = SteamCollectionPayload.from_entry(entry)
                if key != f"user-collections.{payload.id}":
                    raise SteamIoError(f"collection key/id mismatch: {key}")
                # end if
            # end if
        # end for
    # end def _validate_candidate_pair

    def _read_locked(self, path: Path) -> LockedFileSnapshot:
        resolved_parent = path.parent.resolve(strict=True)
        self._require_contained(resolved_parent, self.steam_root)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        # end if
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise SteamIoError(f"could not safely open Steam file {path}: {error}") from error
        # end try
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                raise SteamIoError(f"Steam file is not a single-link regular file: {path}")
            # end if
            if hasattr(os, "getuid") and details.st_uid != os.getuid():
                raise SteamIoError(f"Steam file is not owned by the current user: {path}")
            # end if
            if stat.S_IMODE(details.st_mode) & 0o022:
                raise SteamIoError(f"Steam file is group/world writable: {path}")
            # end if
            if details.st_size > MAX_STEAM_FILE_SIZE:
                raise SteamIoError(f"Steam file exceeds size limit: {path}")
            # end if
            data = b""
            while len(data) < details.st_size:
                chunk = os.read(descriptor, min(65_536, details.st_size - len(data)))
                if not chunk:
                    break
                # end if
                data += chunk
            # end while
            if len(data) != details.st_size:
                raise SteamIoError(f"short read from Steam file: {path}")
            # end if
        finally:
            os.close(descriptor)
        # end try
        identity = FileIdentity(
            path=str(path.resolve(strict=True)),
            device=details.st_dev,
            inode=details.st_ino,
            owner=details.st_uid,
            group=details.st_gid,
            mode=stat.S_IMODE(details.st_mode),
            links=details.st_nlink,
            size=details.st_size,
            mtime_ns=details.st_mtime_ns,
            sha256=_sha256(data),
        )
        return LockedFileSnapshot(identity=identity, data=data)
    # end def _read_locked

    def _atomic_replace(self, target: Path, data: bytes, identity: FileIdentity) -> None:
        self._require_contained(target.parent.resolve(strict=True), self.steam_root)
        temporary = target.with_name(f".{target.name}.game-collections-{os.getpid()}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        # end if
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            # end while
            os.fchmod(descriptor, identity.mode)
            if hasattr(os, "fchown"):
                os.fchown(descriptor, identity.owner, identity.group)
            # end if
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        # end try
        try:
            os.replace(temporary, target)
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            # end try
        finally:
            if temporary.exists():
                temporary.unlink()
            # end if
        # end try
    # end def _atomic_replace

    def _verify_installed(self, expected: dict[str, bytes]) -> None:
        for name, data in expected.items():
            actual = self._read_locked(self.cloud_root / name)
            if actual.data != data:
                raise SteamIoError(f"post-write verification failed for {name}")
            # end if
        # end for
    # end def _verify_installed

    def _load_manifest(self, staged: Path) -> StagingManifest:
        raw = self._read_staged(staged, MANIFEST_NAME, expected_hash=None)
        try:
            return StagingManifest.model_validate_json(raw)
        except ValueError as error:
            raise SteamIoError(f"invalid staging manifest: {error}") from error
        # end try
    # end def _load_manifest

    def _validate_manifest_target(self, manifest: StagingManifest) -> None:
        if (
            manifest.steam_root != str(self.steam_root)
            or manifest.steam_id != self.steam_id
            or manifest.account_id != self.account_id
        ):
            raise SteamIoError("staging manifest targets a different Steam installation or account")
        # end if
    # end def _validate_manifest_target

    def _read_staged(self, staged: Path, name: str, expected_hash: str | None) -> bytes:
        if Path(name).name != name:
            raise SteamIoError(f"unsafe staged filename: {name!r}")
        # end if
        path = staged / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != staged:
            raise SteamIoError(f"unsafe staged file: {path}")
        # end if
        data = path.read_bytes()
        if expected_hash is not None and _sha256(data) != expected_hash:
            raise SteamIoError(f"staged file hash changed: {path}")
        # end if
        return data
    # end def _read_staged

    def _write_new_staged_file(self, path: Path, data: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        # end if
        descriptor = os.open(path, flags, 0o600)
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            # end while
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        # end try
    # end def _write_new_staged_file

    def _write_completion_manifest(
        self,
        staged: Path,
        manifest: StagingManifest,
        status: str,
    ) -> None:
        completed = manifest.model_copy(update={"status": status})
        path = staged / f"manifest-{status}.json"
        self._write_new_staged_file(
            path,
            (json.dumps(completed.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode(),
        )
    # end def _write_completion_manifest

    def _render_report(self, manifest: StagingManifest) -> str:
        lines = [
            "Game Collections Steam synchronization",
            "",
            f"Steam account: {manifest.steam_id}",
            f"Steam root: {manifest.steam_root}",
            "",
            "Inspect these replacements before confirming:",
        ]
        for record in manifest.replacements:
            lines.extend(
                [
                    f"  source: {record.source.path}",
                    f"  candidate: {record.candidate_name}",
                    f"  backup: {record.backup_name}",
                ]
            )
        # end for
        lines.extend(["", "Planned collection operations:"])
        for change in manifest.changes:
            identifier = change.list_id or change.target_id
            lines.append(f"  {change.action}: {identifier} ({change.name})")
        # end for
        lines.extend(
            [
                "",
                "Restore only while Steam is stopped:",
                "  game-collections restore steam <this-staging-directory>",
                "",
            ]
        )
        return "\n".join(lines)
    # end def _render_report

    @staticmethod
    def _require_contained(path: Path, root: Path) -> None:
        try:
            path.relative_to(root)
        except ValueError as error:
            raise SteamIoError(f"path escapes verified Steam root: {path}") from error
        # end try
    # end def _require_contained

# end class SteamFileGateway


def steam_collection_id(list_id: str) -> str:
    """Derive Steam's user-collection-shaped stable ID from a logical list ID."""
    digest = hashlib.sha256(list_id.encode("utf-8")).digest()[:9]
    encoded = base64.b64encode(digest).decode("ascii").replace("/", "*+").replace("%", "**")
    return f"uc-{encoded}"
# end def steam_collection_id


def default_staging_root() -> Path:
    """Choose an inspectable default outside Steam."""
    desktop = Path.home() / "Desktop"
    return desktop if desktop.is_dir() else Path.cwd()
# end def default_staging_root


def _parse_steam_compact_id(value: str) -> int:
    provider, separator, raw_app_id = value.partition(":")
    if provider != "steam" or not separator:
        raise SteamIoError(f"Steam sync plan contains non-Steam ID: {value!r}")
    # end if
    try:
        app_id = int(raw_app_id)
    except ValueError as error:
        raise SteamIoError(f"invalid Steam app ID in sync plan: {value!r}") from error
    # end try
    if app_id <= 0:
        raise SteamIoError(f"invalid Steam app ID in sync plan: {value!r}")
    # end if
    return app_id
# end def _parse_steam_compact_id


def _render_root_model(model: CloudStorageNamespaceFile | ModifiedKeysFile) -> bytes:
    data = model.model_dump(mode="json", exclude_none=True)
    return json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
# end def _render_root_model


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
# end def _sha256
