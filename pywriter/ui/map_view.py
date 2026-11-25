"""Relationship map: every entry as a node, every connection as a line.
Drag nodes to arrange them (positions are saved with the project), hover for a
summary, double-click to open. Location containment is drawn as dashed lines."""
from __future__ import annotations

import json
import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QGraphicsItem, QGraphicsObject, QGraphicsPathItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..store import KINDS
from ..summary import tooltip_html
from .common import KIND_COLORS


class Node(QGraphicsObject):
    def __init__(self, view: "MapView", eid: str, label: str, kind: str, tier: str):
        super().__init__()
        self.view = view
        self.eid = eid
        self.label = label
        self.kind = kind
        self.edges: list[Edge] = []
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(Qt.OpenHandCursor)
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        f = QFont()
        f.setPointSizeF(10 if tier != "primary" else 11.5)
        f.setBold(tier == "primary")
        self.font = f
        from PySide6.QtGui import QFontMetricsF
        fm = QFontMetricsF(f)
        self.w = fm.horizontalAdvance(label) + 24
        self.h = fm.height() + 12

    def boundingRect(self) -> QRectF:
        return QRectF(-self.w / 2 - 2, -self.h / 2 - 2, self.w + 4, self.h + 4)

    def paint(self, p: QPainter, opt, widget=None):
        color = QColor(KIND_COLORS.get(self.kind, "#777"))
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(color.darker(130), 2 if self.isSelected() else 1))
        p.setBrush(QBrush(color.lighter(165)))
        r = QRectF(-self.w / 2, -self.h / 2, self.w, self.h)
        radius = self.h / 2 if self.kind == "character" else 5
        p.drawRoundedRect(r, radius, radius)
        p.setFont(self.font)
        p.setPen(QColor("#1d1d1d"))
        p.drawText(r, Qt.AlignCenter, self.label)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for e in self.edges:
                e.adjust()
        return super().itemChange(change, value)

    def hoverEnterEvent(self, e):
        self.setToolTip(tooltip_html(self.view.ctx.store, self.eid))
        super().hoverEnterEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.view.save_positions()

    def mouseDoubleClickEvent(self, e):
        self.view.ctx.bus.open_entity.emit(self.eid)


class Edge(QGraphicsPathItem):
    def __init__(self, a: Node, b: Node, label: str, dashed: bool = False):
        super().__init__()
        self.a, self.b = a, b
        a.edges.append(self)
        b.edges.append(self)
        pen = QPen(QColor(120, 120, 120, 170), 1.3)
        if dashed:
            pen.setStyle(Qt.DashLine)
        self.setPen(pen)
        self.setZValue(0)
        self.text = QGraphicsSimpleTextItem(label)
        f = QFont()
        f.setPointSizeF(8)
        self.text.setFont(f)
        self.text.setBrush(QColor(110, 110, 110))
        self.text.setZValue(1)
        self.adjust()

    def adjust(self):
        p1, p2 = self.a.pos(), self.b.pos()
        path = QPainterPath(p1)
        path.lineTo(p2)
        self.setPath(path)
        mid = (p1 + p2) / 2
        self.text.setPos(mid.x() - self.text.boundingRect().width() / 2, mid.y() - 14)


class MapView(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.nodes: dict[str, Node] = {}
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        h = QLabel("Map")
        h.setObjectName("h1")
        top.addWidget(h)
        top.addStretch(1)
        lay.addLayout(top)
        top = QGridLayout()  # filter checkboxes wrap onto two rows so the map fits small screens
        self.filters: dict[str, QCheckBox] = {}
        for i, kind in enumerate(("character", "location", "group", "item", "event", "plot", "theme", "topic",
                                  "source")):
            cb = QCheckBox(KINDS[kind][2])
            cb.setChecked(kind in ("character", "location", "group", "item"))
            cb.setStyleSheet(f"color: {KIND_COLORS[kind]}")
            cb.toggled.connect(self.rebuild)
            self.filters[kind] = cb
            top.addWidget(cb, i // 5, i % 5)
        top.setColumnStretch(5, 1)
        lay.addLayout(top)
        btns = QHBoxLayout()
        auto = QPushButton("Auto-arrange")
        auto.clicked.connect(lambda: self.rebuild(force_layout=True))
        btns.addWidget(auto)
        fit = QPushButton("Fit to window")
        fit.clicked.connect(self.fit)
        btns.addWidget(fit)
        self.show_labels = QCheckBox("Show relation labels")
        self.show_labels.setChecked(True)
        self.show_labels.toggled.connect(self.rebuild)
        btns.addWidget(self.show_labels)
        hint = QLabel("Drag to arrange · scroll to zoom · hover for summary · double-click to open")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        btns.addWidget(hint, 1)
        lay.addLayout(btns)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.wheelEvent = self._wheel
        lay.addWidget(self.view, 1)
        self._dirty = True
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.rebuild)
        ctx.bus.entity_changed.connect(self._mark)
        ctx.bus.links_changed.connect(self._mark)
        ctx.bus.reloaded.connect(self._mark)

    def _mark(self, *_):
        self._dirty = True
        if self.isVisible():
            self._timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        if self._dirty:
            self.rebuild()
            QTimer.singleShot(50, self.fit)

    def _wheel(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.view.scale(f, f)

    def fit(self):
        r = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if not r.isEmpty():
            self.view.fitInView(r, Qt.KeepAspectRatio)

    def _positions(self) -> dict:
        try:
            return json.loads(self.ctx.store.meta("map_positions") or "{}")
        except ValueError:
            return {}

    def save_positions(self) -> None:
        pos = self._positions()
        for eid, n in self.nodes.items():
            pos[eid] = [round(n.pos().x(), 1), round(n.pos().y(), 1)]
        self.ctx.store.set_meta("map_positions", json.dumps(pos), log=False)

    def rebuild(self, *_, force_layout: bool = False) -> None:
        if not self.ctx.store:
            return
        self._dirty = False
        self.scene.clear()
        self.nodes.clear()
        kinds = {k for k, cb in self.filters.items() if cb.isChecked()}
        ents = [e for e in self.ctx.store.entities() if e.kind in kinds]
        saved = {} if force_layout else self._positions()
        for e in ents:
            n = Node(self, e.id, e.label, e.kind, e.tier)
            self.scene.addItem(n)
            self.nodes[e.id] = n
        edges = []
        for l in self.ctx.store.all_links():
            if l.src in self.nodes and l.dst in self.nodes:
                edges.append((l.src, l.dst, l.relation, False))
        for e in ents:
            if e.kind == "location" and e.parent_id in self.nodes:
                edges.append((e.id, e.parent_id, "in", True))
        need = [eid for eid in self.nodes if eid not in saved]
        if need:
            layout = self._layout(list(self.nodes), [(a, b) for a, b, _, _ in edges])
            for eid in need:
                saved[eid] = layout[eid]
        for eid, n in self.nodes.items():
            x, y = saved[eid]
            n.setPos(QPointF(x, y))
        for a, b, rel, dashed in edges:
            ed = Edge(self.nodes[a], self.nodes[b], rel if self.show_labels.isChecked() else "", dashed)
            self.scene.addItem(ed)
            self.scene.addItem(ed.text)
        if force_layout or need:
            self.save_positions()
        if force_layout:
            QTimer.singleShot(0, self.fit)

    @staticmethod
    def _layout(ids: list[str], edges: list[tuple[str, str]]) -> dict:
        n = max(1, len(ids))
        scale = 120 * math.sqrt(n)
        try:
            import networkx as nx
            g = nx.Graph()
            g.add_nodes_from(ids)
            g.add_edges_from(edges)
            pos = nx.spring_layout(g, k=2.2 / math.sqrt(n), seed=7, iterations=120)
            return {k: [float(v[0]) * scale, float(v[1]) * scale] for k, v in pos.items()}
        except Exception:
            rnd = random.Random(7)
            return {k: [math.cos(2 * math.pi * i / n) * scale + rnd.uniform(-10, 10),
                        math.sin(2 * math.pi * i / n) * scale + rnd.uniform(-10, 10)]
                    for i, k in enumerate(ids)}
