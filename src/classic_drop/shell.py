"""Native window toolbar, source-list navigation and workspace surfaces."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from classic_drop.i18n import tr
from classic_drop.presentation import button, tool


class WorkspaceShell(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setAutoFillBackground(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar_panel = QWidget()
        self.sidebar_panel.setAutoFillBackground(True)
        self.sidebar_panel.setBackgroundRole(QPalette.ColorRole.AlternateBase)
        self.sidebar_panel.setMinimumWidth(190)
        self.sidebar_panel.setMaximumWidth(240)
        sidebar_layout = QVBoxLayout(self.sidebar_panel)
        sidebar_layout.setContentsMargins(12, 16, 12, 14)
        self.workspace_label = QLabel()
        self.workspace_label.setObjectName("muted")
        sidebar_layout.addWidget(self.workspace_label)
        self.sidebar = QListWidget()
        self.sidebar.setAccessibleName(tr("Workspaces"))
        self.sidebar.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar.setStyleSheet(
            "QListWidget { background: palette(alternate-base); }"
        )
        self.sidebar.setSpacing(3)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sidebar.addItems(["iPod Library", "To Import", "Recovery & History"])
        sidebar_layout.addWidget(self.sidebar, 1)
        self.device_label = QLabel()
        self.device_label.setObjectName("muted")
        sidebar_layout.addWidget(self.device_label)
        self.device_layout = QVBoxLayout()
        self.device_layout.setSpacing(8)
        sidebar_layout.addLayout(self.device_layout)
        layout.addWidget(self.sidebar_panel)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(separator)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(10)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.pages = QStackedWidget()
        self.pages.setMinimumWidth(320)
        self.splitter.addWidget(self.pages)
        self.inspectors = QStackedWidget()
        self.inspectors.setMinimumWidth(280)
        self.inspectors.setMaximumWidth(320)
        self.splitter.addWidget(self.inspectors)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setSizes([640, 300])
        content_layout.addWidget(self.splitter, 1)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        content_layout.addWidget(self.progress)
        footer = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(80)
        footer.addWidget(self.status, 1)
        self.cancel_button = button("Cancel", "x")
        footer.addWidget(self.cancel_button)
        self.import_button = button("Import selected", "music")
        self.import_button.setObjectName("primary")
        self.import_button.setDefault(True)
        footer.addWidget(self.import_button)
        content_layout.addLayout(footer)
        layout.addWidget(content, 1)

        self.toolbar = QToolBar()
        self.toolbar.setObjectName("workspaceToolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.title = QLabel()
        font = QFont()
        font.setPointSize(17)
        font.setWeight(QFont.Weight.DemiBold)
        self.title.setFont(font)
        self.title.setContentsMargins(12, 0, 12, 0)
        self.toolbar.addWidget(self.title)
        stretch = QWidget()
        stretch.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.toolbar.addWidget(stretch)
        self.inspector_button = tool("Toggle inspector", "list")
        self.inspector_button.setCheckable(True)
        self.inspector_button.setChecked(True)

        self.recovery_page = QWidget()
        recovery_layout = QVBoxLayout(self.recovery_page)
        recovery_layout.setContentsMargins(20, 24, 20, 24)
        self.recovery_title = QLabel()
        self.recovery_title.setWordWrap(True)
        self.recovery_title.setFont(font)
        recovery_layout.addWidget(self.recovery_title)
        self.recovery_detail = QLabel()
        self.recovery_detail.setWordWrap(True)
        self.recovery_detail.setObjectName("muted")
        recovery_layout.addWidget(self.recovery_detail)
        recovery_actions = QHBoxLayout()
        self.restore_button = button("Restore last import", "skip-back")
        recovery_actions.addWidget(self.restore_button)
        self.logs_button = button("Show backups and logs", "folder")
        recovery_actions.addWidget(self.logs_button)
        recovery_actions.addStretch()
        recovery_layout.addLayout(recovery_actions)
        recovery_layout.addStretch()
        self.retranslate()

    def retranslate(self) -> None:
        self.workspace_label.setText(tr("Workspaces"))
        self.sidebar.setAccessibleName(tr("Workspaces"))
        self.device_label.setText(tr("Current iPod"))
        for row, source in enumerate(
            ("iPod Library", "To Import", "Recovery & History")
        ):
            item = self.sidebar.item(row)
            item.setText(tr(source))
            item.setSizeHint(QSize(180, 36))
        self.logs_button.setText(tr("Show backups and logs"))
        self.inspector_button.setToolTip(tr("Toggle inspector"))
        self.inspector_button.setAccessibleName(tr("Toggle inspector"))

    def update_recovery(self, available: bool) -> None:
        self.recovery_title.setText(
            tr("Last import can be restored")
            if available
            else tr("No recovery available")
        )
        self.recovery_detail.setText(
            tr("Restore the selected iPod to its state before the last import.")
            if available
            else tr("Connect an iPod with a recoverable import to restore its Library.")
        )
