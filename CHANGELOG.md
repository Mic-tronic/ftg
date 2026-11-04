# Changelog / Versionen

Version number in `ftg.pyw` (`VERSION`), shown in the settings dialog, briefly at start-up and
in `ftg.log`. / Die Versionsnummer steht in `ftg.pyw` (`VERSION`), im Einstellungsfenster,
kurz beim Start und im `ftg.log`.

## 1.9.0 – 2026-11-04 – first public release / erste öffentliche Version
- EN: Label for sums of interfaces is now `Name · [7]`. The settings dialog loads the interface
  list automatically for existing configurations. Header comment updated, legacy migration removed.
  The project is now called *Flexible Traffic Grapher*.
- DE: Beschriftung bei Summen jetzt `Name · [7]`. Die Einstellungen laden bei bestehender
  Konfiguration die Interface-Liste automatisch. Kopfkommentar aktualisiert, alte Übernahme entfernt.
  Das Projekt heißt jetzt *Flexible Traffic Grapher*.

## 1.8.1 – 2026-11-02
- EN: Diagnostics: polling errors and the first measurements per interface (sum mode) go to `ftg.log`.
- DE: Diagnose: Abfragefehler und im Summen-Modus die ersten Messungen je Interface stehen im `ftg.log`.

## 1.8.0 – 2026-11-02
- EN: Sum of several interfaces (checkbox list with all/none, one SNMP request per cycle,
  wrap/reset handled per interface). Version shown at start-up.
- DE: Summe mehrerer Interfaces (Ankreuzliste mit alle/keine, eine SNMP-Anfrage pro Takt,
  Überlauf/Reset je Interface). Versionsnummer beim Start.

## 1.7.x – 2026-11-02
- EN: SNMPv3 (USM per RFC 3414/3826/7860, AES-128 in pure Python, engine discovery and time
  sync, clear error messages); passwords protected with Windows DPAPI. Mouse side buttons fixed.
- DE: SNMPv3 (USM nach RFC 3414/3826/7860, AES-128 in reinem Python, Engine-Erkennung und
  Zeitabgleich, verständliche Fehlermeldungen); Passwörter per Windows-DPAPI geschützt.
  Maus-Seitentasten repariert.

## 1.6.x – 2026-11-02
- EN: Version number; arrange windows in four directions; windows always kept on screen;
  clearer context menu; wheel-tilt throttling; more mouse side-button variants.
- DE: Versionsnummer; Fenster anordnen in vier Richtungen; Fenster bleiben immer auf dem
  Bildschirm; eindeutigeres Kontextmenü; Kippen des Mausrads gebremst; weitere Seitentasten-Varianten.

## 1.5.0 – 2026-11-02
- EN: Mouse side buttons for the time range, size indicator while resizing, arrange windows,
  copy window size, own program icon; loading a configuration also restores its position.
- DE: Maus-Seitentasten für den Zeitraum, Größenanzeige beim Ändern, Fenster anordnen,
  Fenstergröße übertragen, eigenes Programmsymbol; „Konfiguration laden“ übernimmt die Position.

## 1.4.0 – 2026-10-30
- EN: Background opacity (curves stay opaque), move borderless windows with Ctrl+drag,
  wheel scrolls back in time, Shift+wheel zooms.
- DE: Hintergrund-Deckkraft (Kurven bleiben voll), rahmenlose Fenster mit Strg+Ziehen
  verschieben, Mausrad blättert, Shift+Mausrad zoomt.

## 1.3.x – 2026-10-30
- EN: 60 minutes of history, zoom and scroll back, Ø/max for the visible range, selectable fill,
  window opacity; tray mode fix.
- DE: 60 Minuten Verlauf, Zoomen und Zurückblättern, Ø/max für den Ausschnitt, Füllung wählbar,
  Deckkraft; Korrektur im Tray-Modus.

## 1.2.0 – 2026-10-28
- EN: Polling on the system clock (all windows in sync); pause keeps measuring and redraws.
- DE: Abfrage im Takt der Systemuhr (alle Fenster synchron); Pause misst weiter und zeichnet nach.

## 1.1.0 – 2026-10-28
- EN: Tray mode with a mini live graph.
- DE: Tray-Modus mit Mini-Live-Graph.

## 1.0.0 – 2026-10-28
- EN: First version: SNMP v2c, live graph, configurations, lock file, shortcuts, dark design.
- DE: Erste Version: SNMP v2c, Live-Graph, Konfigurationen, Sperrdatei, Verknüpfungen, dunkles Design.
