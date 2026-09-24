"""Riksantikvarieämbetet's lämningsregister as a download source.

RAÄ publishes the full register as open data, updated nightly, as one
GeoPackage per kommun, per län and for all of Sweden. Unlike NGP's reference
objects it has every attribute (socken, RAÄ-nummer, beskrivning, …) and a
layer with lägesosäkerhet. No login needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from osgeo import ogr
from qgis.core import QgsBlockingNetworkRequest, QgsFileDownloader
from qgis.PyQt.QtCore import QObject, QUrl, pyqtSignal
from qgis.PyQt import sip
from qgis.PyQt.QtNetwork import QNetworkRequest

BASE_URL = "https://pub.raa.se/nedladdning/datauttag/lamningar_v1/"
# Apache directory index row: link, date, size.
_ROW = re.compile(
    r'<a href="([^"?/][^"]*\.gpkg)">[^<]*</a></td><td align="right">([^<]*)</td><td align="right">\s*([^<]*)'
)
# Layer name ending -> our layer suffix, listed bottom to top.
LAYER_SUFFIXES = {
    "_lägesosäkerhet": "lagesosakerhet",
    "_polygon": "yta",
    "_linestring": "linje",
    "_point": "punkt",
}
HIDDEN_SUFFIXES = {"lagesosakerhet"}  # off by default, as in Fornsök


@dataclass(frozen=True)
class RaaFile:
    level: str  # "kommun", "län" or "sverige"
    name: str  # e.g. "Kristianstad"
    url: str
    size: str  # as listed, e.g. "22M"
    updated: str

    @property
    def filename(self) -> str:
        return unquote(self.url.rsplit("/", 1)[-1])


def _title(filename: str, prefix: str) -> str:
    stem = filename[len(prefix):-len(".gpkg")]
    return " ".join(w[:1].upper() + w[1:] for w in stem.split("_"))


def _index(url: str) -> list[tuple[str, str, str]]:
    blocking = QgsBlockingNetworkRequest()
    error = blocking.get(QNetworkRequest(QUrl(url)), True)
    if error != QgsBlockingNetworkRequest.ErrorCode.NoError:
        raise RuntimeError(f"Kunde inte läsa {url}: {blocking.errorMessage()}")
    html = bytes(blocking.reply().content()).decode("utf-8", "replace")
    return [(href, date.strip(), size.strip()) for href, date, size in _ROW.findall(html)]


def list_files() -> list[RaaFile]:
    """All downloadable files: Sweden first, then län and kommuner by name."""
    files = []
    for href, date, size in _index(BASE_URL):
        files.append(RaaFile("sverige", "Hela Sverige", BASE_URL + href, size, date))
    for level, folder, prefix in (("län", "lan/", "lämningar_län_"), ("kommun", "kommun/", "lämningar_kommun_")):
        for href, date, size in _index(BASE_URL + folder):
            name = _title(unquote(href), prefix)
            files.append(RaaFile(level, name, BASE_URL + folder + href, size, date))
    order = {"sverige": 0, "län": 1, "kommun": 2}
    return sorted(files, key=lambda f: (order[f.level], f.name.lower()))


def layers_in(gpkg: Path) -> list[tuple[str, str]]:
    """(layer name, suffix) of the map layers in a RAÄ GeoPackage, bottom to top.

    Skips the attribute tables and the bare geometry layers (only uuid).
    """
    ds = ogr.Open(str(gpkg))
    names = [ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())]
    ds = None
    found = []
    for ending, suffix in LAYER_SUFFIXES.items():
        found += [(n, suffix) for n in names if n.startswith("lämningar_") and n.endswith(ending)]
    return found


class RaaDownload(QObject):
    """Downloads RAÄ files one after another with QGIS' file downloader.

    Streams to disk (the Sweden file is 2 GB) and honours QGIS' proxy settings.
    """

    progress = pyqtSignal(str)
    completed = pyqtSignal(list)  # [(RaaFile, Path)]
    failed = pyqtSignal(str)

    def __init__(self, files: list[RaaFile], output_dir: Path, stamp: str, parent=None):
        super().__init__(parent)
        self.queue = list(files)
        self.output_dir = output_dir
        self.stamp = stamp
        self.done: list[tuple[RaaFile, Path]] = []
        self._downloader: QgsFileDownloader | None = None
        self._current: tuple[RaaFile, Path] | None = None
        self._error: str | None = None
        self._canceled = False

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._next()

    def cancel(self) -> None:
        self._canceled = True
        if self._downloader:
            self._downloader.cancelDownload()

    def _next(self) -> None:
        if not self.queue:
            self.completed.emit(self.done)
            return
        f = self.queue.pop(0)
        # Time-stamped name: the file changes nightly, and a loaded file must not be overwritten.
        path = self.output_dir / f"{Path(f.filename).stem}_{self.stamp}.gpkg"
        self._current, self._error = (f, path), None
        self._downloader = QgsFileDownloader(QUrl(f.url), str(path))
        # The downloader deletes itself (deleteLater) when done; let C++ own it so
        # Python does not delete it a second time when the reference is dropped.
        sip.transferto(self._downloader, None)
        self._downloader.downloadProgress.connect(self._on_progress)
        self._downloader.downloadError.connect(self._on_error)
        self._downloader.downloadExited.connect(self._on_exited)

    def _on_progress(self, received: int, total: int) -> None:
        f = self._current[0]
        size = f"{received / 1e6:.0f} av {total / 1e6:.0f} MB" if total > 0 else f"{received / 1e6:.0f} MB"
        self.progress.emit(f"Hämtar {f.name} ({f.level}): {size}")

    def _on_error(self, errors: list) -> None:
        self._error = "; ".join(errors)

    def _on_exited(self) -> None:
        self._downloader = None
        if self._canceled:
            self.failed.emit("Hämtningen avbröts.")
        elif self._error:
            self.failed.emit(f"{self._current[0].name}: {self._error}")
        else:
            self.done.append(self._current)
            self._next()
