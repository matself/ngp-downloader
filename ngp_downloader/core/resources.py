"""Download resources (STAC assets) linked from reference objects.

Generic for all NGP datasets: resources are grouped by their STAC role as
found in the data, deduplicated by href (many reference objects can point to
the same domain object, e.g. every provision in a detaljplan) and saved as is.
Only links to the NGP download API are fetched; other links (e.g. Fornsök)
are web pages and are left as links.
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

from qgis.core import Qgis, QgsBlockingNetworkRequest, QgsFeedback, QgsMessageLog, QgsTask
from qgis.PyQt.QtCore import QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkRequest

from ..config import DOWNLOAD_PATH, PLUGIN_NAME

MAX_WORKERS = 4  # Parallel downloads; kind to the API while cutting wait time.
MANIFEST_NAME = "resurser.json"

EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "image/tiff": ".tif",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


@dataclass(frozen=True)
class Resource:
    href: str
    role: str
    title: str
    length: int | None = None


@dataclass
class RoleSummary:
    role: str
    title: str
    files: int = 0
    known_bytes: int = 0
    unknown_size: int = 0


def is_downloadable(href: str) -> bool:
    return DOWNLOAD_PATH in href


def parse_assets(value: Any) -> list[Resource]:
    """Resources from one feature's `assets` column (a JSON string)."""
    try:
        assets = json.loads(value) if isinstance(value, str) else {}
    except ValueError:
        return []
    resources = []
    for asset in assets.values():
        href = asset.get("href")
        if not href:
            continue
        roles = asset.get("roles") or ["okänd"]
        resources.append(
            Resource(href, roles[0], asset.get("title") or roles[0], asset.get("length"))
        )
    return resources


def summarize(assets_values: Iterable[Any]) -> tuple[list[RoleSummary], dict[str, int]]:
    """Per-role summary of unique downloadable files, plus link-only roles and counts."""
    seen: set[str] = set()
    summaries: dict[str, RoleSummary] = {}
    links: dict[str, int] = {}
    for value in assets_values:
        for r in parse_assets(value):
            if not is_downloadable(r.href):
                links[r.title] = links.get(r.title, 0) + 1
                continue
            if r.href in seen:
                continue
            seen.add(r.href)
            s = summaries.setdefault(r.role, RoleSummary(r.role, r.title))
            s.files += 1
            if r.length:
                s.known_bytes += r.length
            else:
                s.unknown_size += 1
    return list(summaries.values()), links


def _safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "fil"


def _filename(reply, href: str) -> str:
    disposition = bytes(reply.rawHeader(b"Content-Disposition")).decode("utf-8", "replace")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition, re.IGNORECASE)
    if match:
        return _safe_name(unquote(match.group(1)))
    content_type = bytes(reply.rawHeader(b"Content-Type")).decode().split(";")[0].strip()
    ext = ".json" if content_type.endswith("json") else EXTENSIONS.get(content_type, ".bin")
    return _safe_name(href.rstrip("/").rsplit("/", 1)[-1]) + ext


class ResourceTask(QgsTask):
    """Downloads resources in parallel; skips files already in the manifest."""

    completed = pyqtSignal(dict, list)  # href -> absolute path, failure messages
    failed = pyqtSignal(str)

    def __init__(self, authcfg: str, resources: list[Resource], target_dir: Path):
        super().__init__(f"NGP: hämtar {len(resources)} resurser", QgsTask.Flag.CanCancel)
        self.authcfg = authcfg
        self.resources = resources
        self.target_dir = target_dir
        self.paths: dict[str, str] = {}
        self.failures: list[str] = []
        self.error: str | None = None
        self._feedback = QgsFeedback()
        self._lock = threading.Lock()
        self._manifest: dict[str, str] = {}
        self._reserved: set[str] = set()  # names chosen by running downloads

    def cancel(self) -> None:
        self._feedback.cancel()
        super().cancel()

    # --- manifest --------------------------------------------------------

    def _manifest_path(self) -> Path:
        return self.target_dir / MANIFEST_NAME

    def _load_manifest(self) -> None:
        try:
            self._manifest = json.loads(self._manifest_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._manifest = {}

    def _save_manifest(self) -> None:
        self._manifest_path().write_text(
            json.dumps(self._manifest, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # --- work ------------------------------------------------------------

    def _download(self, resource: Resource) -> str:
        """Fetch one resource; returns its path relative to target_dir."""
        blocking = QgsBlockingNetworkRequest()
        blocking.setAuthCfg(self.authcfg)
        error = blocking.get(QNetworkRequest(QUrl(resource.href)), True, self._feedback)
        reply = blocking.reply()
        if error != QgsBlockingNetworkRequest.ErrorCode.NoError:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            raise RuntimeError(f"HTTP {status}: {blocking.errorMessage()}")

        folder = self.target_dir / _safe_name(resource.role)
        name = _filename(reply, resource.href)
        with self._lock:
            folder.mkdir(parents=True, exist_ok=True)
            taken = set(self._manifest.values()) | self._reserved
            relative = f"{folder.name}/{name}"
            if relative in taken or (folder / name).exists():
                # Same file name for a different resource: keep both.
                uid = resource.href.rstrip("/").rsplit("/", 1)[-1][:8]
                relative = f"{folder.name}/{uid}_{name}"
            self._reserved.add(relative)
        (self.target_dir / relative).write_bytes(bytes(reply.content()))
        return relative

    def run(self) -> bool:
        try:
            self.target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.error = str(e)
            return False
        self._load_manifest()

        todo = []
        for r in self.resources:
            known = self._manifest.get(r.href)
            if known and (self.target_dir / known).exists():
                self.paths[r.href] = str(self.target_dir / known)
            else:
                todo.append(r)
        self._log(f"{len(self.resources)} resurser, {len(todo)} att hämta, "
                  f"{len(self.resources) - len(todo)} finns redan")

        done = len(self.resources) - len(todo)
        total = len(self.resources) or 1
        with ThreadPoolExecutor(MAX_WORKERS) as pool:
            pending = {pool.submit(self._download, r): r for r in todo}
            while pending:
                finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    r = pending.pop(future)
                    try:
                        relative = future.result()
                        with self._lock:
                            self._manifest[r.href] = relative
                        self.paths[r.href] = str(self.target_dir / relative)
                    except Exception as e:  # noqa: BLE001 — one bad file must not stop the rest
                        if not self.isCanceled():
                            self.failures.append(f"{r.title} ({r.href}): {e}")
                    done += 1
                self.setProgress(100.0 * done / total)
                if self.isCanceled():
                    for future in pending:
                        future.cancel()
        self._save_manifest()

        if self.isCanceled():
            return False
        for failure in self.failures:
            self._log(failure, Qgis.MessageLevel.Warning)
        return True

    def finished(self, result: bool) -> None:
        if result:
            self.completed.emit(self.paths, self.failures)
        elif not self.isCanceled():
            self._log(self.error or "Okänt fel", Qgis.MessageLevel.Critical)
            self.failed.emit(self.error or "Okänt fel")

    def _log(self, message: str, level=Qgis.MessageLevel.Info) -> None:
        QgsMessageLog.logMessage(message, PLUGIN_NAME, level)
