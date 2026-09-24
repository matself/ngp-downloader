"""Dialog: choose which resources (by role) to download for a layer."""

from __future__ import annotations

from qgis.core import QgsFeatureRequest, QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QVBoxLayout,
)

from ..core.resources import summarize


def _size(n: int) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class ResourceDialog(QDialog):
    def __init__(self, layer: QgsVectorLayer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hämta resurser")
        self.setMinimumWidth(460)
        self.layer = layer

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Lager: <b>{layer.name()}</b>"))

        selected = layer.selectedFeatureCount()
        self.selected_radio = QRadioButton(f"Endast valda objekt ({selected})")
        self.all_radio = QRadioButton(f"Alla objekt ({layer.featureCount()})")
        self.selected_radio.setEnabled(selected > 0)
        (self.selected_radio if selected else self.all_radio).setChecked(True)
        self.selected_radio.toggled.connect(self._refresh)
        layout.addWidget(self.selected_radio)
        layout.addWidget(self.all_radio)

        layout.addWidget(QLabel("Hämta:"))
        self.role_list = QListWidget()
        self.role_list.itemChanged.connect(self._update_ok)
        layout.addWidget(self.role_list)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Hämta")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._refresh()

    def feature_ids(self) -> list[int] | None:
        """Selected feature ids, or None for all features."""
        return list(self.layer.selectedFeatureIds()) if self.selected_radio.isChecked() else None

    def roles(self) -> list[str]:
        return [
            self.role_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.role_list.count())
            if self.role_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _assets_values(self):
        request = QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry)
        request.setSubsetOfAttributes(["assets"], self.layer.fields())
        ids = self.feature_ids()
        if ids is not None:
            request.setFilterFids(ids)
        return (f["assets"] for f in self.layer.getFeatures(request))

    def _refresh(self) -> None:
        checked = set(self.roles())
        summaries, links = summarize(self._assets_values())

        self.role_list.blockSignals(True)
        self.role_list.clear()
        for s in sorted(summaries, key=lambda s: -s.files):
            size = _size(s.known_bytes) if s.known_bytes else "okänd storlek"
            if s.known_bytes and s.unknown_size:
                size = f"minst {size}"
            item = QListWidgetItem(f"{s.title} ({s.role}) – {s.files} filer, {size}")
            item.setData(Qt.ItemDataRole.UserRole, s.role)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if s.role in checked else Qt.CheckState.Unchecked)
            self.role_list.addItem(item)
        self.role_list.blockSignals(False)

        info = []
        if not summaries:
            info.append("Objekten har inga resurser att hämta via NGP.")
        if links:
            names = ", ".join(sorted(links))
            info.append(f"Länkar till andra webbplatser hämtas inte ({names}); de finns kvar i kolumnen assets.")
        info.append("Varje fil hämtas en gång även om flera objekt pekar på den. "
                    "Redan hämtade filer hoppas över.")
        self.info_label.setText("\n\n".join(info))
        self._update_ok()

    def _update_ok(self) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.roles()))
