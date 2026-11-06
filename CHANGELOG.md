# Changelog / Versionen

Version number in `ftg.pyw` (`VERSION`), shown in the settings dialog, briefly at start-up and
in `ftg.log`. / Die Versionsnummer steht in `ftg.pyw` (`VERSION`), im Einstellungsfenster,
kurz beim Start und im `ftg.log`.

## 1.12.2 – 2026-11-06 – screenshot, colour swap, shortcut check / Screenshot, Farbtausch, Verknüpfungen
- EN: Context menu “Screenshot to clipboard” copies the window as it appears on screen, with a
  Windows notification. Settings: button ⇄ swaps the colours of In and Out. When the configuration
  folder changes, FTG finds autostart and desktop shortcuts that still point to the old folder and
  offers to update them; “Check shortcuts” in the shortcut menu does the same at any time.
- DE: Kontextmenü „Screenshot in die Zwischenablage“ kopiert das Fenster so, wie es auf dem Bildschirm
  aussieht, mit Windows-Benachrichtigung. Einstellungen: Knopf ⇄ tauscht die Farben von In und Out.
  Beim Wechsel des Konfigurationsordners findet FTG Autostart- und Desktop-Verknüpfungen, die noch auf
  den alten Ordner zeigen, und bietet das Umstellen an; „Verknüpfungen prüfen“ im Verknüpfungsmenü
  macht das jederzeit.

## 1.11.0 – 2026-11-05 – backup copies / Sicherungskopien
- EN: “Save configuration” is gone (settings are saved automatically anyway). New in the context menu:
  “Save backup copy” puts a copy into the subfolder `Backup` of the configuration folder,
  “Restore backup copy” lists the copies of this window (newest first) and restores one, including
  position and size; the current state is backed up first. Changing the configuration folder is logged.
- DE: „Konfiguration speichern“ entfällt (gespeichert wird ohnehin automatisch). Neu im Kontextmenü:
  „Sicherungskopie speichern“ legt eine Kopie im Unterordner `Backup` des Konfigurationsordners ab,
  „Sicherungskopie wiederherstellen“ listet die Kopien dieses Fensters (neueste zuerst) und stellt eine
  wieder her, samt Position und Größe; der jetzige Stand wird vorher gesichert. Ein Wechsel des
  Konfigurationsordners steht im Log.

## 1.10.0 – 2026-11-04 – English user interface / englische Oberfläche
- EN: The user interface is now available in English and German. The language follows Windows
  (German → German, any other language → English) and can be set in the settings
  (Automatic / Deutsch / English). Numbers use a decimal point in English.
- DE: Die Oberfläche gibt es jetzt auf Englisch und Deutsch. Die Sprache richtet sich nach Windows
  (Deutsch → deutsch, jede andere Sprache → englisch) und lässt sich in den Einstellungen festlegen
  (Automatisch / Deutsch / English).

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
