"""CachyMonitor : module widgets (voir cachymonitor.py)."""

from collections import deque
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPainterPath, QPen, QBrush, QFont, QLinearGradient
from PySide6.QtWidgets import QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QSizePolicy, QPushButton, QMessageBox
from .config import DEFAULT_FPS_TARGET, GAME_WINDOW_S, HISTORY, IS_WINDOWS
from .game import bottleneck
from .i18n import tr
from .mangohud_conf import enable_mangohud_logging, mangohud_conf_path, mangohud_hud_hidden, mangohud_logging_enabled, no_game_text, set_mangohud_hud_hidden
from .theme import col



# ----------------------------------------------------------------------------- #
#  Widgets graphiques
# ----------------------------------------------------------------------------- #

class Sparkline(QWidget):
    """Courbe d'historique remplie. max_value=None => échelle auto."""

    def __init__(self, role, max_value=100.0):
        super().__init__()
        self.role = role
        self.max_value = max_value
        self.data = deque(maxlen=HISTORY)
        self.setMinimumHeight(54)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def push(self, value):
        self.data.append(value)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        color = QColor(col(self.role))

        if not self.data:
            return
        vals = list(self.data)
        valid = [v for v in vals if v is not None]
        if not valid:
            return

        if self.max_value is not None:
            vmax = self.max_value
        else:
            vmax = max(valid) * 1.15 or 1.0

        n = len(vals)
        step = w / max(1, n - 1)

        def pt(i, v):
            return QPointF(i * step, h - (min(v, vmax) / vmax) * (h - 4) - 2)

        # On découpe en segments contigus (sauts sur les None).
        line = QPen(color, 2)
        line.setJoinStyle(Qt.RoundJoin)
        i = 0
        while i < n:
            if vals[i] is None:
                i += 1
                continue
            j = i
            seg = []
            while j < n and vals[j] is not None:
                seg.append((j, vals[j]))
                j += 1
            if len(seg) >= 1:
                path = QPainterPath()
                path.moveTo(pt(seg[0][0], seg[0][1]))
                for k, v in seg[1:]:
                    path.lineTo(pt(k, v))
                # remplissage dégradé sous la courbe
                fill = QPainterPath(path)
                fill.lineTo(QPointF(seg[-1][0] * step, h))
                fill.lineTo(QPointF(seg[0][0] * step, h))
                fill.closeSubpath()
                grad = QLinearGradient(0, 0, 0, h)
                c = QColor(color)
                c.setAlpha(90)
                grad.setColorAt(0, c)
                c2 = QColor(color)
                c2.setAlpha(0)
                grad.setColorAt(1, c2)
                p.fillPath(fill, QBrush(grad))
                p.strokePath(path, line)
            i = j


class FrametimeGraph(QWidget):
    """Graphe des frametimes (ms). Les pics = micro-saccades ressenties en jeu.

    Une ligne de repère est tracée à la cible (ex. 6,06 ms pour 165 fps) :
    tout ce qui dépasse nettement se voit immédiatement.
    """

    def __init__(self, role="ft"):
        super().__init__()
        self.role = role
        self.data = []
        self.target_ms = 1000.0 / DEFAULT_FPS_TARGET
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, values, target_ms=None):
        # On n'affiche que la fin de la session (le graphe défile).
        self.data = list(values)[-HISTORY:]
        if target_ms:
            self.target_ms = target_ms
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        color = QColor(col(self.role))
        muted = QColor(col("muted"))

        if len(self.data) < 2:
            p.setPen(muted)
            p.drawText(self.rect(), Qt.AlignCenter, tr("waiting for data…"))
            return

        # Échelle : au moins 2x la cible, sinon le pic max (avec marge).
        peak = max(self.data)
        top = max(self.target_ms * 2.0, peak * 1.15)

        def y_of(v):
            return h - (min(v, top) / top) * h

        # Ligne de repère (cible)
        ty = y_of(self.target_ms)
        pen = QPen(muted, 1, Qt.DashLine)
        p.setPen(pen)
        p.drawLine(0, int(ty), w, int(ty))
        p.setPen(muted)
        f = p.font(); f.setPointSize(8); p.setFont(f)
        p.drawText(4, max(10, int(ty) - 3), f"{self.target_ms:.1f} ms")

        # Courbe remplie
        step = w / max(1, len(self.data) - 1)
        path = QPainterPath()
        path.moveTo(0, y_of(self.data[0]))
        for i, v in enumerate(self.data[1:], start=1):
            path.lineTo(i * step, y_of(v))

        fill = QPainterPath(path)
        fill.lineTo(w, h)
        fill.lineTo(0, h)
        fill.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        c = QColor(color); c.setAlpha(110)
        grad.setColorAt(0, c)
        c2 = QColor(color); c2.setAlpha(10)
        grad.setColorAt(1, c2)
        p.fillPath(fill, QBrush(grad))

        p.setPen(QPen(color, 1.6))
        p.drawPath(path)

        # Marqueurs sur les pics importants (> 2x la cible)
        spike = self.target_ms * 2.0
        bad = QColor(col("bad"))
        p.setPen(QPen(bad, 1))
        p.setBrush(QBrush(bad))
        for i, v in enumerate(self.data):
            if v >= spike:
                p.drawEllipse(QPointF(i * step, y_of(v)), 2.2, 2.2)


class CircularGauge(QWidget):
    """Jauge circulaire : anneau de progression + valeur au centre."""

    def __init__(self, role):
        super().__init__()
        self.role = role
        self.percent = 0.0
        self.big = "—"
        self.sub = ""
        self.sub_role = "muted"
        self.setMinimumSize(150, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set(self, percent, big, sub, sub_role=None):
        self.percent = max(0.0, min(100.0, percent))
        self.big = big
        self.sub = sub
        self.sub_role = sub_role or "muted"
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        side = min(w, h)
        thick = max(8, side * 0.11)
        margin = thick / 2 + 4
        rect = QRectF(
            (w - side) / 2 + margin,
            (h - side) / 2 + margin,
            side - 2 * margin,
            side - 2 * margin,
        )

        # anneau de fond
        bg = QPen(QColor(col("ring")), thick)
        bg.setCapStyle(Qt.RoundCap)
        p.setPen(bg)
        p.drawArc(rect, 0, 360 * 16)

        # arc de progression (départ en haut, sens horaire)
        pen = QPen(QColor(col(self.role)), thick)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        span = int(-self.percent / 100.0 * 360 * 16)
        p.drawArc(rect, 90 * 16, span)

        # valeur centrale
        p.setPen(QColor(col("text")))
        f = QFont()
        f.setPointSizeF(max(14, side * 0.16))
        f.setBold(True)
        p.setFont(f)
        big_rect = QRectF(rect.x(), rect.y(), rect.width(), rect.height() * 0.70)
        p.drawText(big_rect, Qt.AlignCenter, self.big)

        # sous-texte (peut contenir plusieurs lignes via \n)
        p.setPen(QColor(col(self.sub_role)))
        sf = QFont()
        sf.setPointSizeF(max(8, side * 0.058))
        p.setFont(sf)
        sub_rect = QRectF(
            rect.x(), rect.y() + rect.height() * 0.54,
            rect.width(), rect.height() * 0.34,
        )
        p.drawText(sub_rect, Qt.AlignHCenter | Qt.AlignTop, self.sub)


class GaugeCard(QFrame):
    """Carte contenant un titre et une jauge circulaire."""

    def __init__(self, title, role):
        super().__init__()
        self.setObjectName("card")
        self.role = role
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(4)

        top = QHBoxLayout()
        self.dot = QLabel("●")
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        top.addWidget(self.dot)
        top.addWidget(self.title)
        top.addStretch()
        lay.addLayout(top)

        # Nom du matériel détecté (CPU/GPU/RAM…) sous le titre
        self.hw = QLabel("")
        self.hw.setObjectName("cardHw")
        lay.addWidget(self.hw)

        self.gauge = CircularGauge(role)
        lay.addWidget(self.gauge, 1)

        # Courbe de tendance : montre les pics des dernières minutes,
        # que la jauge instantanée ne peut pas révéler.
        self.trend = Sparkline(role, max_value=100.0)
        self.trend.setMinimumHeight(28)
        self.trend.setMaximumHeight(34)
        lay.addWidget(self.trend)

        self.retheme()

    def update_value(self, percent, big, sub, sub_role=None):
        """Met à jour la jauge ET la courbe de tendance d'un coup."""
        self.gauge.set(percent, big, sub, sub_role)
        self.trend.push(percent)

    def retheme(self):
        """Réapplique les couleurs posées en ligne (le QSS global ne les couvre pas)."""
        self.dot.setStyleSheet(f"color:{col(self.role)}; font-size:12px;")
        self.hw.setStyleSheet(f"color:{col(self.role)};")
        self.gauge.update()
        self.trend.update()


class StatBox(QVBoxLayout):
    """Petite statistique : grande valeur + libellé dessous."""

    def __init__(self, label, role="text", big=False):
        super().__init__()
        self.setSpacing(0)
        self._font_px = 34 if big else 20
        self.role = role
        self.value = QLabel("—")
        self.retheme()
        self.value.setAlignment(Qt.AlignCenter)
        self.cap = QLabel(label)
        self.cap.setObjectName("cardSub")
        self.cap.setAlignment(Qt.AlignCenter)
        self.addWidget(self.value)
        self.addWidget(self.cap)

    def set(self, text, role=None):
        self.value.setText(text)
        if role and role != self.role:
            self.role = role
            self.retheme()

    def retheme(self):
        self.value.setStyleSheet(
            f"color:{col(self.role)}; font-size:{self._font_px}px; font-weight:700;"
        )


class GamePanel(QFrame):
    """Panneau gaming : FPS, 1% low, 0.1% low, frametime et goulot d'étranglement.

    Le 1% low est ce qui se ressent vraiment en jeu : une moyenne de 120 fps
    avec un 1% low à 40 donne une expérience saccadée.
    """

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # En-tête : titre + nom du jeu détecté
        top = QHBoxLayout()
        self.dot = QLabel("●")
        self.title = QLabel(tr("IN GAME"))
        self.title.setObjectName("cardTitle")
        top.addWidget(self.dot)
        top.addWidget(self.title)
        top.addStretch()
        self.game = QLabel("")
        self.game.setObjectName("cardHw")
        top.addWidget(self.game)
        lay.addLayout(top)

        # Ligne de statistiques
        stats = QHBoxLayout()
        stats.setSpacing(6)
        self.s_fps = StatBox("FPS", "fps", big=True)
        self.s_low1 = StatBox(tr("1% LOW ({win:.0f} s)").format(win=GAME_WINDOW_S), "text")
        self.s_low01 = StatBox(tr("0.1% LOW ({win:.0f} s)").format(win=GAME_WINDOW_S), "text")
        self.s_avg = StatBox(tr("AVERAGE ({win:.0f} s)").format(win=GAME_WINDOW_S), "muted")
        self.s_ft = StatBox("FRAMETIME", "ft")
        for s in (self.s_fps, self.s_low1, self.s_low01, self.s_avg, self.s_ft):
            stats.addLayout(s)
        lay.addLayout(stats)

        # Goulot d'étranglement
        self.bottle = QLabel("")
        self.bottle.setObjectName("cardSub")
        self.bottle.setAlignment(Qt.AlignCenter)
        self.bottle_role = "muted"
        lay.addWidget(self.bottle)

        # Graphe de frametime
        self.ft_graph = FrametimeGraph()
        lay.addWidget(self.ft_graph, 1)

        self.status = QLabel(no_game_text())
        self.status.setObjectName("cardSub")
        self.status.setAlignment(Qt.AlignCenter)
        self.idle = True     # aucun jeu détecté : le statut est un texte fixe
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        # Linux : propose d'activer le logging MangoHud quand il est coupé
        self.enable_btn = QPushButton(tr("Enable MangoHud logging"))
        self.enable_btn.setObjectName("optButton")
        self.enable_btn.setCursor(Qt.PointingHandCursor)
        self.enable_btn.clicked.connect(self._enable_logging)
        lay.addWidget(self.enable_btn, 0, Qt.AlignCenter)

        # Linux : afficher/cacher le HUD MangoHud (les logs continuent)
        self.hud_btn = QPushButton()
        self.hud_btn.setObjectName("optButton")
        self.hud_btn.setCursor(Qt.PointingHandCursor)
        self.hud_btn.clicked.connect(self._toggle_hud)
        self.hud_btn.setVisible(not IS_WINDOWS)
        lay.addWidget(self.hud_btn, 0, Qt.AlignCenter)
        self._refresh_hud_btn()
        self._refresh_idle()

        self.retheme()

    def retext(self):
        """Repose les libellés fixes après un changement de langue. Le reste
        (statut, goulot, valeurs) est réécrit au prochain échantillon."""
        self.title.setText(tr("IN GAME"))
        for box, key in (
            (self.s_low1, "1% LOW ({win:.0f} s)"),
            (self.s_low01, "0.1% LOW ({win:.0f} s)"),
            (self.s_avg, "AVERAGE ({win:.0f} s)"),
        ):
            box.cap.setText(tr(key).format(win=GAME_WINDOW_S))
        self.enable_btn.setText(tr("Enable MangoHud logging"))
        self._refresh_hud_btn()
        if self.idle:
            self._refresh_idle()

    def _refresh_idle(self):
        """Texte « aucun jeu » + bouton d'aide (seulement si le logging est coupé)."""
        self.status.setText(no_game_text())
        self.enable_btn.setVisible(
            self.idle and not IS_WINDOWS and not mangohud_logging_enabled())

    def _refresh_hud_btn(self):
        self.hud_btn.setText(tr("Show MangoHud overlay") if mangohud_hud_hidden()
                             else tr("Hide MangoHud overlay"))

    def _toggle_hud(self):
        try:
            set_mangohud_hud_hidden(not mangohud_hud_hidden())
        except OSError as e:
            QMessageBox.warning(self, tr("Could not edit the MangoHud config"), str(e))
        self._refresh_hud_btn()

    def _enable_logging(self):
        path = mangohud_conf_path()
        ask = QMessageBox.question(
            self, tr("Enable MangoHud logging?"),
            tr("CachyMonitor reads FPS from MangoHud log files, which MangoHud "
               "does not write by default.\n\nThis adds autostart_log=1 to {path} "
               "(a backup is made first). Restart your game afterwards."
               ).format(path=path))
        if ask != QMessageBox.Yes:
            return
        try:
            enable_mangohud_logging()
        except OSError as e:
            QMessageBox.warning(self, tr("Could not edit the MangoHud config"), str(e))
            return
        QMessageBox.information(
            self, tr("Logging enabled"),
            tr("Done. Restart your game for MangoHud to pick it up."))
        self._refresh_idle()

    def retheme(self):
        self.dot.setStyleSheet(f"color:{col('fps')}; font-size:12px;")
        self.game.setStyleSheet(f"color:{col('fps')};")
        for s in (self.s_fps, self.s_low1, self.s_low01, self.s_avg, self.s_ft):
            s.retheme()
        self._apply_bottle()
        self.ft_graph.update()

    def _apply_bottle(self):
        self.bottle.setStyleSheet(
            f"color:{col(self.bottle_role)}; font-size:12px; font-weight:600;"
        )

    def _fps_role(self, v, target):
        if v is None:
            return "muted"
        if v >= target * 0.85:
            return "ok"
        if v >= target * 0.5:
            return "warn"
        return "bad"

    def clear(self):
        for s in (self.s_fps, self.s_low1, self.s_low01, self.s_avg, self.s_ft):
            s.value.setText("—")
        self.game.setText("")
        self.bottle.setText("")
        self.ft_graph.set_data([])
        self.idle = True
        self._refresh_idle()

    def update_game(self, g, target):
        self.idle = False
        self.enable_btn.hide()
        self.game.setText(g["name"])

        if g["live"] and g["fps"] is not None:
            self.s_fps.set(f"{g['fps']:.0f}", self._fps_role(g["fps"], target))
        else:
            self.s_fps.set("—", "muted")

        self.s_low1.set(f"{g['low1']:.0f}", self._fps_role(g["low1"], target))
        self.s_low01.set(f"{g['low01']:.0f}", self._fps_role(g["low01"], target))
        self.s_avg.set(f"{g['avg']:.0f}")

        ft = g["frametime"]
        self.s_ft.set(f"{ft:.1f} ms" if ft else "—")

        txt, role = bottleneck(g["cpu_load"], g["gpu_load"])
        self.bottle.setText(txt or "")
        if txt:
            self.bottle_role = role
            self._apply_bottle()

        self.ft_graph.set_data(g["ft_history"], target_ms=1000.0 / target)

        state = tr("Session running") if g["live"] else tr("Last session (ended)")
        self.status.setText(
            tr("{state} · {mins:.1f} min played · lows over the last {win:.0f} s "
               "· session range {low:.0f}–{high:.0f} fps").format(
                state=state, mins=g["duration_s"] / 60, win=g["window_s"],
                low=g["min"], high=g["max"],
            )
            + (" · " + tr("source: {src}").format(src=g["source"])
               if g.get("source") else "")
        )


def battery_role(pct):
    """Couleur du niveau de batterie : vert, orange sous 50 %, rouge sous 20 %."""
    if pct is None:
        return "muted"
    if pct > 50:
        return "ok"
    if pct > 20:
        return "warn"
    return "bad"


class BatteryBar(QWidget):
    """Petite pile horizontale remplie au niveau de charge."""

    def __init__(self):
        super().__init__()
        self.pct = None
        self.setFixedSize(34, 15)

    def set(self, pct):
        self.pct = pct
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        body = QRectF(0.5, 0.5, self.width() - 4.5, self.height() - 1)
        p.setPen(QPen(QColor(col("muted")), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(body, 3, 3)
        # le téton de la pile
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(col("muted")))
        p.drawRoundedRect(QRectF(body.right() + 0.5, body.height() * 0.3,
                                 3, body.height() * 0.45), 1, 1)
        if self.pct is not None:
            inner = body.adjusted(2, 2, -2, -2)
            inner.setWidth(inner.width() * max(0, min(self.pct, 100)) / 100)
            p.setBrush(QColor(col(battery_role(self.pct))))
            p.drawRoundedRect(inner, 1.5, 1.5)


class ControllerRow(QHBoxLayout):
    """Une manette : nom, type de connexion, pile et pourcentage."""

    def __init__(self):
        super().__init__()
        self.setSpacing(8)
        self.name = QLabel("")
        self.name.setObjectName("cardHw")
        self.link = QLabel("")
        self.link.setObjectName("cardSub")
        self.bar = BatteryBar()
        self.pct = QLabel("")
        self.pct.setMinimumWidth(44)
        self.pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.addWidget(self.name)
        self.addWidget(self.link)
        self.addStretch()
        self.addWidget(self.bar)
        self.addWidget(self.pct)
        self.role = "muted"
        self.retheme()

    def widgets(self):
        return (self.name, self.link, self.bar, self.pct)

    def set(self, c):
        self.name.setText(c["name"])
        self.link.setText(
            {"usb": tr("Wired (USB)"), "bluetooth": "Bluetooth"}.get(c["bus"], "")
        )

        pct = c["battery"]
        self.bar.set(pct)
        if pct is not None:
            # L'éclair signale la charge en cours (manette branchée en USB).
            self.pct.setText(f"{'⚡' if c['status'] == 'charging' else ''}{pct}%")
        else:
            # Manette filaire sans batterie, ou pilote qui ne la publie pas.
            self.pct.setText("—")
        # Les couleurs ne sont reposées que si le niveau change de catégorie.
        role = battery_role(pct)
        if role != self.role:
            self.role = role
            self.retheme()

    def retheme(self):
        self.name.setStyleSheet(f"color:{col('text')};")
        self.pct.setStyleSheet(
            f"color:{col(self.role)}; font-size:15px; font-weight:700;"
        )
        self.bar.update()


class ControllerPanel(QFrame):
    """Manettes connectées : modèle, câble ou Bluetooth, niveau de batterie."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        self.dot = QLabel("●")
        self.title = QLabel(tr("CONTROLLER"))
        self.title.setObjectName("cardTitle")
        top.addWidget(self.dot)
        top.addWidget(self.title)
        top.addStretch()
        lay.addLayout(top)

        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(6)
        lay.addLayout(self.rows_box)
        self.rows = []

        self.empty = QLabel(tr("No controller detected"))
        self.empty.setObjectName("cardSub")
        lay.addWidget(self.empty)

        self.retheme()

    def update_controllers(self, controllers):
        # Une ligne par manette. Les lignes en trop (manette déconnectée) sont
        # masquées plutôt que détruites, et resserviront à la prochaine.
        while len(self.rows) < len(controllers):
            row = ControllerRow()
            self.rows_box.addLayout(row)
            self.rows.append(row)
        for i, row in enumerate(self.rows):
            shown = i < len(controllers)
            for w in row.widgets():
                w.setVisible(shown)
            if shown:
                row.set(controllers[i])
        self.empty.setVisible(not controllers)

    def retext(self):
        self.title.setText(tr("CONTROLLER"))
        self.empty.setText(tr("No controller detected"))

    def retheme(self):
        self.dot.setStyleSheet(f"color:{col('cpu')}; font-size:12px;")
        for row in self.rows:
            row.retheme()
