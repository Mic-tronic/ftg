#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
FTG - Flexible Traffic Grapher (Version siehe VERSION, Aenderungen: CHANGELOG.md).

Schlanker SNMP-Live-Traffic-Graph mit dunklem Design, inspiriert vom alten
Windows-Tool STG (SNMP Traffic Grapher): ein Fenster pro Interface oder pro
Summe mehrerer Interfaces, Live-Graph fuer ein- und ausgehenden Verkehr.

* eine Datei, nur Python-Standardbibliothek mit tkinter (Python 3.11 oder neuer;
  entwickelt mit Python 3.14 / Tk 9 unter Windows 11, laeuft eingeschraenkt auch unter Linux)
* SNMP v2c und v3 (USM: MD5, SHA, SHA-224/256/384/512; AES-128), 64-Bit-Zaehler
  (ifHCIn/OutOctets) mit Fallback auf 32 Bit
* mehrere Fenster parallel, je eine Konfigurationsdatei:
      pythonw ftg.pyw wan
      pythonw ftg.pyw "C:\Pfad\zu\lan.json"
* Konfigurationen unter %APPDATA%\FTG\ oder in einem frei waehlbaren Ordner
  (z. B. Netzlaufwerk); SNMPv3-Passwoerter per Windows-DPAPI geschuetzt
* Oberflaeche deutsch oder englisch: automatisch nach der Windows-Sprache (Deutsch ->
  deutsch, sonst englisch), umschaltbar in den Einstellungen (Feld "Sprache")

Bedienung: Doppelklick in den Graphen = Einstellungen, Rechtsklick = Menue.
Mausrad oder Pfeiltasten = zurueckblaettern (Anzeige haelt an, gemessen wird
weiter), Ende-Taste = jetzt; Shift+Mausrad, Mausrad kippen, Maus-Seitentasten
oder +/- = Zeitraum (1 ... 60 min). Ohne Titelleiste: verschieben mit Strg +
linke Maustaste, Groesse am Griff unten rechts. Es werden immer die letzten
60 Minuten im Speicher gehalten; Ø und max gelten fuer den sichtbaren Ausschnitt.

Tray-Modus (Windows): Rechtsklick → "Nur im Infobereich (Tray)". Das Fenster
verschwindet aus Taskleiste und Alt+Tab, im Infobereich laeuft ein Mini-Graph.
Linksklick aufs Symbol = Fenster ein-/ausblenden, Rechtsklick = Menue,
das X schickt das Fenster in den Infobereich, "Beenden" beendet wirklich.
"""

import ctypes
import json
import math
import os
import queue
import random
import socket
import sys
import threading
import time
from collections import deque
import tkinter as tk
from tkinter import ttk, filedialog

APP = "FTG"
VERSION = "1.11.0"         # Aenderungen: CHANGELOG.md
APP_LONG = "FTG – Flexible Traffic Grapher"
LOGNAME = "ftg.log"

# ---------------------------------------------------------------- Farben
BG = "#16181d"
PANEL = "#1e2128"
FIELD = "#262a33"
GRID = "#2a2f38"
GRID_STRONG = "#3b414d"
FG = "#d7dae0"
FG_DIM = "#8a909c"
OK_COLOR = "#4cc777"     # nur fuer Statusmeldungen
ERR = "#ff6b6b"
ACCENT = "#3a7bd5"

FONT = ("Segoe UI", 9)
FONT_SMALL = ("Segoe UI", 8)
FONT_MONO = ("Consolas", 10)

# ---------------------------------------------------------------- OIDs
OID_IFDESCR = "1.3.6.1.2.1.2.2.1.2"
OID_IFNAME = "1.3.6.1.2.1.31.1.1.1.1"
OID_IFALIAS = "1.3.6.1.2.1.31.1.1.1.18"
OID_IN32 = "1.3.6.1.2.1.2.2.1.10"
OID_OUT32 = "1.3.6.1.2.1.2.2.1.16"
OID_IN64 = "1.3.6.1.2.1.31.1.1.1.6"
OID_OUT64 = "1.3.6.1.2.1.31.1.1.1.10"

DEFAULTS = {
    "host": "",
    "port": 161,
    "community": "public",
    "ifindex": 0,
    "ifname": "",
    "interval": 1.0,      # Sekunden zwischen Abfragen
    "window": 300,        # angezeigter Zeitraum in Sekunden
    "unit": "bit",        # "bit" oder "byte"
    "topmost": False,
    "borderless": False,
    "geometry": "680x280",
    "color_in": "#ffa94d",
    "color_out": "#b197fc",
    "color_label": "#8a909c",
    "show_label": True,
    "tray": False,        # nur im Infobereich statt in der Taskleiste (Windows)
    "fill": "in",         # gefuellte Flaeche: "in", "out", "both", "none"
    "alpha": 100,         # Deckkraft des Fensters in Prozent
    "alpha_hover": True,  # unter der Maus voll deckend
    "bg_alpha": 100,      # Deckkraft des Hintergrunds in Prozent (100 = normal, Windows)
    "snmp_version": "2c",  # "2c" oder "3"
    "v3_user": "",
    "v3_auth": "SHA-256",  # keine, MD5, SHA, SHA-224/256/384/512
    "v3_auth_pw": "",      # geschuetzt gespeichert (Windows: DPAPI), siehe protect_secret
    "v3_priv": "AES-128",  # keine, AES-128
    "v3_priv_pw": "",
    "if_sum": False,       # mehrere Interfaces addieren
    "ifindexes": [],       # bei if_sum: die addierten Interfaces
    "ifnames": [],         # deren Namen (fuer die Anzeige ohne Abfrage)
}

HISTORY = 3600            # so viele Sekunden werden immer im Speicher gehalten
ZOOM_STEPS = (60, 120, 300, 600, 900, 1800, 3600)
FILL_MODES = (("in", "In gefüllt"), ("out", "Out gefüllt"), ("both", "Beide gefüllt"),
              ("none", "Keine Füllung"))

# ---------------------------------------------------------------- Sprache
# Oberflaeche deutsch oder englisch: Texte stehen im Code auf Deutsch, T() liefert bei
# englischer Oberflaeche die Uebersetzung aus EN (fehlt sie, bleibt der deutsche Text).
# Die Wahl steht in settings.cfg ("language": auto/de/en), auto = Sprache von Windows.
BACKUP_DIR = "Backup"     # Unterordner des Konfigurationsordners fuer Sicherungskopien

LANG = "de"
LANG_CHOICES = (("auto", "Automatisch (Windows-Sprache)"), ("de", "Deutsch"), ("en", "English"))


def T(text, **kw):
    if LANG == "en":
        text = EN.get(text, text)
    return text.format(**kw) if kw else text


def detect_lang():
    """'de', wenn Windows (bzw. die Umgebung) deutsch eingestellt ist, sonst 'en'."""
    try:
        if sys.platform == "win32":
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "de" if (lid & 0x3FF) == 0x07 else "en"
        import locale
        loc = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG")
               or locale.getlocale()[0] or "")
        return "de" if loc.lower().startswith("de") else "en"
    except Exception:
        return "en"


def init_lang(pref=None):
    global LANG
    if pref is None:
        pref = load_settings().get("language", "auto")
    LANG = pref if pref in ("de", "en") else detect_lang()
    return LANG


EN = {
    # Fuellung / Menues
    "In gefüllt": "In filled", "Out gefüllt": "Out filled", "Beide gefüllt": "Both filled",
    "Keine Füllung": "No fill",
    "Fenster ausblenden": "Hide window", "Fenster anzeigen": "Show window",
    "Fenster ausblenden (nur im Tray-Modus)": "Hide window (tray mode only)",
    "Einstellungen …": "Settings …", "Pause": "Pause", "Fortsetzen": "Resume",
    "Pause-Taste": "Pause key", "Statistik zurücksetzen": "Reset statistics",
    "Zeitraum": "Time range", "Füllung": "Fill", "Immer im Vordergrund": "Always on top",
    "Ohne Titelleiste": "Borderless", "Nur im Infobereich (Tray)": "Notification area only (tray)",
    "Fenster anordnen": "Arrange windows", "Fenstergröße übernehmen für": "Copy window size to",
    "Weiteres Fenster öffnen": "Open another window",
    "Sicherungskopie speichern": "Save backup copy",
    "Sicherungskopie wiederherstellen": "Restore backup copy",
    "Sicherungskopie gespeichert: {name}": "Backup copy saved: {name}",
    "Sicherungskopie nicht gespeichert: {e}": "Backup copy not saved: {e}",
    "Keine Sicherungskopien von „{name}“": "No backup copies of “{name}”",
    "Backup-Ordner öffnen": "Open backup folder",
    "Stand vom {when}": "State of {when}",
    "„{name}“ auf den Stand vom {when} zurücksetzen?\n\n"
    "Die jetzigen Einstellungen werden vorher ebenfalls als Sicherungskopie gespeichert.":
        "Reset “{name}” to the state of {when}?\n\n"
        "The current settings are saved as a backup copy first.",
    "Sicherungskopie nicht lesbar: {e}": "Backup copy not readable: {e}",
    "Konfiguration in diesem Fenster laden": "Load configuration in this window",
    "Konfigurationsordner": "Configuration folder", "Verknüpfung": "Shortcut", "Beenden": "Exit",
    "{name}  ➜  neues Fenster": "{name}  ➜  new window", "   (schon offen)": "   (already open)",
    "Neue Konfiguration": "New configuration",
    "{name}  ⟲  hier laden (ersetzt dieses Fenster)": "{name}  ⟲  load here (replaces this window)",
    "Datei wählen …": "Choose file …", "Konfiguration laden": "Load configuration",
    "Nur unter Windows verfügbar": "Windows only",
    "„{name}“ auf den Desktop": "“{name}” on the desktop",
    "„{name}“ in den Autostart": "“{name}” in autostart", "  (aktualisieren)": "  (update)",
    "„{name}“ aus dem Autostart entfernen": "Remove “{name}” from autostart",
    "Autostart-Ordner öffnen": "Open autostart folder",
    "Verknüpfung erstellt:\n{info}\n\nStartet:\n{target} {args}":
        "Shortcut created:\n{info}\n\nStarts:\n{target} {args}",
    "Verknüpfung konnte nicht erstellt werden:\n\n{info}": "Could not create shortcut:\n\n{info}",
    "Aus dem Autostart entfernt": "Removed from autostart",
    "Im Explorer öffnen": "Open in Explorer", "Anderen Ordner wählen …": "Choose another folder …",
    "Zurück auf Standard (AppData)": "Back to default (AppData)",
    "Konfigurationsordner wählen": "Choose configuration folder",
    "Ordner nicht erreichbar:\n{d}": "Folder not reachable:\n{d}",
    "Im neuen Ordner gibt es schon „{name}“.\n\nJa: diese Konfiguration von dort laden\n"
    "Nein: mit der aktuellen Konfiguration überschreiben":
        "“{name}” already exists in the new folder.\n\nYes: load that configuration\n"
        "No: overwrite it with the current configuration",
    "Sollen auch die übrigen Konfigurationen in den neuen Ordner kopiert werden?\n\n":
        "Copy the other configurations to the new folder as well?\n\n",
    "Konfigurationsordner gewechselt": "Configuration folder changed",
    "Zurück zu „jetzt“": "Back to “now”", "Ende": "End",
    "Mausrad = blättern, Shift+Mausrad = Zeitraum": "Wheel = scroll, Shift+wheel = time range",
    "↓  darunter": "↓  below", "↑  darüber": "↑  above", "→  rechts daneben": "→  to the right",
    "←  links daneben": "←  to the left",
    "Dieses Fenster gibt Position und Größe vor; offen: ": "This window sets position and size; open: ",
    "Keine weiteren Fenster offen": "No other windows open",
    "Keine weiteren Konfigurationen": "No other configurations", "   (offen)": "   (open)",
    "alle": "all", "keine": "none",
    "{n} Fenster angeordnet": "{n} windows arranged",
    " – Stapel verschoben, damit alles auf den Monitor passt":
        " – stack moved so that everything fits on the monitor",
    "{n} Fenster angeordnet – der Monitor ist dafür zu klein, sie wurden an den Rand geschoben":
        "{n} windows arranged – the monitor is too small, they were moved to the edge",
    "Größe {w} × {h} übernommen: {names}": "Size {w} × {h} applied: {names}",
    "Nichts geändert": "Nothing changed",
    # Anzeige
    "Gespeichert: {name}": "Saved: {name}", "Pausiert": "Paused", " (nur Ansicht)": " (view only)",
    "alle {i} s": "every {i} s", "{kind}-Zähler": "{kind} counters", "jetzt": "now",
    "◀ zurückgeblättert {span}  ·  Ende = jetzt": "◀ scrolled back {span}  ·  End = now",
    "warte auf Daten …": "waiting for data …",
    "Infobereich nicht verfügbar: {e}": "Notification area not available: {e}",
    "{n} Interfaces, z. B. {x}": "{n} interfaces, e.g. {x}",
    "Konfiguration geschrieben, aber beim Gegenlesen anders – bitte melden":
        "Configuration written, but it differs when read back – please report",
    "Konfiguration nicht gespeichert: Ordner nicht erreichbar ({d})":
        "Configuration not saved: folder not reachable ({d})",
    "Konfiguration nicht gespeichert: {e}": "Configuration not saved: {e}",
    "Konfigurationsordner nicht erreichbar: {d} – Rechtsklick → Konfigurationsordner wählen":
        "Configuration folder not reachable: {d} – right-click → Configuration folder",
    "Diese Konfiguration ist schon in einem anderen Fenster offen – hier wird nichts gespeichert":
        "This configuration is already open in another window – nothing is saved here",
    "Verknüpfungen gibt es nur unter Windows": "Shortcuts are only available on Windows",
    "Interner Fehler:\n\n{val}\n\nDetails stehen in {log}": "Internal error:\n\n{val}\n\nDetails are in {log}",
    # SNMP
    "SNMPv3: Sicherheitsstufe wird vom Gerät nicht unterstützt":
        "SNMPv3: security level not supported by the device",
    "SNMPv3: Benutzername unbekannt": "SNMPv3: unknown user name",
    "SNMPv3: Anmeldung abgelehnt – Auth-Passwort oder -Verfahren falsch":
        "SNMPv3: authentication failed – wrong auth password or protocol",
    "SNMPv3: Entschlüsselung fehlgeschlagen – Priv-Passwort oder -Verfahren falsch":
        "SNMPv3: decryption failed – wrong priv password or protocol",
    "SNMPv3: Passwort fehlt": "SNMPv3: password missing",
    "SNMPv3: unbekanntes Auth-Verfahren {x}": "SNMPv3: unknown auth protocol {x}",
    "SNMPv3: unbekanntes Priv-Verfahren {x}": "SNMPv3: unknown priv protocol {x}",
    "SNMPv3: Auth-Passwort muss mindestens 8 Zeichen haben":
        "SNMPv3: auth password must have at least 8 characters",
    "SNMPv3: Priv-Passwort muss mindestens 8 Zeichen haben":
        "SNMPv3: priv password must have at least 8 characters",
    "keine SNMPv3-Antwort": "no SNMPv3 response",
    "SNMPv3: Antwort mit unerwarteter Anmeldung": "SNMPv3: response with unexpected authentication",
    "SNMPv3: Prüfsumme der Antwort falsch": "SNMPv3: response checksum wrong",
    "SNMPv3: verschlüsselte Antwort, aber kein Priv-Schlüssel":
        "SNMPv3: encrypted response, but no priv key",
    "Host nicht auflösbar: {host}": "Cannot resolve host: {host}",
    "Netzwerkfehler: {e}": "Network error: {e}", "SNMP-Fehlerstatus {err}": "SNMP error status {err}",
    "Keine Antwort (Timeout) – Community, ACL oder allowaccess prüfen":
        "No response (timeout) – check community, ACL or allowaccess",
    "SNMPv3: keine Antwort auf die Erkennung – Host, Port, SNMPv3-Freigabe auf dem Gerät prüfen":
        "SNMPv3: no response to discovery – check host, port and SNMPv3 access on the device",
    "SNMPv3: Gerät meldet keine Engine-ID": "SNMPv3: device reports no engine ID",
    "SNMPv3: keine Antwort (Timeout) – Benutzer, Passwörter, Sicherheitsstufe und Freigabe prüfen":
        "SNMPv3: no response (timeout) – check user, passwords, security level and access",
    "SNMPv3-Fehlermeldung {x}": "SNMPv3 report {x}",
    "SNMPv3: Zeitabgleich mit dem Gerät gescheitert": "SNMPv3: time synchronisation with the device failed",
    "SNMPv3-Passwort ist hier nicht lesbar (anderer Benutzer oder PC?) – bitte in den Einstellungen neu eingeben":
        "SNMPv3 password cannot be read here (other user or PC?) – please enter it again in the settings",
    "Keine Interfaces gefunden": "No interfaces found",
    "Interface-Index {idx} liefert keine Zähler": "Interface index {idx} returns no counters",
    "Zähler nicht lesbar": "Counters not readable",
    # Einstellungen
    "Einstellungen": "Settings", "Name": "Name", "Host / IP": "Host / IP", "Port": "Port",
    "Summe mehrerer Interfaces": "Sum of several interfaces", "Abfragen": "Query",
    "Kopieren": "Copy", "Intervall (s)": "Interval (s)", "Zeitraum (s)": "Time range (s)",
    "auch per Shift+Mausrad oder Kippen": "also via Shift+wheel or tilt", "Einheit": "Unit",
    "Farben": "Colours", "Standard": "Default", "Name im Graph": "Name in graph",
    "oben links anzeigen": "show top left", "beide": "both", "Hintergrund": "Background",
    "nur Hintergrund, Kurven bleiben voll": "background only, curves stay opaque",
    "Deckkraft": "Opacity", "ganzes Fenster": "whole window",
    "unter der Maus voll deckend": "fully opaque under the mouse", "Abbrechen": "Cancel",
    "Version 2c (Community)": "Version 2c (community)",
    "Version 3 (Benutzer, verschlüsselt)": "Version 3 (user, encrypted)",
    "Benutzer": "User", "Anmeldung": "Authentication", "Verschlüsselung": "Encryption",
    "Passwörter anzeigen": "Show passwords",
    "SNMPv3: Benutzername fehlt.": "SNMPv3: user name missing.",
    "SNMPv3: Auth-Passwort muss mindestens 8 Zeichen haben.":
        "SNMPv3: auth password must have at least 8 characters.",
    "SNMPv3: Priv-Passwort muss mindestens 8 Zeichen haben.":
        "SNMPv3: priv password must have at least 8 characters.",
    "{n} gewählt": "{n} selected",
    "Zum Auswählen erst „Abfragen“ klicken.": "Click “Query” first to choose.",
    "Farbe für {x}": "Colour for {x}", "Kopiert: {x}": "Copied: {x}",
    "Bitte zuerst Host angeben.": "Please enter a host first.", "Port ist keine Zahl.": "Port is not a number.",
    "Frage Interfaces ab …": "Querying interfaces …", "{n} Interfaces gefunden.": "{n} interfaces found.",
    "Port, Intervall und Zeitraum müssen Zahlen sein.": "Port, interval and time range must be numbers.",
    "Für die Summe mindestens ein Interface ankreuzen.": "Tick at least one interface for the sum.",
    "Host und Interface müssen gesetzt sein.": "Host and interface must be set.",
    "Intervall ≥ 0,2 s, Zeitraum ≥ 10 s, höchstens 20000 Messpunkte.":
        "Interval ≥ 0.2 s, time range ≥ 10 s, at most 20000 data points.",
    "Name: 1–40 Zeichen, nur Buchstaben, Ziffern, Leerzeichen, - und _.":
        "Name: 1–40 characters, only letters, digits, spaces, - and _.",
    "Eine Konfiguration „{name}“ gibt es schon.": "A configuration “{name}” already exists.",
    "„{name}“ ist gerade in einem anderen Fenster offen.": "“{name}” is currently open in another window.",
    "Summe {n} Interfaces": "Sum of {n} interfaces",
    "Sprache": "Language", "Automatisch (Windows-Sprache)": "Automatic (Windows language)",
    "neu": "new",
}


# ====================================================================
#  Minimaler SNMP-v2c-Client (BER-Kodierung von Hand)
# ====================================================================
class SnmpError(Exception):
    pass


def _enc_len(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag, value):
    return bytes([tag]) + _enc_len(len(value)) + value


def _enc_int(i):
    length = max(1, (i.bit_length() + 8) // 8)
    return _tlv(0x02, i.to_bytes(length, "big", signed=True))


def _enc_oid(oid):
    parts = [int(x) for x in oid.strip(".").split(".")]
    out = bytearray([parts[0] * 40 + parts[1]])
    for n in parts[2:]:
        chunk = [n & 0x7F]
        n >>= 7
        while n:
            chunk.append(0x80 | (n & 0x7F))
            n >>= 7
        out += bytes(reversed(chunk))
    return _tlv(0x06, bytes(out))


def _dec_tlv(data, pos):
    tag = data[pos]
    pos += 1
    length = data[pos]
    pos += 1
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[pos:pos + n], "big")
        pos += n
    return tag, data[pos:pos + length], pos + length


def _dec_oid(v):
    parts = [v[0] // 40, v[0] % 40]
    n = 0
    for b in v[1:]:
        n = (n << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(n)
            n = 0
    return ".".join(map(str, parts))


def _dec_value(tag, v):
    if tag == 0x02:
        return int.from_bytes(v, "big", signed=True)
    if tag in (0x41, 0x42, 0x43, 0x46):   # Counter32, Gauge32, TimeTicks, Counter64
        return int.from_bytes(v, "big")
    if tag == 0x04:
        return v.decode("utf-8", "replace")
    if tag == 0x06:
        return _dec_oid(v)
    if tag == 0x40:
        return ".".join(str(b) for b in v)
    return None   # Null, noSuchObject, noSuchInstance, endOfMibView


def build_request(community, pdu_type, oids, req_id):
    vbs = b"".join(_tlv(0x30, _enc_oid(o) + b"\x05\x00") for o in oids)
    pdu = _tlv(pdu_type, _enc_int(req_id) + _enc_int(0) + _enc_int(0) + _tlv(0x30, vbs))
    return _tlv(0x30, _enc_int(1) + _tlv(0x04, community.encode()) + pdu)


def parse_response(data):
    _, msg, _ = _dec_tlv(data, 0)
    _, _, p = _dec_tlv(msg, 0)          # Version
    _, _, p = _dec_tlv(msg, p)          # Community
    _, pdu, _ = _dec_tlv(msg, p)
    _, rid, q = _dec_tlv(pdu, 0)
    _, err, q = _dec_tlv(pdu, q)
    _, _, q = _dec_tlv(pdu, q)
    _, vbl, _ = _dec_tlv(pdu, q)
    result = []
    q = 0
    while q < len(vbl):
        _, vb, q = _dec_tlv(vbl, q)
        _, oid_raw, r = _dec_tlv(vb, 0)
        vtag, vraw, _ = _dec_tlv(vb, r)
        result.append((_dec_oid(oid_raw), vtag, _dec_value(vtag, vraw)))
    return (int.from_bytes(rid, "big", signed=True),
            int.from_bytes(err, "big"), result)


# ====================================================================
#  SNMPv3 (USM, RFC 3414 / 3826 / 7860) – ohne Fremdpakete
# ====================================================================
# AES-128 bringt Python nicht mit. Fuer ein paar kleine Pakete pro Sekunde reicht
# eine schlanke Umsetzung; SNMP nutzt AES im CFB-Modus, dafuer genuegt die
# Verschluesselungsrichtung des Blockchiffre.
def _aes_sbox():
    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)       # p * 3
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09                                               # q / 3
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) \
            ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


_SBOX = _aes_sbox()


def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


class AES128:
    def __init__(self, key):
        if len(key) != 16:
            raise ValueError("AES-128 braucht 16 Byte Schlüssel")
        w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
        rcon = 1
        for i in range(4, 44):
            t = list(w[i - 1])
            if i % 4 == 0:
                t = [_SBOX[b] for b in t[1:] + t[:1]]
                t[0] ^= rcon
                rcon = _xt(rcon)
            w.append([a ^ b for a, b in zip(w[i - 4], t)])
        self.rk = [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]

    def encrypt_block(self, block):
        s = [a ^ b for a, b in zip(block, self.rk[0])]
        for r in range(1, 11):
            s = [_SBOX[b] for b in s]
            s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]             # ShiftRows
            if r != 10:
                m = []
                for c in range(4):
                    a0, a1, a2, a3 = s[4 * c:4 * c + 4]
                    t = a0 ^ a1 ^ a2 ^ a3
                    m += [a0 ^ t ^ _xt(a0 ^ a1), a1 ^ t ^ _xt(a1 ^ a2),
                          a2 ^ t ^ _xt(a2 ^ a3), a3 ^ t ^ _xt(a3 ^ a0)]
                s = m
            s = [a ^ b for a, b in zip(s, self.rk[r])]
        return bytes(s)


def aes_cfb(key, iv, data, decrypt=False):
    """AES-128 im CFB-128-Modus (RFC 3826)."""
    aes = AES128(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        ks = aes.encrypt_block(prev)
        res = bytes(a ^ b for a, b in zip(chunk, ks))
        out += res
        prev = (chunk if decrypt else res) + b"\0" * (16 - len(chunk))
    return bytes(out)


# Anmeldeverfahren: Name -> (hashlib-Name, Laenge der Pruefsumme im Paket)
V3_AUTH = {"MD5": ("md5", 12), "SHA": ("sha1", 12), "SHA-224": ("sha224", 16),
           "SHA-256": ("sha256", 24), "SHA-384": ("sha384", 32), "SHA-512": ("sha512", 48)}
V3_AUTH_CHOICES = ["keine"] + list(V3_AUTH)
V3_PRIV_CHOICES = ["keine", "AES-128"]

_USM_REPORTS = {
    "1.3.6.1.6.3.15.1.1.1.0": "SNMPv3: Sicherheitsstufe wird vom Gerät nicht unterstützt",
    "1.3.6.1.6.3.15.1.1.3.0": "SNMPv3: Benutzername unbekannt",
    "1.3.6.1.6.3.15.1.1.5.0": "SNMPv3: Anmeldung abgelehnt – Auth-Passwort oder -Verfahren falsch",
    "1.3.6.1.6.3.15.1.1.6.0": "SNMPv3: Entschlüsselung fehlgeschlagen – Priv-Passwort oder -Verfahren falsch",
}
_USM_UNKNOWN_ENGINE = "1.3.6.1.6.3.15.1.1.4.0"
_USM_NOT_IN_TIME = "1.3.6.1.6.3.15.1.1.2.0"


def v3_password_key(password, hash_name):
    """Passwort -> Schluessel Ku (RFC 3414 A.2: 1 MB wiederholtes Passwort hashen)."""
    import hashlib
    pw = password.encode("utf-8")
    if not pw:
        raise SnmpError(T("SNMPv3: Passwort fehlt"))
    data = (pw * (1048576 // len(pw) + 1))[:1048576]
    return hashlib.new(hash_name, data).digest()


def v3_localize(ku, engine_id, hash_name):
    import hashlib
    return hashlib.new(hash_name, ku + engine_id + ku).digest()


def _dec_pos(data, pos):
    """Wie _dec_tlv, liefert aber (tag, Wertanfang, Wertende) im Gesamtpaket."""
    tag = data[pos]
    pos += 1
    length = data[pos]
    pos += 1
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[pos:pos + n], "big")
        pos += n
    return tag, pos, pos + length


def parse_pdu(pdu_tag, pdu):
    _, rid, q = _dec_tlv(pdu, 0)
    _, err, q = _dec_tlv(pdu, q)
    _, _, q = _dec_tlv(pdu, q)
    _, vbl, _ = _dec_tlv(pdu, q)
    result = []
    q = 0
    while q < len(vbl):
        _, vb, q = _dec_tlv(vbl, q)
        _, oid_raw, r = _dec_tlv(vb, 0)
        vtag, vraw, _ = _dec_tlv(vb, r)
        result.append((_dec_oid(oid_raw), vtag, _dec_value(vtag, vraw)))
    return (pdu_tag, int.from_bytes(rid, "big", signed=True), int.from_bytes(err, "big"), result)


class SnmpV3:
    """User-based Security Model fuer einen Agenten (Discovery, Zeitabgleich,
    Anmeldung, Verschluesselung)."""

    def __init__(self, user, auth="SHA-256", auth_pw="", priv="AES-128", priv_pw=""):
        self.user = user.encode("utf-8")
        self.auth = None if auth in (None, "", "keine") else auth
        self.priv = None if (priv in (None, "", "keine") or not self.auth) else priv
        if self.auth and self.auth not in V3_AUTH:
            raise SnmpError(T("SNMPv3: unbekanntes Auth-Verfahren {x}", x=auth))
        if self.priv and self.priv != "AES-128":
            raise SnmpError(T("SNMPv3: unbekanntes Priv-Verfahren {x}", x=priv))
        if self.auth and len(auth_pw) < 8:
            raise SnmpError(T("SNMPv3: Auth-Passwort muss mindestens 8 Zeichen haben"))
        if self.priv and len(priv_pw) < 8:
            raise SnmpError(T("SNMPv3: Priv-Passwort muss mindestens 8 Zeichen haben"))
        self._auth_pw, self._priv_pw = auth_pw, priv_pw
        self.engine_id = None
        self.boots = 0
        self._time0 = 0
        self._tref = 0.0
        self._salt = random.getrandbits(64)
        self.k_auth = self.k_priv = None

    # ---------------------------------------------------- Zustand
    @property
    def ready(self):
        return self.engine_id is not None

    def engine_time(self):
        return max(0, self._time0 + int(time.monotonic() - self._tref))

    def set_engine(self, engine_id, boots, etime):
        new = engine_id != self.engine_id
        self.engine_id, self.boots = engine_id, boots
        self._time0, self._tref = etime, time.monotonic()
        if new and self.auth:
            h = V3_AUTH[self.auth][0]
            self.k_auth = v3_localize(v3_password_key(self._auth_pw, h), engine_id, h)
            if self.priv:
                self.k_priv = v3_localize(v3_password_key(self._priv_pw, h), engine_id, h)[:16]

    # ---------------------------------------------------- Pakete
    def build(self, pdu_type, oids, rid, msg_id, discovery=False):
        vbs = b"".join(_tlv(0x30, _enc_oid(o) + b"\x05\x00") for o in oids)
        pdu = _tlv(pdu_type, _enc_int(rid) + _enc_int(0) + _enc_int(0) + _tlv(0x30, vbs))
        if discovery:
            eid, boots, etime, user, level = b"", 0, 0, b"", 0
        else:
            eid, boots, etime, user = self.engine_id, self.boots, self.engine_time(), self.user
            level = (1 if self.auth else 0) | (2 if self.priv else 0)
        scoped = _tlv(0x30, _tlv(0x04, eid) + _tlv(0x04, b"") + pdu)
        priv_params = b""
        if level & 2:
            self._salt = (self._salt + 1) & 0xFFFFFFFFFFFFFFFF
            priv_params = self._salt.to_bytes(8, "big")
            iv = boots.to_bytes(4, "big") + etime.to_bytes(4, "big") + priv_params
            msg_data = _tlv(0x04, aes_cfb(self.k_priv, iv, scoped))
        else:
            msg_data = scoped
        alen = V3_AUTH[self.auth][1] if level & 1 else 0
        glob = _tlv(0x30, _enc_int(msg_id) + _enc_int(65507)
                    + _tlv(0x04, bytes([level | 0x04])) + _enc_int(3))

        def whole(auth_params):
            usm = _tlv(0x30, _tlv(0x04, eid) + _enc_int(boots) + _enc_int(etime)
                       + _tlv(0x04, user) + _tlv(0x04, auth_params) + _tlv(0x04, priv_params))
            return _tlv(0x30, _enc_int(3) + glob + _tlv(0x04, usm) + msg_data)

        if not alen:
            return whole(b"")
        import hmac
        draft = whole(b"\0" * alen)
        mac = hmac.new(self.k_auth, draft, V3_AUTH[self.auth][0]).digest()[:alen]
        return whole(mac)

    def parse(self, data):
        """-> (msg_id, pdu_tag, rid, err, varbinds). Prueft Anmeldung, entschluesselt,
        uebernimmt Engine-Daten aus Reports."""
        _, s, e = _dec_pos(data, 0)
        _, a, b = _dec_pos(data, s)                         # Version
        if int.from_bytes(data[a:b], "big") != 3:
            raise SnmpError(T("keine SNMPv3-Antwort"))
        _, gs, ge = _dec_pos(data, b)                       # msgGlobalData
        _, a, b2 = _dec_pos(data, gs)
        msg_id = int.from_bytes(data[a:b2], "big", signed=True)
        _, a, b2 = _dec_pos(data, b2)                       # maxSize
        _, a, b2 = _dec_pos(data, b2)                       # Flags
        flags = data[a] if b2 > a else 0
        _, us, ue = _dec_pos(data, ge)                      # msgSecurityParameters
        _, ss, se = _dec_pos(data, us)                      # USM-Sequenz
        fields = []
        p = ss
        for _ in range(6):
            _, a, b2 = _dec_pos(data, p)
            fields.append((a, b2))
            p = b2
        eid = data[fields[0][0]:fields[0][1]]
        boots = int.from_bytes(data[fields[1][0]:fields[1][1]], "big")
        etime = int.from_bytes(data[fields[2][0]:fields[2][1]], "big")
        aa, ab = fields[4]
        priv_params = data[fields[5][0]:fields[5][1]]
        if flags & 1:
            if not self.auth or eid != self.engine_id:
                raise SnmpError(T("SNMPv3: Antwort mit unerwarteter Anmeldung"))
            import hmac
            plain = data[:aa] + b"\0" * (ab - aa) + data[ab:]
            mac = hmac.new(self.k_auth, plain, V3_AUTH[self.auth][0]).digest()[:ab - aa]
            if not hmac.compare_digest(mac, data[aa:ab]):
                raise SnmpError(T("SNMPv3: Prüfsumme der Antwort falsch"))
        tag, ms, me = _dec_pos(data, ue)                    # msgData
        if flags & 2:
            if tag != 0x04 or not self.k_priv:
                raise SnmpError(T("SNMPv3: verschlüsselte Antwort, aber kein Priv-Schlüssel"))
            iv = boots.to_bytes(4, "big") + etime.to_bytes(4, "big") + priv_params
            scoped = aes_cfb(self.k_priv, iv, data[ms:me], decrypt=True)
            _, s2, _ = _dec_pos(scoped, 0)
        else:
            scoped, s2 = data, ms
        _, a, b2 = _dec_pos(scoped, s2)                     # contextEngineID
        _, a, b2 = _dec_pos(scoped, b2)                     # contextName
        ptag, a, b2 = _dec_pos(scoped, b2)
        pdu_tag, rid, err, vbs = parse_pdu(ptag, scoped[a:b2])
        if pdu_tag == 0xA8 and eid:                         # Report: Engine-Daten merken
            if eid != self.engine_id or vbs and vbs[0][0] == _USM_NOT_IN_TIME:
                self.set_engine(eid, boots, etime)
        elif flags & 1 and eid == self.engine_id:
            # authentische Antwort: Uhr nachfuehren (RFC 3414 3.2 Schritt 7)
            if boots > self.boots or (boots == self.boots and etime > self.engine_time()):
                self.boots, self._time0, self._tref = boots, etime, time.monotonic()
        return msg_id, pdu_tag, rid, err, vbs


class SnmpClient:
    def __init__(self, host, community, port=161, timeout=1.5, retries=1, v3=None):
        try:
            info = socket.getaddrinfo(host, port, 0, socket.SOCK_DGRAM)[0]
        except socket.gaierror as e:
            raise SnmpError(T("Host nicht auflösbar: {host}", host=host)) from e
        self.addr = info[4]
        self.sock = socket.socket(info[0], socket.SOCK_DGRAM)
        self.community = community
        self.timeout = timeout
        self.retries = retries
        self.v3 = v3                         # SnmpV3 oder None (= v2c)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _request(self, pdu_type, oids):
        if self.v3:
            return self._request_v3(pdu_type, oids)
        rid = random.randint(1, 2**31 - 1)
        packet = build_request(self.community, pdu_type, oids, rid)
        for _ in range(self.retries + 1):
            self.sock.sendto(packet, self.addr)
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.sock.settimeout(remaining)
                try:
                    data, _ = self.sock.recvfrom(65535)
                except socket.timeout:
                    break
                except OSError as e:
                    raise SnmpError(T("Netzwerkfehler: {e}", e=e)) from e
                try:
                    r, err, vbs = parse_response(data)
                except Exception:
                    continue
                if r != rid:
                    continue
                if err:
                    raise SnmpError(T("SNMP-Fehlerstatus {err}", err=err))
                return vbs
        raise SnmpError(T("Keine Antwort (Timeout) – Community, ACL oder allowaccess prüfen"))

    def _exchange_v3(self, pdu_type, oids, discovery=False):
        """Ein Versuch mit Wiederholungen bei Zeitueberschreitung.
        -> (pdu_tag, err, varbinds) oder None bei Timeout."""
        v3 = self.v3
        rid = random.randint(1, 2**31 - 1)
        mid = random.randint(1, 2**31 - 1)
        for _ in range(self.retries + 1):
            packet = v3.build(pdu_type, oids, rid, mid, discovery=discovery)
            self.sock.sendto(packet, self.addr)
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.sock.settimeout(remaining)
                try:
                    data, _ = self.sock.recvfrom(65535)
                except socket.timeout:
                    break
                except OSError as e:
                    raise SnmpError(T("Netzwerkfehler: {e}", e=e)) from e
                try:
                    m, tag, r, err, vbs = v3.parse(data)
                except SnmpError:
                    raise
                except Exception:
                    continue
                if m != mid:
                    continue
                return tag, err, vbs
        return None

    def _request_v3(self, pdu_type, oids):
        v3 = self.v3
        for _ in range(3):
            if not v3.ready:                     # Engine-ID, Boots und Uhr des Agenten holen
                res = self._exchange_v3(0xA0, [], discovery=True)
                if res is None:
                    raise SnmpError(T("SNMPv3: keine Antwort auf die Erkennung – Host, Port, "
                                      "SNMPv3-Freigabe auf dem Gerät prüfen"))
                if not v3.ready:
                    raise SnmpError(T("SNMPv3: Gerät meldet keine Engine-ID"))
            res = self._exchange_v3(pdu_type, oids)
            if res is None:
                raise SnmpError(T("SNMPv3: keine Antwort (Timeout) – Benutzer, Passwörter, "
                                  "Sicherheitsstufe und Freigabe prüfen"))
            tag, err, vbs = res
            if tag == 0xA8:                          # Report
                oid = vbs[0][0] if vbs else ""
                if oid in (_USM_NOT_IN_TIME, _USM_UNKNOWN_ENGINE):
                    continue                         # Uhr/Engine uebernommen -> nochmal
                raise SnmpError(T(_USM_REPORTS[oid]) if oid in _USM_REPORTS else T("SNMPv3-Fehlermeldung {x}", x=oid))
            if err:
                raise SnmpError(T("SNMP-Fehlerstatus {err}", err=err))
            return vbs
        raise SnmpError(T("SNMPv3: Zeitabgleich mit dem Gerät gescheitert"))

    def get(self, oids):
        return self._request(0xA0, oids)

    def walk(self, base, limit=5000):
        out, oid, prefix = [], base, base + "."
        for _ in range(limit):
            o, tag, val = self._request(0xA1, [oid])[0]
            if tag in (0x80, 0x81, 0x82) or not o.startswith(prefix):
                break
            out.append((o, val))
            oid = o
        return out


# ---------------------------------------------------------------- Passwoerter
def _dpapi(data, protect):
    """Windows-Datenschutz-API: an das Benutzerkonto gebunden verschluesseln."""
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(BLOB), ctypes.c_wchar_p, ctypes.POINTER(BLOB), ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buf = ctypes.create_string_buffer(data, len(data))
    src = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    # 0x1 = CRYPTPROTECT_UI_FORBIDDEN
    if not fn(ctypes.byref(src), "FTG" if protect else None, None, None, None, 0x1, ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), "DPAPI")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect_secret(text):
    """Passwort fuer die Konfigurationsdatei: unter Windows per DPAPI an das
    Benutzerkonto gebunden ("dpapi:…"), sonst nur verschleiert ("b64:…")."""
    import base64
    if not text:
        return ""
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        try:
            return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode()
        except OSError:
            pass
    return "b64:" + base64.b64encode(raw).decode()


def reveal_secret(stored):
    """Gegenstueck zu protect_secret. SnmpError, wenn es hier nicht lesbar ist
    (z. B. anderer Windows-Benutzer oder anderer PC)."""
    import base64
    if not stored:
        return ""
    try:
        if stored.startswith("dpapi:"):
            if sys.platform != "win32":
                raise OSError("kein Windows")
            return _dpapi(base64.b64decode(stored[6:]), False).decode("utf-8")
        if stored.startswith("b64:"):
            return base64.b64decode(stored[4:]).decode("utf-8")
    except (OSError, ValueError) as e:
        raise SnmpError(T("SNMPv3-Passwort ist hier nicht lesbar (anderer Benutzer oder PC?) – "
                          "bitte in den Einstellungen neu eingeben")) from e
    return stored                                    # Klartext (von Hand eingetragen)


def make_client(cfg, timeout=1.5, retries=1, secrets=None):
    """SNMP-Client passend zur Konfiguration. secrets = (auth_pw, priv_pw) im
    Klartext (aus dem Dialog), sonst werden sie aus cfg entschluesselt."""
    v3 = None
    if str(cfg.get("snmp_version", "2c")) == "3":
        if secrets is None:
            secrets = (reveal_secret(cfg.get("v3_auth_pw", "")), reveal_secret(cfg.get("v3_priv_pw", "")))
        v3 = SnmpV3(cfg.get("v3_user", ""), cfg.get("v3_auth", "SHA-256"), secrets[0],
                    cfg.get("v3_priv", "AES-128"), secrets[1])
    return SnmpClient(cfg["host"], cfg.get("community", ""), int(cfg["port"]),
                      timeout=timeout, retries=retries, v3=v3)


def snmp_label(cfg):
    if str(cfg.get("snmp_version", "2c")) != "3":
        return "SNMPv2c"
    a, p = cfg.get("v3_auth", "keine"), cfg.get("v3_priv", "keine")
    if a == "keine":
        return "SNMPv3"
    return f"SNMPv3 {a}" + (f"/{p}" if p != "keine" else "")


def list_interfaces(client):
    def table(oid):
        try:
            return {int(o.rsplit(".", 1)[1]): str(v or "") for o, v in client.walk(oid)}
        except SnmpError:
            return {}
    names = table(OID_IFNAME) or table(OID_IFDESCR)
    if not names:
        raise SnmpError(T("Keine Interfaces gefunden"))
    aliases = table(OID_IFALIAS)
    return [(i, names[i], aliases.get(i, "")) for i in sorted(names)]


def detect_counters(client, idx):
    try:
        vbs = client.get([f"{OID_IN64}.{idx}", f"{OID_OUT64}.{idx}"])
        if all(t == 0x46 for _, t, _ in vbs):
            return [o for o, _, _ in vbs], 2**64, "64-Bit"
    except SnmpError:
        pass
    vbs = client.get([f"{OID_IN32}.{idx}", f"{OID_OUT32}.{idx}"])
    if all(t == 0x41 for _, t, _ in vbs):
        return [o for o, _, _ in vbs], 2**32, "32-Bit"
    raise SnmpError(T("Interface-Index {idx} liefert keine Zähler", idx=idx))


# ====================================================================
#  Abfrage-Thread
# ====================================================================
def next_tick(now, interval):
    """Naechster Zeitpunkt nach 'now', der ein Vielfaches von 'interval' ist
    (gemessen an der Systemuhr). Knapp verpasste Punkte werden uebersprungen."""
    t = (math.floor(now / interval + 1e-9) + 1) * interval
    if t - now < 0.005:
        t += interval
    return t


def config_indexes(cfg):
    """Abzufragende Interface-Indizes: eins oder (Summe) mehrere."""
    if cfg.get("if_sum") and cfg.get("ifindexes"):
        return [int(i) for i in cfg["ifindexes"]]
    return [int(cfg["ifindex"])]


class Poller(threading.Thread):
    def __init__(self, cfg, out_queue, gen):
        super().__init__(daemon=True)
        self.cfg = dict(cfg)
        self.q = out_queue
        self.gen = gen
        self.stop_evt = threading.Event()

    def stop(self):
        self.stop_evt.set()

    def run(self):
        cfg = self.cfg
        interval = max(0.2, float(cfg["interval"]))
        indexes = config_indexes(cfg)
        client = None
        counters = None                # [(oid_in, oid_out, wrap), ...] je Interface
        prev = None
        tick = time.time()             # erste Abfrage sofort (Ausgangswert)
        while not self.stop_evt.is_set():
            try:
                if client is None:
                    client = make_client(cfg, timeout=min(2.0, max(0.5, interval * 0.9)))
                if counters is None:
                    counters, kinds = [], set()
                    for idx in indexes:
                        o, wrap, kind = detect_counters(client, idx)
                        counters.append((o[0], o[1], wrap))
                        kinds.add(kind)
                    kind = "/".join(sorted(kinds))
                    shown = [counters[0][0], counters[0][1]] if len(counters) == 1 else \
                        [T("{n} Interfaces, z. B. {x}", n=len(counters), x=counters[0][0]),
                         T("{n} Interfaces, z. B. {x}", n=len(counters), x=counters[0][1])]
                    self.q.put((self.gen, "info", kind, shown))
                # alle Zaehler in moeglichst wenigen Anfragen (max. 40 Werte je Paket)
                oids = [o for c in counters for o in c[:2]]
                vals = []
                for i in range(0, len(oids), 40):
                    vals += [v for _, _, v in client.get(oids[i:i + 40])]
                now = time.monotonic()
                if any(v is None for v in vals):
                    raise SnmpError(T("Zähler nicht lesbar"))
                if prev is not None:
                    dt = now - prev[0]
                    din = dout = 0
                    reset = False
                    for k, (_, _, wrap) in enumerate(counters):
                        a = (vals[2 * k] - prev[1][2 * k]) % wrap
                        b = (vals[2 * k + 1] - prev[1][2 * k + 1]) % wrap
                        # Zaehler-Reset (z. B. Neustart) bei 64 Bit erkennen
                        if wrap == 2**64 and (a > 2**62 or b > 2**62):
                            reset = True
                        din += a
                        dout += b
                    if not reset and dt > 0:
                        self.q.put((self.gen, "data", tick, din * 8 / dt, dout * 8 / dt))
                    # Diagnose: die ersten Messungen je Interface ins Log
                    self._diag = getattr(self, "_diag", 0) + 1
                    if self._diag <= 3 and len(counters) > 1 and dt > 0:
                        per = []
                        for k, (oi, _, wrap) in enumerate(counters):
                            a = (vals[2 * k] - prev[1][2 * k]) % wrap * 8 / dt
                            b = (vals[2 * k + 1] - prev[1][2 * k + 1]) % wrap * 8 / dt
                            per.append(f"{indexes[k]}: {fmt_rate(a)}/{fmt_rate(b)}")
                        self.q.put((self.gen, "log", f"Summe Messung {self._diag} (dt {dt:.2f} s"
                                    + (", Zähler-Reset erkannt" if reset else "") + "): "
                                    + f"gesamt {fmt_rate(din * 8 / dt)}/{fmt_rate(dout * 8 / dt)} – "
                                    + ", ".join(per)))
                prev = (now, vals)
            except SnmpError as e:
                self.q.put((self.gen, "error", str(e)))
                prev = None
            except Exception as e:  # unerwartet, aber weiterlaufen
                self.q.put((self.gen, "error", f"{type(e).__name__}: {e}"))
                prev = None
                counters = None
            # naechste Abfrage auf den naechsten Rasterpunkt der Uhrzeit legen
            # (bei 1 s jede volle Sekunde, bei 0,5 s jede volle und halbe ...),
            # so laufen alle Fenster mit gleichem Intervall im selben Takt
            tick = next_tick(time.time(), interval)
            while not self.stop_evt.is_set():
                rest = tick - time.time()
                if rest <= 0:
                    break
                if rest > interval + 0.5:                 # Uhr zurueckgestellt
                    tick = next_tick(time.time(), interval)
                    continue
                self.stop_evt.wait(rest)                  # wacht evtl. etwas zu frueh auf
        if client:
            client.close()


# ====================================================================
#  Hilfsfunktionen Anzeige
# ====================================================================
def fmt_rate(bps, unit="bit"):
    if bps is None:
        return "–"
    if unit == "byte":
        v = bps / 8
        units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"]
    else:
        v = bps
        units = ["bit/s", "Kbit/s", "Mbit/s", "Gbit/s", "Tbit/s"]
    i = 0
    while v >= 1000 and i < len(units) - 1:
        v /= 1000
        i += 1
    if i == 0 or v >= 100:
        s = f"{v:.0f}"
    elif v >= 10:
        s = f"{v:.1f}"
    else:
        s = f"{v:.2f}"
    return f"{s.replace('.', ',') if LANG == 'de' else s} {units[i]}"


def fmt_span(a):
    """Zeitspanne in Sekunden lesbar: 30 s, 5 min, 7:30 min, 1 h, 1:30 h."""
    a = int(round(a))
    if a < 60:
        return f"{a} s"
    if a < 3600:
        m, sec = divmod(a, 60)
        return f"{m} min" if not sec else f"{m}:{sec:02d} min"
    h, m = divmod(a // 60, 60)
    return f"{h} h" if not m else f"{h}:{m:02d} h"


def fmt_age(a):
    return "-" + fmt_span(a)


def view_stats(pts):
    """Ø, max und letzter Wert fuer In und Out ueber die gegebenen Punkte."""
    n = 0
    s_in = s_out = m_in = m_out = 0.0
    c_in = c_out = None
    for _, vi, vo in pts:
        if vi is None:
            continue
        n += 1
        s_in += vi
        s_out += vo
        if vi > m_in:
            m_in = vi
        if vo > m_out:
            m_out = vo
        c_in, c_out = vi, vo
    if not n:
        return None, None, None, None, None, None
    return s_in / n, s_out / n, m_in, m_out, c_in, c_out


def scroll_step(window, interval):
    """Schrittweite beim Zurueckblaettern: etwa ein Zehntel des Zeitraums, rund."""
    want = max(interval, window / 10)
    return next((t for t in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if t >= want), 600)


def blend(c1, c2, a):
    """Mischt Farbe c1 mit Anteil a in c2 (Hex)."""
    try:
        x = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
        y = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    except (ValueError, TypeError):
        return c2
    return "#" + "".join(f"{round(a * u + (1 - a) * v):02x}" for u, v in zip(x, y))


def nice_ceiling(v):
    if v <= 0:
        return 0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if m * e >= v:
            return m * e
    return 10 * e


# ---------------------------------------------------------------- Verknuepfungen
def to_unc(path):
    """Z:\\pfad -> \\\\server\\freigabe\\pfad, falls Z: ein Netzlaufwerk ist."""
    path = os.path.abspath(path)
    if sys.platform != "win32" or len(path) < 2 or path[1] != ":":
        return path
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.c_ulong(1024)
        if ctypes.windll.mpr.WNetGetConnectionW(path[:2], buf, ctypes.byref(n)) == 0:
            return buf.value.rstrip("\\") + path[2:]
    except Exception:
        pass
    return path


def startup_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def shortcut_name(cfg_path):
    return f"FTG {config_name(cfg_path)}.lnk"


def launch_command(cfg_path):
    """(Programm, Argumente, Arbeitsordner) fuer eine Verknuepfung."""
    cfg = to_unc(cfg_path)
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return exe, f'"{cfg}"', os.path.dirname(exe)
    exe = sys.executable
    if os.path.basename(exe).lower() == "python.exe":
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(w):
            exe = w
    script = to_unc(os.path.abspath(__file__))
    return exe, f'"{script}" "{cfg}"', os.path.dirname(script)


_PS_SHORTCUT = r"""
$ws  = New-Object -ComObject WScript.Shell
$dir = if ($env:FTG_WHERE -eq 'Startup') { [Environment]::GetFolderPath('Startup') }
       else { [Environment]::GetFolderPath('Desktop') }
$p = Join-Path $dir $env:FTG_LNK
$l = $ws.CreateShortcut($p)
$l.TargetPath = $env:FTG_TARGET
$l.Arguments = $env:FTG_ARGS
$l.WorkingDirectory = $env:FTG_WD
$l.Description = $env:FTG_DESC
if ($env:FTG_ICON) { $l.IconLocation = $env:FTG_ICON + ',0' }
$l.Save()
Write-Output $p
"""


def create_shortcut(cfg_path, where):
    """where: 'Desktop' oder 'Startup'. Gibt (ok, Pfad oder Fehlertext) zurueck."""
    if sys.platform != "win32":
        return False, T("Verknüpfungen gibt es nur unter Windows")
    import subprocess
    target, args, wd = launch_command(cfg_path)
    env = dict(os.environ, FTG_WHERE=where, FTG_LNK=shortcut_name(cfg_path), FTG_TARGET=target,
               FTG_ARGS=args, FTG_WD=wd, FTG_DESC=f"{APP_LONG} – {config_name(cfg_path)}",
               FTG_ICON=app_icon_path() or "")
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                            "Bypass", "-Command", _PS_SHORTCUT], env=env, capture_output=True,
                           text=True, errors="replace", timeout=30,
                           creationflags=0x08000000)          # CREATE_NO_WINDOW
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()[:300] or f"PowerShell-Fehler {r.returncode}"
    return True, r.stdout.strip()


# ---------------------------------------------------------------- Programmsymbol
ICON_VERSION = 1          # erhoehen, wenn sich das Aussehen aendert (erzeugt .ico neu)


def render_app_icon(S):
    """Programmsymbol: dunkles abgerundetes Quadrat mit kleinem Traffic-Graph
    (orange Flaeche fuer In, lavendel Linie fuer Out). Kantenglaettung per
    Ueberabtastung. Rueckgabe: RGBA, zeilenweise von oben."""
    ss = 4 if S <= 64 else 2
    N = S * ss
    small = S <= 32                     # Taskleiste/Titelleiste: Graph groesser, Linien kraeftiger
    rad = N * (0.16 if small else 0.20)
    border = max(1.0, N / 64) if not small else ss * 0.6
    gx0, gx1 = (N * 0.08, N * 0.92) if small else (N * 0.14, N * 0.86)
    gy_top, gy_bot = (N * 0.10, N * 0.88) if small else (N * 0.18, N * 0.80)
    th_in = max(ss * 1.7, N * 0.045) if small else N * 0.042
    th_out = max(ss * 1.5, N * 0.040) if small else N * 0.036

    def lerp(a, b, t):
        return a + (b - a) * t

    def rgb(c):
        return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)

    c_bg_top, c_bg_bot = rgb("#252a33"), rgb(BG)
    c_border = rgb(GRID_STRONG)
    c_grid = rgb(GRID)
    c_in, c_out = rgb(DEFAULTS["color_in"]), rgb(DEFAULTS["color_out"])
    c_fill_top = rgb(blend(DEFAULTS["color_in"], BG, 0.55))
    c_fill_bot = rgb(blend(DEFAULTS["color_in"], BG, 0.18))

    def f_in(t):      # Download: ruhig, dann ein kraeftiger Anstieg
        return (0.28 + 0.10 * math.sin(t * 7.0) + 0.55 * math.exp(-((t - 0.70) / 0.13) ** 2))

    def f_out(t):     # Upload: niedrig, leicht wellig
        return 0.14 + 0.07 * math.sin(t * 11.0 + 1.0) + 0.12 * math.exp(-((t - 0.32) / 0.10) ** 2)

    def ycurve(f, x):
        t = (x - gx0) / (gx1 - gx0)
        return gy_bot - f(t) * (gy_bot - gy_top)

    def slope(f, x):
        h = (gx1 - gx0) / 400
        return (ycurve(f, x + h) - ycurve(f, x - h)) / (2 * h)

    # Kurvenwerte je Unter-Spalte vorab
    cols = []
    for X in range(N):
        x = X + 0.5
        if gx0 <= x <= gx1:
            cols.append((ycurve(f_in, x), math.sqrt(1 + slope(f_in, x) ** 2),
                         ycurve(f_out, x), math.sqrt(1 + slope(f_out, x) ** 2)))
        else:
            cols.append(None)

    out = bytearray(S * S * 4)
    for py in range(S):
        for px in range(S):
            r = g = b = a = 0.0
            for sy in range(ss):
                Y = py * ss + sy + 0.5
                for sx in range(ss):
                    X = px * ss + sx
                    x = X + 0.5
                    # abgerundetes Quadrat
                    dx = max(rad - x, 0, x - (N - rad))
                    dy = max(rad - Y, 0, Y - (N - rad))
                    d = math.hypot(dx, dy)
                    if d > rad:
                        continue
                    t = Y / N
                    col = [lerp(c_bg_top[i], c_bg_bot[i], t) for i in range(3)]
                    if rad - d < border:
                        col = list(c_border)
                    else:
                        # dezentes Gitter
                        if S >= 48:
                            for gl in (0.39, 0.59):
                                if abs(Y - N * gl) < max(ss * 0.5, N / 200) and gx0 <= x <= gx1:
                                    col = list(c_grid)
                        cc = cols[X]
                        if cc is not None:
                            yi, ki, yo, ko = cc
                            if Y >= yi and Y <= gy_bot:
                                tt = (Y - yi) / max(1.0, gy_bot - yi)
                                col = [lerp(c_fill_top[i], c_fill_bot[i], tt) for i in range(3)]
                            if abs(Y - yi) / ki < th_in / 2:
                                col = list(c_in)
                            if abs(Y - yo) / ko < th_out / 2:
                                col = list(c_out)
                    r += col[0]
                    g += col[1]
                    b += col[2]
                    a += 1
            n = ss * ss
            i = (py * S + px) * 4
            if a:
                out[i:i + 4] = bytes((round(r / a), round(g / a), round(b / a), round(255 * a / n)))
    return out


def _png(S, rgba):
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgba[y * S * 4:(y + 1) * S * 4]) for y in range(S))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", S, S, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _dib(S, rgba):
    """Klassischer ICO-Eintrag (32 Bit BGRA, von unten nach oben + leere UND-Maske)."""
    import struct
    hdr = struct.pack("<IiiHHIIiiII", 40, S, S * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = []
    for y in range(S - 1, -1, -1):
        row = bytearray()
        for x in range(S):
            i = (y * S + x) * 4
            row += bytes((rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3]))
        rows.append(bytes(row))
    mask = bytes(((S + 31) // 32) * 4 * S)
    return hdr + b"".join(rows) + mask


def build_ico(sizes=(16, 20, 24, 32, 40, 48, 64, 128, 256)):
    import struct
    images = []
    for S in sizes:
        px = render_app_icon(S)
        images.append((S, _png(S, px) if S >= 256 else _dib(S, px)))
    head = struct.pack("<HHH", 0, 1, len(images))
    off = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for S, data in images:
        entries += struct.pack("<BBBBHHII", S % 256, S % 256, 0, 0, 1, 32, len(data), off)
        blobs += data
        off += len(data)
    return head + entries + blobs


def app_icon_path():
    """Legt das Programmsymbol einmalig lokal ab (%APPDATA%\\FTG\\ftg.ico)."""
    d = local_dir()
    path = os.path.join(d, "ftg.ico")
    mark = os.path.join(d, "ftg.ico.version")
    try:
        with open(mark, encoding="utf-8") as f:
            ok = f.read().strip() == str(ICON_VERSION) and os.path.exists(path)
    except OSError:
        ok = False
    if not ok:
        try:
            os.makedirs(d, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(build_ico())
            os.replace(tmp, path)
            with open(mark, "w", encoding="utf-8") as f:
                f.write(str(ICON_VERSION))
        except OSError:
            return path if os.path.exists(path) else None
    return path


def apply_app_icon(root):
    """Programmsymbol fuer Fenster, Taskleiste, Alt+Tab (und alle Dialoge)."""
    try:
        if sys.platform == "win32":
            p = app_icon_path()
            if p:
                root.iconbitmap(default=p)
        else:
            import base64
            img = tk.PhotoImage(data=base64.b64encode(_png(48, render_app_icon(48))))
            root.iconphoto(True, img)
            root._ftg_icon = img            # Referenz halten
    except (tk.TclError, OSError):
        pass


# ---------------------------------------------------------------- Tray-Symbol
def render_tray_icon(size, points, top, color_in, color_out, paused=False, error=False,
                     fill="in"):
    """Zeichnet den Mini-Live-Graphen fuer den Infobereich.

    points: Liste (In, Out) in bit/s, None = Luecke, neuester Wert zuletzt.
    Rueckgabe: Pixel als BGRA, zeilenweise von oben (fuer CreateDIBSection).
    """
    S = max(8, int(size))
    px = bytearray(S * S * 4)

    def rgb(c):
        try:
            return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        except (ValueError, TypeError):
            return 200, 200, 200

    def put(x, y, col, a=255):
        i = (y * S + x) * 4
        px[i:i + 4] = bytes((col[2], col[1], col[0], a))

    bg, frame = rgb(BG), rgb(blend(FG_DIM, BG, 0.30))
    c_in, c_out = rgb(color_in), rgb(color_out)
    f_in, f_out = rgb(blend(color_in, BG, 0.60)), rgb(blend(color_out, BG, 0.60))
    f_mix = rgb(blend(blend(color_in, color_out, 0.5), BG, 0.70))
    fill_in, fill_out = fill in ("in", "both"), fill in ("out", "both")

    # Hintergrund, Rahmen, abgerundete Ecken
    rad = 1 if S < 24 else 2
    for y in range(S):
        for x in range(S):
            cx, cy = min(x, S - 1 - x), min(y, S - 1 - y)
            if cx + cy < rad:
                continue                                    # durchsichtig
            put(x, y, frame if cx == 0 or cy == 0 else bg)

    # Graph: eine Spalte pro Messwert, rechts = jetzt
    x0, y0, x1, y1 = 1, 1, S - 2, S - 2
    gw, gh = x1 - x0 + 1, y1 - y0 + 1
    top = top or 1
    pts = list(points)[-gw:]
    start = x0 + gw - len(pts)

    def ypos(v):
        return y1 - int(round(min(max(v, 0), top) / top * (gh - 1)))

    thick = 1 if S < 24 else 2

    def yfill(v):
        y = ypos(v)
        if y == y1 and v > top * 0.002:
            y = y1 - 1                                       # kleine Last trotzdem sichtbar
        return y

    prev = {}
    for k, p in enumerate(pts):
        x = start + k
        if p is None or p[0] is None or p[1] is None:
            prev = {}
            continue
        vin, vout = p
        yi = yfill(vin) if fill_in else ypos(vin)
        yo = yfill(vout) if fill_out else ypos(vout)
        if fill_in and vin > 0:
            for y in range(yi, y1 + 1):
                put(x, y, f_in)
        if fill_out and vout > 0:
            for y in range(yo, y1 + 1):
                put(x, y, f_out)
        if fill_in and fill_out and vin > 0 and vout > 0:
            for y in range(max(yi, yo), y1 + 1):
                put(x, y, f_mix)
        if fill_in and vin > 0:
            put(x, yi, c_in)
        if fill_out and vout > 0:
            put(x, yo, c_out)
        # nicht gefuellte Reihen als durchgehende Linie obendrauf
        for key, filled, yv, col in (("i", fill_in, yi, c_in), ("o", fill_out, yo, c_out)):
            if filled:
                continue
            pv = prev.get(key)
            lo, hi = (yv, yv) if pv is None else (min(pv, yv), max(pv, yv))
            for y in range(max(y0, lo - thick + 1), hi + 1):
                put(x, y, col)
            prev[key] = yv

    if paused:
        for y in range(y0, y1 + 1):                          # abdunkeln
            for x in range(x0, x1 + 1):
                i = (y * S + x) * 4
                for c in range(3):
                    px[i + c] = (px[i + c] + bg[2 - c]) // 2
        bw, bh = max(2, S // 8), max(4, S // 2)
        by = (S - bh) // 2
        for bx in (S // 2 - bw - max(1, S // 16), S // 2 + max(1, S // 16)):
            for y in range(by, by + bh):
                for x in range(bx, bx + bw):
                    put(x, y, rgb(FG))
    if error:
        d = max(3, S // 5)
        for y in range(1, 1 + d):
            for x in range(S - 1 - d, S - 1):
                put(x, y, rgb(ERR))
    return px


_WIN = None
_TRAY = {"obj": None, "hwnd": None, "proc": None}


def tray_supported():
    return sys.platform == "win32"


def win32():
    """Win32-Funktionen mit festen Typen (wichtig unter 64 Bit). Nur Windows."""
    global _WIN
    if _WIN is not None:
        return _WIN
    c = ctypes
    HANDLE = c.c_void_p
    DWORD, LONG, UINT, WORD, BOOL = c.c_uint32, c.c_int32, c.c_uint32, c.c_uint16, c.c_int32
    WPARAM, LPARAM, LRESULT = c.c_size_t, c.c_ssize_t, c.c_ssize_t
    WCHAR = c.c_wchar

    class W:
        pass

    w = W()
    w.WNDPROC = c.WINFUNCTYPE(LRESULT, HANDLE, UINT, WPARAM, LPARAM)
    w.ENUMPROC = c.WINFUNCTYPE(BOOL, HANDLE, LPARAM)

    class WNDCLASSW(c.Structure):
        _fields_ = [("style", UINT), ("lpfnWndProc", w.WNDPROC), ("cbClsExtra", c.c_int),
                    ("cbWndExtra", c.c_int), ("hInstance", HANDLE), ("hIcon", HANDLE),
                    ("hCursor", HANDLE), ("hbrBackground", HANDLE),
                    ("lpszMenuName", c.c_wchar_p), ("lpszClassName", c.c_wchar_p)]

    class NOTIFYICONDATAW(c.Structure):
        _fields_ = [("cbSize", DWORD), ("hWnd", HANDLE), ("uID", UINT), ("uFlags", UINT),
                    ("uCallbackMessage", UINT), ("hIcon", HANDLE), ("szTip", WCHAR * 128),
                    ("dwState", DWORD), ("dwStateMask", DWORD), ("szInfo", WCHAR * 256),
                    ("uVersion", UINT), ("szInfoTitle", WCHAR * 64), ("dwInfoFlags", DWORD),
                    ("guidItem", c.c_ubyte * 16), ("hBalloonIcon", HANDLE)]

    class ICONINFO(c.Structure):
        _fields_ = [("fIcon", BOOL), ("xHotspot", DWORD), ("yHotspot", DWORD),
                    ("hbmMask", HANDLE), ("hbmColor", HANDLE)]

    class BITMAPINFOHEADER(c.Structure):
        _fields_ = [("biSize", DWORD), ("biWidth", LONG), ("biHeight", LONG),
                    ("biPlanes", WORD), ("biBitCount", WORD), ("biCompression", DWORD),
                    ("biSizeImage", DWORD), ("biXPelsPerMeter", LONG), ("biYPelsPerMeter", LONG),
                    ("biClrUsed", DWORD), ("biClrImportant", DWORD)]

    class BITMAPINFO(c.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 1)]

    class POINT(c.Structure):
        _fields_ = [("x", LONG), ("y", LONG)]

    w.WNDCLASSW, w.NOTIFYICONDATAW, w.ICONINFO = WNDCLASSW, NOTIFYICONDATAW, ICONINFO
    w.BITMAPINFO, w.POINT = BITMAPINFO, POINT

    u = c.WinDLL("user32", use_last_error=True)
    g = c.WinDLL("gdi32", use_last_error=True)
    s = c.WinDLL("shell32", use_last_error=True)
    k = c.WinDLL("kernel32", use_last_error=True)

    def fn(dll, name, res, *args):
        f = getattr(dll, name)
        f.restype, f.argtypes = res, list(args)
        setattr(w, name, f)

    P = c.POINTER
    fn(u, "DefWindowProcW", LRESULT, HANDLE, UINT, WPARAM, LPARAM)
    fn(u, "RegisterClassW", WORD, P(WNDCLASSW))
    fn(u, "CreateWindowExW", HANDLE, DWORD, c.c_wchar_p, c.c_wchar_p, DWORD, c.c_int, c.c_int,
       c.c_int, c.c_int, HANDLE, HANDLE, HANDLE, c.c_void_p)
    fn(u, "RegisterWindowMessageW", UINT, c.c_wchar_p)
    fn(u, "SetForegroundWindow", BOOL, HANDLE)
    fn(u, "PostMessageW", BOOL, HANDLE, UINT, WPARAM, LPARAM)
    fn(u, "GetCursorPos", BOOL, P(POINT))
    fn(u, "GetSystemMetrics", c.c_int, c.c_int)
    fn(u, "GetParent", HANDLE, HANDLE)
    fn(u, "GetWindowLongW", LONG, HANDLE, c.c_int)
    fn(u, "SetWindowLongW", LONG, HANDLE, c.c_int, LONG)
    if hasattr(u, "SetWindowLongPtrW"):
        fn(u, "SetWindowLongPtrW", c.c_ssize_t, HANDLE, c.c_int, c.c_ssize_t)
        fn(u, "GetWindowLongPtrW", c.c_ssize_t, HANDLE, c.c_int)
    else:                                                      # 32-Bit-Python
        w.SetWindowLongPtrW = lambda h, i, v: w.SetWindowLongW(h, i, v or 0)
        w.GetWindowLongPtrW = w.GetWindowLongW
    fn(u, "EnumThreadWindows", BOOL, DWORD, w.ENUMPROC, LPARAM)
    fn(u, "GetWindow", HANDLE, HANDLE, UINT)

    class RECT(c.Structure):
        _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]

    class MONITORINFO(c.Structure):
        _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", DWORD)]

    w.RECT, w.MONITORINFO = RECT, MONITORINFO
    fn(u, "MonitorFromRect", HANDLE, P(RECT), DWORD)
    fn(u, "GetMonitorInfoW", BOOL, HANDLE, P(MONITORINFO))
    fn(u, "SetWindowPos", BOOL, HANDLE, HANDLE, c.c_int, c.c_int, c.c_int, c.c_int, UINT)
    fn(u, "GetClassNameW", c.c_int, HANDLE, c.c_wchar_p, c.c_int)
    fn(u, "GetDC", HANDLE, HANDLE)
    fn(u, "ReleaseDC", c.c_int, HANDLE, HANDLE)
    fn(u, "CreateIconIndirect", HANDLE, P(ICONINFO))
    fn(u, "DestroyIcon", BOOL, HANDLE)
    fn(g, "CreateDIBSection", HANDLE, HANDLE, P(BITMAPINFO), UINT, P(c.c_void_p), HANDLE, DWORD)
    fn(g, "CreateBitmap", HANDLE, c.c_int, c.c_int, UINT, UINT, c.c_void_p)
    fn(g, "DeleteObject", BOOL, HANDLE)
    fn(s, "Shell_NotifyIconW", BOOL, DWORD, P(NOTIFYICONDATAW))
    fn(k, "GetModuleHandleW", HANDLE, c.c_wchar_p)
    fn(k, "GetCurrentThreadId", DWORD)
    _WIN = w
    return w


def _tray_wndproc(hwnd, msg, wp, lp):
    # Laeuft innerhalb der Tk-Nachrichtenschleife: hier KEIN tkinter aufrufen,
    # nur Win32 und reines Python. Alles andere geht ueber die Warteschlange.
    t = _TRAY["obj"]
    try:
        if t is not None and hwnd == _TRAY["hwnd"]:
            r = t.handle(msg, wp, lp)
            if r is not None:
                return r
    except Exception as e:
        if t is not None:
            write_log(t.app.cfg_path, f"Tray-Fehler: {type(e).__name__}: {e}")
    return win32().DefWindowProcW(hwnd, msg, wp, lp)


def tray_window():
    """Unsichtbares Fenster fuer Tray-Nachrichten, einmal pro Prozess.
    Dient zugleich als Besitzer des Hauptfensters (= kein Taskleisten-Knopf)."""
    if _TRAY["hwnd"]:
        return _TRAY["hwnd"]
    w = win32()
    _TRAY["proc"] = w.WNDPROC(_tray_wndproc)                # Referenz halten!
    hinst = w.GetModuleHandleW(None)
    wc = w.WNDCLASSW()
    wc.lpfnWndProc = _TRAY["proc"]
    wc.hInstance = hinst
    wc.lpszClassName = "FTGTrayWindow"
    w.RegisterClassW(ctypes.byref(wc))
    hwnd = w.CreateWindowExW(0, "FTGTrayWindow", "FTG Tray", 0, 0, 0, 0, 0,
                             None, None, hinst, None)
    if not hwnd:
        raise OSError(f"Tray-Fenster nicht erstellt (Fehler {ctypes.get_last_error()})")
    _TRAY["hwnd"] = hwnd
    return hwnd


class TrayIcon:
    WM_TRAY = 0x8000 + 1                 # WM_APP + 1
    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4

    def __init__(self, app):
        self.app = app
        self.w = win32()
        self.q = queue.Queue()
        self.hwnd = tray_window()
        _TRAY["obj"] = self
        self.size = self.w.GetSystemMetrics(49) or 16          # SM_CXSMICON, DPI-skaliert
        self.msg_created = self.w.RegisterWindowMessageW("TaskbarCreated")
        self.hicon = None
        self.added = False
        self.tip = ""
        self._skip_up = False
        self._menu_owner = None

    # ------------------------------------------------ Symbol
    def _nid(self, flags):
        n = self.w.NOTIFYICONDATAW()
        n.cbSize = ctypes.sizeof(n)
        n.hWnd = self.hwnd
        n.uID = 1
        n.uFlags = flags
        n.uCallbackMessage = self.WM_TRAY
        n.hIcon = self.hicon
        n.szTip = self.tip[:127]
        return n

    def _make_icon(self, pixels):
        w, S = self.w, self.size
        bmi = w.BITMAPINFO()
        h = bmi.bmiHeader
        h.biSize = ctypes.sizeof(h)
        h.biWidth, h.biHeight = S, -S                         # von oben nach unten
        h.biPlanes, h.biBitCount = 1, 32
        bits = ctypes.c_void_p()
        hdc = w.GetDC(None)
        try:
            color = w.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        finally:
            w.ReleaseDC(None, hdc)
        if not color or not bits.value:
            raise OSError("CreateDIBSection fehlgeschlagen")
        ctypes.memmove(bits.value, bytes(pixels), S * S * 4)
        mask_bits = ctypes.create_string_buffer(((S + 15) // 16) * 2 * S)
        mask = w.CreateBitmap(S, S, 1, 1, mask_bits)
        ii = w.ICONINFO(1, 0, 0, mask, color)
        icon = w.CreateIconIndirect(ctypes.byref(ii))
        w.DeleteObject(mask)
        w.DeleteObject(color)
        if not icon:
            raise OSError("CreateIconIndirect fehlgeschlagen")
        return icon

    def refresh(self, pixels, tip):
        """Neues Bild und Tooltip setzen (fuegt das Symbol bei Bedarf hinzu)."""
        old = self.hicon
        self.hicon = self._make_icon(pixels)
        self.tip = tip
        flags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        ok = False
        if self.added:
            ok = self.w.Shell_NotifyIconW(self.NIM_MODIFY, ctypes.byref(self._nid(flags)))
        if not ok:
            ok = self.w.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(self._nid(flags)))
        self.added = bool(ok)
        if old:
            self.w.DestroyIcon(old)
        return self.added

    def remove(self):
        if self.added:
            self.w.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(self._nid(0)))
        self.added = False
        if self.hicon:
            self.w.DestroyIcon(self.hicon)
            self.hicon = None

    # ------------------------------------------------ Nachrichten (Tk-frei!)
    def handle(self, msg, wp, lp):
        if msg == self.WM_TRAY:
            ev = lp & 0xFFFF
            if ev == 0x0202:                                   # WM_LBUTTONUP
                if self._skip_up:
                    self._skip_up = False
                else:
                    self.w.SetForegroundWindow(self.hwnd)
                    self.q.put(("toggle",))
            elif ev == 0x0203:                                 # WM_LBUTTONDBLCLK
                self._skip_up = True
                self.q.put(("show",))
            elif ev == 0x0205:                                 # WM_RBUTTONUP
                pt = self.w.POINT()
                self.w.GetCursorPos(ctypes.byref(pt))
                self.w.SetForegroundWindow(self.menu_owner())
                self.q.put(("menu", pt.x, pt.y))
            return 0
        if msg == self.msg_created and msg:                    # Explorer neu gestartet
            self.added = False
            self.q.put(("readd",))
            return 0
        if msg == 0x0011:                                      # WM_QUERYENDSESSION
            return 1
        if msg == 0x0016 and wp:                               # WM_ENDSESSION
            self.app.save_quiet("Windows wird beendet")
            self.remove()
            return 0
        return None

    def menu_owner(self):
        """Tk-internes Fenster, dem das Popup-Menue gehoert. Es muss im
        Vordergrund sein, sonst schliesst das Menue bei Klick daneben nicht."""
        if self._menu_owner:
            return self._menu_owner
        found = []

        def cb(h, _):
            buf = ctypes.create_unicode_buffer(64)
            self.w.GetClassNameW(h, buf, 64)
            if buf.value == "MenuWindowClass":
                found.append(h)
                return False
            return True

        try:
            self.w.EnumThreadWindows(self.w.GetCurrentThreadId(), self.w.ENUMPROC(cb), 0)
        except Exception:
            pass
        self._menu_owner = found[0] if found else self.hwnd
        return self._menu_owner

    def after_menu(self):
        self.w.PostMessageW(self.menu_owner(), 0, 0, 0)          # WM_NULL


def taskbar_style_ok(win, owner, borderless):
    """Ist der Taskleisten-Knopf (im Tray-Modus) wirklich ausgeblendet?
    Tk ueberschreibt den erweiterten Fensterstil in manchen Faellen."""
    w = win32()
    hwnd = w.GetParent(win.winfo_id())
    if not hwnd:
        return True                                          # noch nie angezeigt
    ex = w.GetWindowLongW(hwnd, -20) & 0xFFFFFFFF
    if ex & 0x00040000:                                      # WS_EX_APPWINDOW
        return False
    if borderless:
        return bool(ex & 0x00000080)                         # WS_EX_TOOLWINDOW
    return (w.GetWindowLongPtrW(hwnd, -8) or 0) == (owner or 0)


def work_area(win, rect):
    """Arbeitsbereich (ohne Taskleiste) des Monitors, der rect=(l, t, r, b) am
    naechsten liegt: (l, t, r, b). Ausserhalb von Windows: ganzer Bildschirm."""
    if sys.platform == "win32":
        try:
            w = win32()
            rc = w.RECT(*[int(v) for v in rect])
            mon = w.MonitorFromRect(ctypes.byref(rc), 2)          # MONITOR_DEFAULTTONEAREST
            mi = w.MONITORINFO()
            mi.cbSize = ctypes.sizeof(mi)
            if mon and w.GetMonitorInfoW(mon, ctypes.byref(mi)):
                r = mi.rcWork
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()


def fit_rect(x, y, w, h, area):
    """Position so verschieben, dass w x h ganz in area liegt (links/oben hat Vorrang)."""
    l, t, r, b = area
    x = max(l, min(x, r - w))
    y = max(t, min(y, b - h))
    return x, y


def set_taskbar_button(win, visible, owner, borderless):
    """Taskleisten-Knopf ein-/ausblenden.

    Mit Titelleiste: Fenster bekommt einen unsichtbaren Besitzer (dann kein
    Knopf, kein Alt+Tab). Ohne Titelleiste: Werkzeugfenster-Stil.
    """
    if sys.platform != "win32":
        return
    w = win32()
    win.update_idletasks()
    hwnd = w.GetParent(win.winfo_id())
    ex = w.GetWindowLongW(hwnd, -20)                            # GWL_EXSTYLE
    TOOL, APP = 0x00000080, 0x00040000
    if visible:
        w.SetWindowLongPtrW(hwnd, -8, 0)                         # GWLP_HWNDPARENT
        if borderless:
            ex = (ex & ~TOOL) | APP
    else:
        ex &= ~APP
        if borderless:
            ex |= TOOL
        else:
            w.SetWindowLongPtrW(hwnd, -8, owner or 0)
    w.SetWindowLongW(hwnd, -20, ex)
    if win.state() != "withdrawn":
        win.withdraw()
        win.after(10, win.deiconify)


def dark_titlebar(win):
    """Dunkle Titelleiste unter Windows 10/11."""
    if sys.platform != "win32":
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def load_config(path):
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    if cfg.pop("bg_transparent", False):          # alte Einstellung -> 0 %
        cfg["bg_alpha"] = 0
    return cfg


def bg_supported():
    """Durchsichtiger Hintergrund braucht -transparentcolor (nur Windows)."""
    return sys.platform == "win32"


def save_config(path, cfg):
    """Speichert atomar. Gibt None oder eine Fehlermeldung zurueck."""
    try:
        if not ensure_dir(os.path.dirname(path)):
            return T("Konfiguration nicht gespeichert: Ordner nicht erreichbar ({d})", d=os.path.dirname(path))
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return None
    except OSError as e:
        return T("Konfiguration nicht gespeichert: {e}", e=e)


def real_path(path):
    """Tatsaechlicher Pfad auf der Platte.

    Python aus dem Microsoft Store leitet Schreibzugriffe auf %APPDATA%
    unbemerkt in einen privaten Ordner unter %LOCALAPPDATA%\\Packages um.
    realpath() liefert dort den echten Speicherort.
    """
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def ensure_dir(d):
    """Legt nur den lokalen Standardordner selbst an – fremde Ordner
    (Netzlaufwerk) muessen existieren, sonst gilt er als nicht erreichbar."""
    if os.path.isdir(d):
        return True
    if os.path.normcase(os.path.abspath(d)) == os.path.normcase(os.path.abspath(local_dir())):
        os.makedirs(d, exist_ok=True)
        return True
    return False


def acquire_lock(cfg_path):
    """Sperrt die Konfiguration fuer dieses Fenster. None = belegt/nicht erreichbar."""
    try:
        if not ensure_dir(os.path.dirname(cfg_path)):
            return None
        f = open(cfg_path + ".lock", "a+")
    except OSError:
        return None
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def lock_problem(cfg_path):
    d = os.path.dirname(cfg_path)
    if not os.path.isdir(d):
        return T("Konfigurationsordner nicht erreichbar: {d} – Rechtsklick → "
                 "Konfigurationsordner wählen", d=d)
    return T("Diese Konfiguration ist schon in einem anderen Fenster offen – "
             "hier wird nichts gespeichert")


def write_log(cfg_path, text):
    try:
        path = os.path.join(os.path.dirname(cfg_path), LOGNAME)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} "
                    f"{os.path.basename(cfg_path)}: {text}\n")
    except OSError:
        pass


def parse_geometry(g):
    """'WxH+X+Y' -> (w, h, x, y) bzw. (w, h, None, None); None bei Unsinn."""
    import re
    m = re.fullmatch(r"\s*(\d+)x(\d+)(?:([+-]-?\d+)([+-]-?\d+))?\s*", g or "")
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if m.group(3) is None:
        return w, h, None, None
    return w, h, int(m.group(3).replace("+-", "-")), int(m.group(4).replace("+-", "-"))


def config_name(path):
    n = os.path.basename(path)
    return n[:-5] if n.lower().endswith(".json") else n


def valid_name(name):
    import re
    return bool(re.fullmatch(r"[\w\- ]{1,40}", name)) and name.strip() == name


def list_configs(d):
    try:
        return sorted((config_name(f) for f in os.listdir(d)
                       if f.lower().endswith(".json") and f.lower() != ORDER_FILE),
                      key=str.lower)
    except OSError:
        return []


ORDER_FILE = "ftg-auftrag.json"


def post_order(d, targets):
    """Auftrag an andere Fenster: {name_klein: {"geometry"|"size": ...}}."""
    data = {"id": f"{time.time():.6f}-{os.getpid()}", "time": time.time(), "targets": targets}
    return save_config(os.path.join(d, ORDER_FILE), data)


def read_order(d):
    """(id, Zeit, Ziele) des letzten Auftrags oder (None, 0, {})."""
    try:
        with open(os.path.join(d, ORDER_FILE), encoding="utf-8") as f:
            o = json.load(f)
        return o.get("id"), float(o.get("time", 0)), dict(o.get("targets") or {})
    except (OSError, ValueError, TypeError, AttributeError):
        return None, 0.0, {}


def config_in_use(path):
    lk = acquire_lock(path)
    if lk is None:
        return True
    lk.close()
    return False


def launch_instance(name):
    import subprocess
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, name]
    else:
        cmd = [sys.executable, os.path.abspath(__file__), name]
    flags = 0x00000008 if sys.platform == "win32" else 0   # DETACHED_PROCESS
    subprocess.Popen(cmd, close_fds=True, creationflags=flags)


def local_dir():
    """Lokaler Ordner – hier liegt immer settings.cfg (Wahl des Konfigurationsordners)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "FTG")
    return os.path.join(os.path.expanduser("~"), ".config", "ftg")


def settings_path():
    return os.path.join(local_dir(), "settings.cfg")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    return save_config(settings_path(), data)


def config_dir():
    return load_settings().get("config_dir") or local_dir()


def resolve_config_path(arg):
    d = config_dir()
    if not arg:
        return os.path.join(d, "default.json")
    if os.path.isabs(arg) or os.sep in arg or "/" in arg:
        return arg
    if not arg.lower().endswith(".json"):
        arg += ".json"
    return os.path.join(d, arg)


# ====================================================================
#  Hauptfenster
# ====================================================================
class App:
    def __init__(self, root, cfg_path):
        self.root = root
        self.cfg_path = cfg_path
        self.cfg = load_config(cfg_path)
        self._lock = acquire_lock(cfg_path)
        self.readonly = self._lock is None
        self.readonly_reason = lock_problem(cfg_path) if self.readonly else ""
        write_log(cfg_path, f"Start v{VERSION}" + (" (gesperrt, nur Ansicht)" if self.readonly else "")
                  + f", host={self.cfg['host']!r}")
        self.q = queue.Queue()
        self.gen = 0
        self.poller = None
        self.paused = False
        self.error = ""
        self.info = ""
        self.oids = []
        self.flash = ""
        self.frozen = None            # Anzeige-Stand waehrend der Pause
        self.offset = 0.0             # zurueckgeblaettert (Sekunden vor "jetzt")
        self.auto_paused = False      # Pause kam vom Zurueckblaettern
        self._hover = None
        self._save_job = None
        self._t0 = time.time()
        self._last_size = None        # fuer die Groessenanzeige
        self._size_hint = ""
        self._size_job = None
        self._order_seen = read_order(os.path.dirname(cfg_path))[0]
        self._order_mtime = None
        self.under = None             # Unterlage fuer halbdurchsichtigen Hintergrund
        self._under_geo = None
        self.bg_on = False
        self._look = (100.0, 100.0)
        self.tray = None
        self.data = deque(maxlen=self.maxpoints())
        self._build_ui()
        self.apply_look()
        self.flash = f"{APP} Version {VERSION}"          # beim Start kurz anzeigen
        self.root.after(5000, self._end_flash)
        self.root.after(100, self.process_queue)
        self.root.after(500, self._hover_poll)
        if self.readonly:
            self.error = self.readonly_reason
            self.update_labels()
        if self.cfg["host"] and self.cfg["ifindex"]:
            self.start()
        else:
            self.root.after(300, self.open_settings)

    # ---------------------------------------------------------- Aufbau
    def _build_ui(self):
        r = self.root
        r.configure(bg=BG)
        r.geometry(self.cfg.get("geometry") or DEFAULTS["geometry"])
        r.minsize(360, 170)
        r.attributes("-topmost", bool(self.cfg["topmost"]))

        bar = tk.Frame(r, bg=PANEL, padx=10, pady=5)
        bar.pack(side="bottom", fill="x")
        self.bar = bar
        self.canvas = tk.Canvas(r, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.lbl_in = tk.Label(bar, bg=PANEL, fg=self.cfg["color_in"], font=FONT_MONO, anchor="w")
        self.lbl_out = tk.Label(bar, bg=PANEL, fg=self.cfg["color_out"], font=FONT_MONO, anchor="w")
        self.lbl_state = tk.Label(bar, bg=PANEL, fg=FG_DIM, font=FONT, anchor="e", justify="right")
        self.lbl_in.grid(row=0, column=0, sticky="w")
        self.lbl_out.grid(row=1, column=0, sticky="w")
        self.lbl_state.grid(row=0, column=1, rowspan=2, sticky="e")
        bar.columnconfigure(0, weight=1)

        self.var_top = tk.BooleanVar(value=bool(self.cfg["topmost"]))
        self.menu = tk.Menu(r, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT,
                            activeforeground="white", bd=0, font=FONT,
                            postcommand=self.fill_main_menu)
        # Feste erste Zeile (nur im Tray-Modus aktiv). Frueher wurde sie beim ersten
        # Aufklappen eingefuegt – unter Windows vertauschte das die Untermenues
        # ("Weiteres Fenster öffnen" lud stattdessen die Konfiguration).
        self.menu.add_command(label=T("Fenster ausblenden"), command=self.toggle_window, state="disabled")
        self.menu.add_separator()
        self.menu.add_command(label=T("Einstellungen …"), command=self.open_settings)
        self.menu.add_command(label=T("Pause"), command=self.toggle_pause, accelerator=T("Pause-Taste"))
        self.menu.add_command(label=T("Statistik zurücksetzen"), command=self.clear)
        self.var_window = tk.IntVar(value=int(float(self.cfg["window"])))
        self.win_menu = tk.Menu(self.menu, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT,
                                activeforeground="white", bd=0, font=FONT,
                                postcommand=self.fill_window_menu)
        self.menu.add_cascade(label=T("Zeitraum"), menu=self.win_menu)
        self.var_fill = tk.StringVar(value=self.cfg["fill"])
        fm = tk.Menu(self.menu, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT,
                     activeforeground="white", bd=0, font=FONT)
        for val, txt in FILL_MODES:
            fm.add_radiobutton(label=T(txt), value=val, variable=self.var_fill,
                               command=self.set_fill_from_menu, selectcolor=FG)
        self.menu.add_cascade(label=T("Füllung"), menu=fm)
        self.menu.add_checkbutton(label=T("Immer im Vordergrund"), variable=self.var_top,
                                  command=self.toggle_topmost, selectcolor=FG)
        self.var_bl = tk.BooleanVar(value=bool(self.cfg["borderless"]))
        self.menu.add_checkbutton(label=T("Ohne Titelleiste"), variable=self.var_bl,
                                  command=self.toggle_borderless, selectcolor=FG)
        self.var_tray = tk.BooleanVar(value=bool(self.cfg["tray"]))
        self.menu.add_checkbutton(label=T("Nur im Infobereich (Tray)"), variable=self.var_tray,
                                  command=self.toggle_tray, selectcolor=FG,
                                  state="normal" if tray_supported() else "disabled")
        self.win_arr_menu = tk.Menu(self.menu, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT,
                                    activeforeground="white", bd=0, font=FONT,
                                    disabledforeground=FG_DIM, postcommand=self.fill_arrange_menu)
        self.menu.add_cascade(label=T("Fenster anordnen"), menu=self.win_arr_menu)
        self.size_menu = tk.Menu(self.menu, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT,
                                 activeforeground="white", bd=0, font=FONT,
                                 disabledforeground=FG_DIM, postcommand=self.fill_size_menu)
        self.menu.add_cascade(label=T("Fenstergröße übernehmen für"), menu=self.size_menu)
        self.menu.add_separator()
        self.open_menu = tk.Menu(self.menu, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT,
                                 activeforeground="white", bd=0, font=FONT,
                                 postcommand=self.fill_open_menu)
        self.menu.add_cascade(label=T("Weiteres Fenster öffnen"), menu=self.open_menu)
        # Trennlinie: Bleibt der Zeiger auf dem Weg ins Untermenue kurz auf dem
        # Nachbarn stehen, oeffnet Windows dessen Untermenue – direkt untereinander
        # und mit gleichen Namen war das nicht zu unterscheiden.
        self.menu.add_separator()
        self.load_menu = tk.Menu(self.menu, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT,
                                 activeforeground="white", bd=0, font=FONT,
                                 postcommand=self.fill_load_menu)
        self.menu.add_cascade(label=T("Konfiguration in diesem Fenster laden"), menu=self.load_menu)
        self.menu.add_separator()
        # Gespeichert wird ohnehin bei jeder Aenderung; hier gibt es Sicherungskopien im
        # Unterordner "Backup" des Konfigurationsordners, um versehentliche Aenderungen
        # rueckgaengig machen zu koennen.
        self.menu.add_command(label=T("Sicherungskopie speichern"), command=self.make_backup)
        self.backup_menu = tk.Menu(self.menu, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT,
                                   activeforeground="white", bd=0, font=FONT,
                                   disabledforeground=FG_DIM, postcommand=self.fill_backup_menu)
        self.menu.add_cascade(label=T("Sicherungskopie wiederherstellen"), menu=self.backup_menu)
        self.menu.add_separator()
        self.dir_menu = tk.Menu(self.menu, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT,
                                activeforeground="white", bd=0, font=FONT,
                                disabledforeground=FG_DIM, postcommand=self.fill_dir_menu)
        self.menu.add_cascade(label=T("Konfigurationsordner"), menu=self.dir_menu)
        self.lnk_menu = tk.Menu(self.menu, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT,
                                activeforeground="white", bd=0, font=FONT,
                                disabledforeground=FG_DIM, postcommand=self.fill_lnk_menu)
        self.menu.add_cascade(label=T("Verknüpfung"), menu=self.lnk_menu)
        self.menu.add_separator()
        self.menu.add_command(label=T("Beenden"), command=self.on_close)

        for w in (self.canvas, bar, self.lbl_in, self.lbl_out, self.lbl_state):
            w.bind("<Button-3>", self.show_menu)
            w.bind("<Double-Button-1>", lambda e: self.open_settings())
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.bind_wheel(self.canvas)
        self.bind_side_buttons(r)
        r.bind("<End>", lambda e: self.go_live())
        r.bind("<plus>", lambda e: self.zoom(-1))
        r.bind("<KP_Add>", lambda e: self.zoom(-1))
        r.bind("<minus>", lambda e: self.zoom(1))
        r.bind("<KP_Subtract>", lambda e: self.zoom(1))
        r.bind("<Left>", lambda e: self.scroll(1))
        r.bind("<Right>", lambda e: self.scroll(-1))
        r.protocol("WM_DELETE_WINDOW", self.on_window_close)
        r.bind("<Pause>", lambda e: self.toggle_pause())
        r.bind("<Configure>", self._root_configure, add="+")
        r.bind("<Unmap>", self._root_unmap, add="+")

        # Rahmenlos: verschieben per Ziehen, Groesse per Griff unten rechts
        self.grip = tk.Label(bar, text="◢", bg=PANEL, fg=GRID_STRONG, font=FONT_SMALL,
                             cursor="size_nw_se" if sys.platform == "win32" else "bottom_right_corner")
        self.grip.bind("<ButtonPress-1>", self._resize_start)
        self.grip.bind("<B1-Motion>", self._resize_move)
        for w in (self.canvas, bar, self.lbl_in, self.lbl_out, self.lbl_state):
            self.bind_move(w)
        self.update_title()
        self.update_labels()

    # ---------------------------------------------------------- Steuerung
    def maxpoints(self):
        """Groesse des Hintergrundspeichers (mind. HISTORY Sekunden)."""
        keep = max(HISTORY, float(self.cfg["window"]))
        return max(2, int(round(keep / float(self.cfg["interval"]))) + 1)

    def start(self):
        self.stop()
        self.gen += 1
        self.error = ""
        self.info = ""
        self.poller = Poller(self.cfg, self.q, self.gen)
        self.poller.start()
        self.update_labels()

    def stop(self):
        if self.poller:
            self.poller.stop()
            self.poller = None

    def toggle_pause(self, auto=False):
        """Pause friert nur die Anzeige ein – gemessen wird weiter; beim
        Fortsetzen wird der Zeitraum der Pause nachgezeichnet."""
        self.paused = not self.paused
        self.auto_paused = auto and self.paused
        if not self.paused:
            self.offset = 0.0
        self._set_pause_label()
        self.frozen = list(self.data) if self.paused else None
        self.update_labels()
        self.redraw()
        if self.tray_active():
            self.update_tray()

    # ---------------------------------------------------------- Rahmenlos
    def apply_borderless(self):
        bl = bool(self.cfg["borderless"])
        r = self.root
        # Vor dem ersten Anzeigen liefert Tk "1x1" – dann die gespeicherte Groesse nehmen
        if r.winfo_ismapped():
            geo = r.geometry()
        else:
            geo = self.cfg.get("geometry") or DEFAULTS["geometry"]
        r.overrideredirect(bl)
        r.configure(highlightthickness=1 if bl else 0, highlightbackground=GRID_STRONG,
                    highlightcolor=GRID_STRONG)
        if bl:
            self.grip.grid(row=1, column=2, sticky="se", padx=(6, 0))
        else:
            self.grip.grid_remove()
            dark_titlebar(r)
        r.geometry(geo)
        self.apply_tray(force=True)

    def toggle_borderless(self):
        self.cfg["borderless"] = self.var_bl.get()
        self.apply_borderless()
        self.save()

    def bind_wheel(self, w):
        """Mausrad = zurueck-/vorblaettern, Shift+Mausrad = Zeitraum."""
        w.bind("<MouseWheel>", lambda e: self.scroll(1 if e.delta > 0 else -1))
        w.bind("<Shift-MouseWheel>", lambda e: self.zoom_wheel(-1 if e.delta > 0 else 1))
        if sys.platform != "win32":
            w.bind("<Button-4>", lambda e: self.scroll(1))
            w.bind("<Button-5>", lambda e: self.scroll(-1))
            w.bind("<Shift-Button-4>", lambda e: self.zoom_wheel(-1))
            w.bind("<Shift-Button-5>", lambda e: self.zoom_wheel(1))

    def bind_side_buttons(self, w):
        """Maus-Seitentasten: Zurueck = laengerer Zeitraum, Vor = kuerzerer.
        Je nach Tk-Version und Maus-Software kommen sie verschieden an:
        als Taste 8/9 (Tk 9), als Taste 4/5 (aeltere Tk unter Windows), als
        Browser-Zurueck/Vor-Taste (VK 0xA6/0xA7) oder als Alt+Links/Rechts.
        Was ankommt, steht im ftg.log ("Maustaste …" / "Taste …")."""
        w.bind("<ButtonPress>", self._side_button, add="+")
        try:                                         # Tk 9: Taste 8/9 (intern als 12/13 gemeldet)
            w.bind("<Button-8>", lambda e: self._side("Maustaste 8 (Zurück)", 1))
            w.bind("<Button-9>", lambda e: self._side("Maustaste 9 (Vor)", -1))
        except tk.TclError:
            pass
        if sys.platform == "win32":
            w.bind("<KeyPress>", self._side_key, add="+")
            w.bind("<Alt-Left>", lambda e: self._side("Alt+Links", 1))
            w.bind("<Alt-Right>", lambda e: self._side("Alt+Rechts", -1))

    def _side(self, what, direction):
        n = getattr(self, "_side_logged", 0)
        if n < 10:                                   # nur die ersten Male protokollieren
            self._side_logged = n + 1
            write_log(self.cfg_path, f"Seitentaste erkannt: {what}")
        self.zoom(direction)
        return "break"

    def _side_button(self, e):
        num = int(getattr(e, "num", 0) or 0)
        if num in (8, 9):                            # Windows: Tk meldet 8/9 direkt
            return self._side(f"Maustaste {num}", 1 if num == 8 else -1)
        if num in (4, 5) and sys.platform == "win32":     # aeltere Tk unter Windows
            return self._side(f"Maustaste {num}", 1 if num == 4 else -1)
        if num > 3:                                  # unbekannte Taste: nur protokollieren
            n = getattr(self, "_side_logged", 0)
            if n < 10:
                self._side_logged = n + 1
                write_log(self.cfg_path, f"Maustaste {num} gedrückt (nicht belegt)")

    def _side_key(self, e):
        if e.keycode in (0xA6, 0xA7):                # VK_BROWSER_BACK / VK_BROWSER_FORWARD
            return self._side(f"Taste {e.keysym or e.keycode}", 1 if e.keycode == 0xA6 else -1)

    def bind_move(self, w):
        w.bind("<ButtonPress-1>", self._move_start, add="+")
        w.bind("<B1-Motion>", self._move, add="+")
        w.bind("<ButtonRelease-1>", self._move_end, add="+")

    def _move_start(self, e):
        # Verschieben nur mit gedrueckter Strg-Taste (kein versehentliches Verschieben)
        if not self.cfg["borderless"] or not (e.state & 0x0004):
            self._drag = None
            return
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())
        try:
            e.widget.configure(cursor="fleur")
            self._drag_widget = e.widget
        except tk.TclError:
            pass

    def _move(self, e):
        if not self.cfg["borderless"] or not getattr(self, "_drag", None):
            return
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")
        self.sync_under()

    def _move_end(self, e):
        self._drag = None
        w = getattr(self, "_drag_widget", None)
        if w is not None:
            try:
                w.configure(cursor="")
            except tk.TclError:
                pass
            self._drag_widget = None

    def _resize_start(self, e):
        self._rs = (e.x_root, e.y_root, self.root.winfo_width(), self.root.winfo_height())
        return "break"

    def _resize_move(self, e):
        x0, y0, w0, h0 = self._rs
        w = max(360, w0 + e.x_root - x0)
        h = max(170, h0 + e.y_root - y0)
        self.root.geometry(f"{w}x{h}")
        return "break"

    def toggle_topmost(self):
        self.cfg["topmost"] = self.var_top.get()
        self.root.attributes("-topmost", self.cfg["topmost"])
        if self.under is not None:
            self.under.attributes("-topmost", self.cfg["topmost"])
            self.sync_under()
        self.save()

    # ---------------------------------------------------------- Infobereich (Tray)
    def tray_active(self):
        return bool(self.tray and self.tray.added)

    def apply_tray(self, force=False):
        """Tray-Symbol und Taskleisten-Knopf passend zur Einstellung setzen."""
        want = bool(self.cfg.get("tray")) and tray_supported()
        was = self.tray_active()
        if want:
            try:
                if self.tray is None:
                    self.tray = TrayIcon(self)
                self.update_tray()
            except Exception as e:
                write_log(self.cfg_path, f"Tray nicht verfügbar: {type(e).__name__}: {e}")
                self.error = T("Infobereich nicht verfügbar: {e}", e=e)
                self.update_labels()
        elif self.tray:
            self.tray.remove()
        now = self.tray_active()
        if tray_supported() and (force or now != was):
            try:
                set_taskbar_button(self.root, not now, self.tray.hwnd if now else None,
                                   bool(self.cfg["borderless"]))
            except Exception as e:
                write_log(self.cfg_path, f"Taskleiste: {type(e).__name__}: {e}")
        if not now:
            self.show_window()

    def toggle_tray(self):
        self.cfg["tray"] = self.var_tray.get()
        self.apply_tray()
        self.save()

    def update_tray(self):
        if not self.tray:
            return
        pts = [(i, o) if i is not None else None for _, i, o in self.view_data()]
        px = render_tray_icon(self.tray.size, pts, self.scale_top(), self.cfg["color_in"],
                              self.cfg["color_out"], paused=self.paused, error=bool(self.error),
                              fill=self.cfg.get("fill", "in"))
        u = self.cfg["unit"]
        tip = f"{APP} {config_name(self.cfg_path)}"
        if self.paused:
            tip += "\n" + T("Pausiert")
        elif self.error:
            tip += "\n" + self.error[:80]
        else:
            _, _, _, _, c_in, c_out = view_stats(list(self.data)[-1:])
            tip += f"\n▼ In   {fmt_rate(c_in, u)}\n▲ Out {fmt_rate(c_out, u)}"
        self.tray.refresh(px, tip)

    def window_hidden(self):
        return self.root.state() in ("withdrawn", "iconic")

    def show_window(self):
        r = self.root
        if not self.window_hidden():
            return
        r.deiconify()
        r.lift()
        try:
            r.focus_force()
        except tk.TclError:
            pass
        self.update_labels()
        self.redraw()

    def hide_window(self):
        if self.tray_active():
            self.root.withdraw()
            self.sync_under()

    def toggle_window(self):
        if self.window_hidden():
            self.show_window()
        else:
            self.hide_window()

    def ensure_visible(self):
        """Dialoge brauchen ein sichtbares Hauptfenster."""
        self.show_window()

    def on_window_close(self):
        """X der Titelleiste: im Tray-Modus nur ausblenden."""
        if self.tray_active():
            self.hide_window()
        else:
            self.on_close()

    def _root_unmap(self, e):
        # Minimieren im Tray-Modus = ausblenden (es gibt ja keinen Taskleisten-Knopf)
        if e.widget is self.root and self.tray_active():
            self.root.after_idle(lambda: self.root.state() == "iconic" and self.root.withdraw())

    def _root_configure(self, e):
        if e.widget is self.root and self.root.state() == "normal":
            self.cfg["geometry"] = self.root.geometry()
            self.sync_under()
            size = (e.width, e.height)
            if self._last_size and size != self._last_size and time.time() - self._t0 > 1.5:
                self.show_size_hint(*size)
            self._last_size = size

    def show_size_hint(self, w, h):
        """Beim Groesse-Aendern 'B × H' mittig anzeigen, 1,5 s nach der letzten Aenderung weg."""
        self._size_hint = f"{w} × {h}"
        self.draw_size_hint()
        if self._size_job:
            self.root.after_cancel(self._size_job)
        self._size_job = self.root.after(1500, self._end_size_hint)

    def _end_size_hint(self):
        self._size_job = None
        self._size_hint = ""
        self.canvas.delete("sizehint")

    def draw_size_hint(self):
        c = self.canvas
        c.delete("sizehint")
        if not self._size_hint:
            return
        w, h = c.winfo_width(), c.winfo_height()
        t = c.create_text(w / 2, h / 2, text=self._size_hint, fill=FG,
                          font=("Segoe UI", 16, "bold"), tags="sizehint")
        x1, y1, x2, y2 = c.bbox(t)
        b = c.create_rectangle(x1 - 12, y1 - 6, x2 + 12, y2 + 6, fill=PANEL, outline=GRID_STRONG,
                               tags="sizehint")
        c.tag_lower(b, t)

    def handle_tray_event(self, ev):
        kind = ev[0]
        if kind == "toggle":
            self.toggle_window()
        elif kind == "show":
            self.show_window()
        elif kind == "readd":
            self.update_tray()
        elif kind == "menu":
            try:
                self.menu.tk_popup(ev[1], ev[2])
            finally:
                self.menu.grab_release()
                self.tray.after_menu()

    def fill_main_menu(self):
        """Erste Zeile beschriften – nur umbenennen, nie Eintraege einfuegen/loeschen."""
        if self.tray_active():
            label = T("Fenster anzeigen") if self.window_hidden() else T("Fenster ausblenden")
            self.menu.entryconfigure(0, label=label, state="normal")
        else:
            self.menu.entryconfigure(0, label=T("Fenster ausblenden (nur im Tray-Modus)"),
                                     state="disabled")

    def _set_pause_label(self):
        m = self.menu
        for i in range((m.index("end") or 0) + 1):
            if m.type(i) == "command" and m.entrycget(i, "label") in (T("Pause"), T("Fortsetzen")):
                m.entryconfigure(i, label=T("Fortsetzen") if self.paused else T("Pause"))
                return

    def save_quiet(self, why):
        """Speichern ohne Tk-Aufrufe (z. B. beim Herunterfahren von Windows)."""
        if not self.readonly:
            err = save_config(self.cfg_path, self.cfg)
            write_log(self.cfg_path, f"{why}: gespeichert -> {err or 'ok'}")

    def save(self, show=False):
        if self.readonly:
            self.error = self.readonly_reason
            self.update_labels()
            return False
        if not self.window_hidden():
            self.cfg["geometry"] = self.root.geometry()
        err = save_config(self.cfg_path, self.cfg)
        if not err:
            # gegenlesen: steht wirklich drin, was wir geschrieben haben?
            back = load_config(self.cfg_path)
            if any(back.get(k) != self.cfg.get(k) for k in ("host", "ifindex", "community")):
                err = T("Konfiguration geschrieben, aber beim Gegenlesen anders – bitte melden")
        write_log(self.cfg_path, f"gespeichert host={self.cfg['host']!r} "
                                 f"ifindex={self.cfg['ifindex']} -> {err or 'ok'}")
        if err:
            self.error = err
        elif show:
            self.flash = T("Gespeichert: {name}", name=os.path.basename(self.cfg_path))
            self.root.after(6000, self._end_flash)
        self.update_labels()
        return err is None

    # ------------------------------------------------------------ Sicherungskopien
    def backup_dir(self):
        return os.path.join(os.path.dirname(self.cfg_path), BACKUP_DIR)

    def list_backups(self):
        """Sicherungskopien dieser Konfiguration, neueste zuerst: [(Pfad, Zeitpunkt-Text)]."""
        pre = config_name(self.cfg_path) + "_"
        out = []
        try:
            names = os.listdir(self.backup_dir())
        except OSError:
            return out
        for fn in names:
            if not (fn.startswith(pre) and fn.lower().endswith(".json")):
                continue
            stamp = fn[len(pre):-5]
            try:
                t = time.strptime(stamp[:17], "%Y-%m-%d_%H%M%S")   # evtl. mit Zusatz "-2"
            except ValueError:
                continue
            out.append((os.path.join(self.backup_dir(), fn), t))
        out.sort(key=lambda e: (e[1], len(e[0]), e[0]), reverse=True)
        fmt = "%d.%m.%Y %H:%M:%S" if LANG == "de" else "%Y-%m-%d %H:%M:%S"
        return [(p, time.strftime(fmt, t)) for p, t in out]

    def make_backup(self, quiet=False):
        """Aktuellen Stand speichern und als Kopie nach Backup/<Name>_<Zeit>.json legen."""
        if not self.save():
            return None
        base = os.path.join(self.backup_dir(), f"{config_name(self.cfg_path)}_"
                                               f"{time.strftime('%Y-%m-%d_%H%M%S')}")
        dst, k = base + ".json", 1
        while os.path.exists(dst):      # zwei Kopien in derselben Sekunde
            k += 1
            dst = f"{base}-{k}.json"
        try:
            if not os.path.isdir(self.backup_dir()):
                os.mkdir(self.backup_dir())
            with open(self.cfg_path, "rb") as f:
                data = f.read()
            tmp = dst + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dst)
        except OSError as e:
            write_log(self.cfg_path, f"Sicherungskopie fehlgeschlagen: {e}")
            self.error = T("Sicherungskopie nicht gespeichert: {e}", e=e)
            self.update_labels()
            return None
        write_log(self.cfg_path, f"Sicherungskopie {dst}")
        if not quiet:
            self.flash = T("Sicherungskopie gespeichert: {name}",
                           name=f"{BACKUP_DIR}{os.sep}{os.path.basename(dst)}")
            self.root.after(6000, self._end_flash)
            self.update_labels()
        return dst

    def fill_backup_menu(self):
        m = self.backup_menu
        m.delete(0, "end")
        backups = self.list_backups()
        for path, when in backups[:20]:
            m.add_command(label=T("Stand vom {when}", when=when),
                          state="disabled" if self.readonly else "normal",
                          command=lambda p=path, w=when: self.restore_backup(p, w))
        if not backups:
            m.add_command(label=T("Keine Sicherungskopien von „{name}“", name=config_name(self.cfg_path)),
                          state="disabled")
        m.add_separator()
        m.add_command(label=T("Backup-Ordner öffnen"), command=self.open_backup_folder,
                      state="normal" if backups and sys.platform == "win32" else "disabled")

    def restore_backup(self, path, when):
        from tkinter import messagebox
        self.ensure_visible()
        if not messagebox.askyesno(
                APP, T("„{name}“ auf den Stand vom {when} zurücksetzen?\n\n"
                       "Die jetzigen Einstellungen werden vorher ebenfalls als Sicherungskopie gespeichert.",
                       name=config_name(self.cfg_path), when=when), parent=self.root):
            return
        try:
            with open(path, encoding="utf-8") as f:
                json.load(f)
        except (OSError, ValueError) as e:
            self.error = T("Sicherungskopie nicht lesbar: {e}", e=e)
            self.update_labels()
            return
        if self.make_backup(quiet=True) is None:
            return
        # Die Kopie komplett uebernehmen – auch Position und Groesse – und ohne erneutes
        # Speichern neu starten (sonst schriebe on_close die jetzige Position zurueck)
        cfg = load_config(path)
        err = save_config(self.cfg_path, cfg)
        if err:
            self.error = err
            self.update_labels()
            return
        self.cfg = cfg
        self._no_save_on_close = True
        write_log(self.cfg_path, f"wiederhergestellt aus {path} – Fenster startet neu")
        self.restart()

    def open_backup_folder(self):
        try:
            if sys.platform == "win32":
                os.startfile(real_path(self.backup_dir()))
        except OSError as e:
            self.error = str(e)
            self.update_labels()

    def _end_flash(self):
        self.flash = ""
        self.update_labels()

    def fill_open_menu(self):
        m = self.open_menu
        m.delete(0, "end")
        d = os.path.dirname(self.cfg_path)
        me = config_name(self.cfg_path).lower()
        for name in list_configs(d):
            if name.lower() == me:
                continue
            used = config_in_use(os.path.join(d, name + ".json"))
            m.add_command(label=T("{name}  ➜  neues Fenster", name=name) + (T("   (schon offen)") if used else ""),
                          state="disabled" if used else "normal",
                          command=lambda n=name: self.menu_open_window(n))
        if m.index("end") is not None:
            m.add_separator()
        m.add_command(label=T("Neue Konfiguration"), command=self.new_instance)

    def menu_open_window(self, name):
        write_log(self.cfg_path, f"Menü: Weiteres Fenster öffnen → {name}")
        launch_instance(name)

    def menu_load_config(self, path):
        write_log(self.cfg_path, f"Menü: Konfiguration laden → {config_name(path)}")
        self.switch_config(path)

    def fill_load_menu(self):
        m = self.load_menu
        m.delete(0, "end")
        d = os.path.dirname(self.cfg_path)
        me = config_name(self.cfg_path).lower()
        for name in list_configs(d):
            if name.lower() == me:
                continue
            path = os.path.join(d, name + ".json")
            used = config_in_use(path)
            m.add_command(label=T("{name}  ⟲  hier laden (ersetzt dieses Fenster)", name=name)
                                + (T("   (schon offen)") if used else ""),
                          state="disabled" if used else "normal",
                          command=lambda p=path: self.menu_load_config(p))
        if m.index("end") is not None:
            m.add_separator()
        m.add_command(label=T("Datei wählen …"), command=self.pick_config_file)

    def pick_config_file(self):
        self.ensure_visible()
        p = filedialog.askopenfilename(parent=self.root, initialdir=os.path.dirname(self.cfg_path),
                                       title=T("Konfiguration laden"),
                                       filetypes=[("FTG-Konfiguration", "*.json")])
        if p:
            self.switch_config(os.path.normpath(p))

    def switch_config(self, path):
        """Laedt eine andere Konfiguration in dieses Fenster."""
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(self.cfg_path)):
            return True
        lock = acquire_lock(path)
        if lock is None:
            self.error = lock_problem(path)
            self.update_labels()
            return False
        if not self.readonly:
            self.save()
        if self._lock:
            self._lock.close()
        write_log(self.cfg_path, f"wechsle zu {path}")
        self.stop()
        self.cfg_path, self._lock = path, lock
        self.readonly, self.readonly_reason = False, ""
        self.cfg = load_config(path)
        write_log(path, f"geladen, host={self.cfg['host']!r}")
        # Fenster an die gespeicherte Position/Groesse der geladenen Konfiguration
        geo = self.cfg.get("geometry") or ""
        if parse_geometry(geo):
            self.root.geometry(geo)
            self.root.update_idletasks()
            self.root.after(200, lambda: self.ensure_on_screen("Konfiguration geladen"))
        self.var_top.set(bool(self.cfg["topmost"]))
        self.var_bl.set(bool(self.cfg["borderless"]))
        self.var_tray.set(bool(self.cfg["tray"]))
        self.apply_borderless()
        self.root.attributes("-topmost", bool(self.cfg["topmost"]))
        self.data = deque(maxlen=self.maxpoints())
        self.paused = False
        self.frozen = None
        self.offset = 0.0
        self.var_window.set(int(float(self.cfg["window"])))
        self.var_fill.set(self.cfg["fill"])
        self.apply_look()
        self._set_pause_label()
        self.error = self.info = self.flash = ""
        self.oids = []
        self.update_title()
        self.update_labels()
        self.redraw()
        if self.cfg["host"] and self.cfg["ifindex"]:
            self.start()
        else:
            self.open_settings()
        return True

    def fill_lnk_menu(self):
        m = self.lnk_menu
        m.delete(0, "end")
        name = config_name(self.cfg_path)
        if sys.platform != "win32":
            m.add_command(label=T("Nur unter Windows verfügbar"), state="disabled")
            return
        auto = os.path.join(startup_dir(), shortcut_name(self.cfg_path))
        in_auto = os.path.exists(auto)
        m.add_command(label=T("„{name}“ auf den Desktop", name=name), command=lambda: self.make_shortcut("Desktop"))
        m.add_command(label=T("„{name}“ in den Autostart", name=name) + (T("  (aktualisieren)") if in_auto else ""),
                      command=lambda: self.make_shortcut("Startup"))
        if in_auto:
            m.add_command(label=T("„{name}“ aus dem Autostart entfernen", name=name),
                          command=lambda: self.remove_autostart(auto))
        m.add_separator()
        m.add_command(label=T("Autostart-Ordner öffnen"), command=lambda: os.startfile(startup_dir()))

    def make_shortcut(self, where):
        from tkinter import messagebox
        self.ensure_visible()
        ok, info = create_shortcut(self.cfg_path, where)
        write_log(self.cfg_path, f"Verknüpfung {where}: {'ok ' if ok else 'FEHLER '}{info}")
        if ok:
            target, args, _ = launch_command(self.cfg_path)
            messagebox.showinfo(APP, T("Verknüpfung erstellt:\n{info}\n\nStartet:\n{target} {args}",
                                         info=info, target=target, args=args),
                                parent=self.root)
        else:
            messagebox.showerror(APP, T("Verknüpfung konnte nicht erstellt werden:\n\n{info}", info=info),
                                 parent=self.root)

    def remove_autostart(self, path):
        try:
            os.remove(path)
            self.flash = T("Aus dem Autostart entfernt")
            self.root.after(4000, self._end_flash)
        except OSError as e:
            self.error = str(e)
        self.update_labels()

    def fill_dir_menu(self):
        m = self.dir_menu
        m.delete(0, "end")
        cur = os.path.dirname(self.cfg_path)
        m.add_command(label=cur, state="disabled")
        m.add_separator()
        m.add_command(label=T("Im Explorer öffnen"), command=self.open_config_folder)
        m.add_command(label=T("Anderen Ordner wählen …"), command=self.choose_config_dir)
        if load_settings().get("config_dir"):
            m.add_command(label=T("Zurück auf Standard (AppData)"),
                          command=lambda: self.set_config_dir(local_dir()))

    def choose_config_dir(self):
        self.ensure_visible()
        d = filedialog.askdirectory(parent=self.root, initialdir=os.path.dirname(self.cfg_path),
                                    title=T("Konfigurationsordner wählen"), mustexist=True)
        if d:
            self.set_config_dir(os.path.normpath(d))

    def set_config_dir(self, new_dir):
        from tkinter import messagebox
        self.ensure_visible()
        old_dir = os.path.dirname(self.cfg_path)
        if os.path.normcase(new_dir) == os.path.normcase(old_dir):
            return
        if not os.path.isdir(new_dir):
            messagebox.showerror(APP, T("Ordner nicht erreichbar:\n{d}", d=new_dir), parent=self.root)
            return
        name = config_name(self.cfg_path)
        target = os.path.join(new_dir, name + ".json")
        if os.path.exists(target):
            ans = messagebox.askyesnocancel(
                APP, T("Im neuen Ordner gibt es schon „{name}“.\n\n"
                       "Ja: diese Konfiguration von dort laden\n"
                       "Nein: mit der aktuellen Konfiguration überschreiben", name=name), parent=self.root)
            if ans is None:
                return
            if ans is False:
                self.cfg["geometry"] = self.root.geometry()
                err = save_config(target, self.cfg)
                if err:
                    messagebox.showerror(APP, err, parent=self.root)
                    return
        else:
            self.cfg["geometry"] = self.root.geometry()
            err = save_config(target, self.cfg)
            if err:
                messagebox.showerror(APP, err, parent=self.root)
                return
        others = [n for n in list_configs(old_dir)
                  if n.lower() != name.lower()
                  and not os.path.exists(os.path.join(new_dir, n + ".json"))]
        if others and messagebox.askyesno(
                APP, T("Sollen auch die übrigen Konfigurationen in den neuen Ordner kopiert werden?\n\n")
                     + ", ".join(others), parent=self.root):
            import shutil
            for n in others:
                try:
                    shutil.copy2(os.path.join(old_dir, n + ".json"), os.path.join(new_dir, n + ".json"))
                except OSError as e:
                    messagebox.showerror(APP, f"{n}: {e}", parent=self.root)
        st = load_settings()
        if os.path.normcase(new_dir) == os.path.normcase(local_dir()):
            st.pop("config_dir", None)
        else:
            st["config_dir"] = new_dir
        err = save_settings(st)
        if err:
            messagebox.showerror(APP, err, parent=self.root)
            return
        for d in (old_dir, new_dir):      # in beiden Ordnern nachvollziehbar
            write_log(os.path.join(d, name + ".json"), f"Konfigurationsordner gewechselt: {old_dir} -> {new_dir}")
        if self.switch_config(target):
            self.flash = T("Konfigurationsordner gewechselt")
            self.root.after(6000, self._end_flash)
            self.update_labels()

    def restart(self):
        """Fenster neu starten (z. B. nach Wechsel der Sprache)."""
        path = self.cfg_path
        self.on_close()
        if self._lock:
            self._lock.close()
            self._lock = None
        launch_instance(path)

    def new_instance(self):
        d = os.path.dirname(self.cfg_path)
        existing = {n.lower() for n in list_configs(d)}
        k = 1
        while f"{T('neu')}{k}" in existing:
            k += 1
        launch_instance(f"{T('neu')}{k}")

    def rename_config(self, new_path, new_lock):
        old_path, old_lock = self.cfg_path, self._lock
        self.cfg_path, self._lock = new_path, new_lock
        err = save_config(new_path, self.cfg)
        if err:
            new_lock.close()
            self.cfg_path, self._lock = old_path, old_lock
            return err
        write_log(new_path, f"umbenannt von {config_name(old_path)}")
        if old_lock:
            old_lock.close()
        for f in (old_path, old_path + ".lock"):
            try:
                os.remove(f)
            except OSError:
                pass
        return None

    def open_config_folder(self):
        d = os.path.dirname(self.cfg_path)
        try:
            os.makedirs(d, exist_ok=True)
            if sys.platform == "win32":
                # Explorer mit markierter Datei am tatsaechlichen Speicherort
                import subprocess
                f = real_path(self.cfg_path)
                if os.path.exists(f):
                    subprocess.Popen(["explorer", "/select,", f])
                else:
                    os.startfile(real_path(d))
        except OSError as e:
            self.error = str(e)
            self.update_labels()

    def show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def view_data(self):
        """Was angezeigt wird: waehrend der Pause der eingefrorene Stand."""
        return self.frozen if self.frozen is not None else self.data

    def max_offset(self, data=None):
        data = self.view_data() if data is None else data
        if len(data) < 2:
            return 0.0
        return max(0.0, data[-1][0] - data[0][0] - float(self.cfg["window"]))

    def visible(self):
        """(Punkte im sichtbaren Ausschnitt, Zeit am rechten Rand, Zeitraum, Versatz)."""
        data = self.view_data()
        window = float(self.cfg["window"])
        if not data:
            return [], 0.0, window, 0.0
        off = min(self.offset, self.max_offset(data))
        t_end = data[-1][0] - off
        t_start = t_end - window - 1e-6
        if data[0][0] >= t_start and off == 0:
            return list(data), t_end, window, off
        return [p for p in data if t_start <= p[0] <= t_end + 1e-6], t_end, window, off

    def clear(self):
        """Statistik zuruecksetzen = Verlauf leeren (Ø/max gelten fuer den Verlauf)."""
        self.data.clear()
        if self.frozen is not None:
            self.frozen = []
        self.offset = 0.0
        self.update_labels()
        self.redraw()
        if self.tray_active():
            self.update_tray()

    def on_close(self):
        if not self.readonly and not getattr(self, "_no_save_on_close", False):
            self.save()
        write_log(self.cfg_path, "Ende")
        self.stop()
        if self.tray:
            self.tray.remove()
        self.root.destroy()

    # ---------------------------------------------------------- Daten
    def process_queue(self):
        changed = False
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] != self.gen:
                    continue
                kind = msg[1]
                if kind == "data":
                    self.add_sample(*msg[2:])
                    changed = True
                elif kind == "log":
                    write_log(self.cfg_path, msg[2])
                elif kind == "error":
                    if self.error != msg[2]:
                        self.data.append((time.time(), None, None))
                        write_log(self.cfg_path, f"Abfragefehler: {msg[2]}")
                    self.error = msg[2]
                    changed = True
                elif kind == "info":
                    self.info = msg[2]
                    self.oids = msg[3]
                    changed = True
        except queue.Empty:
            pass
        if self.tray:
            while True:
                try:
                    ev = self.tray.q.get_nowait()
                except queue.Empty:
                    break
                self.handle_tray_event(ev)
        if changed:
            self.update_labels()                 # zeigt in der Pause den eingefrorenen Stand
            if not self.paused:                  # Graph bleibt in der Pause stehen
                if not self.window_hidden():
                    self.redraw()
                if self.tray_active():
                    self.update_tray()
        # oft nachsehen, damit neue Werte sofort (und in allen Fenstern
        # gleichzeitig) gezeichnet werden
        self.root.after(25, self.process_queue)

    def add_sample(self, ts, rin, rout):
        self.error = ""
        self.data.append((ts, rin, rout))

    # ---------------------------------------------------------- Zeitraum / Blaettern
    def set_window(self, sec):
        sec = int(sec)
        if sec < 10 or sec / float(self.cfg["interval"]) > 20000 or sec == int(float(self.cfg["window"])):
            return
        self.cfg["window"] = sec
        self.var_window.set(sec)
        if self.maxpoints() != self.data.maxlen:
            self.data = deque(self.data, maxlen=self.maxpoints())
        self.offset = min(self.offset, self.max_offset())
        self.update_labels()
        self.redraw()
        self.schedule_save()

    def zoom_wheel(self, direction):
        """Shift+Mausrad bzw. Mausrad kippen (Tk 9 meldet Kippen als Shift+Mausrad):
        gebremst, damit gehaltenes Kippen nicht alle Stufen auf einmal durchlaeuft."""
        now = time.monotonic()
        if now - getattr(self, "_zoom_t", 0) < 0.25:
            return
        self._zoom_t = now
        self.zoom(direction)

    def zoom(self, direction):
        """direction -1 = kuerzerer Zeitraum (hinein), +1 = laengerer (heraus)."""
        cur = int(float(self.cfg["window"]))
        steps = sorted(set(ZOOM_STEPS) | {cur})
        if direction > 0:
            nxt = next((t for t in steps if t > cur), None)
        else:
            nxt = next((t for t in reversed(steps) if t < cur), None)
        if nxt:
            self.set_window(nxt)

    def scroll(self, direction):
        """direction +1 = zurueck (aelter), -1 = vor Richtung jetzt."""
        data = self.view_data() if self.paused else self.data
        maxoff = self.max_offset(data)
        if direction > 0 and maxoff <= 0:
            return
        step = scroll_step(float(self.cfg["window"]), float(self.cfg["interval"]))
        new = min(max(0.0, self.offset + direction * step), maxoff)
        if new > 0 and not self.paused:
            self.toggle_pause(auto=True)          # zum Nachsehen anhalten, Messung laeuft weiter
        self.offset = new
        if new == 0 and self.auto_paused:
            self.toggle_pause()                   # wieder bei "jetzt" -> weiterlaufen
            return
        self.update_labels()
        self.redraw()

    def go_live(self):
        if self.paused:
            self.toggle_pause()
        self.offset = 0.0
        self.redraw()

    def fill_window_menu(self):
        m = self.win_menu
        m.delete(0, "end")
        if self.offset > 0 or self.paused:
            m.add_command(label=T("Zurück zu „jetzt“"), command=self.go_live, accelerator=T("Ende"))
            m.add_separator()
        cur = int(float(self.cfg["window"]))
        for t in sorted(set(ZOOM_STEPS) | {cur}):
            m.add_radiobutton(label=fmt_span(t), value=t, variable=self.var_window,
                              command=lambda t=t: self.set_window(t), selectcolor=FG)
        m.add_separator()
        m.add_command(label=T("Mausrad = blättern, Shift+Mausrad = Zeitraum"), state="disabled")

    def set_fill_from_menu(self):
        self.cfg["fill"] = self.var_fill.get()
        self.redraw()
        if self.tray_active():
            self.update_tray()
        self.schedule_save()

    def schedule_save(self):
        """Bei schnellen Aenderungen (Mausrad) nur einmal speichern."""
        if self.readonly:
            return
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(1500, self._do_save)

    def _do_save(self):
        self._save_job = None
        self.save()

    # ---------------------------------------------------------- Anordnen / Groesse
    # Jedes Fenster ist ein eigener Prozess. Abgesprochen wird ueber eine kleine
    # Auftragsdatei im Konfigurationsordner, die jedes Fenster sekuendlich prueft.
    def other_configs(self):
        """[(Name, Pfad, laeuft)] der anderen Konfigurationen im Ordner."""
        d = os.path.dirname(self.cfg_path)
        me = config_name(self.cfg_path).lower()
        out = []
        for name in list_configs(d):
            if name.lower() == me:
                continue
            path = os.path.join(d, name + ".json")
            out.append((name, path, config_in_use(path)))
        return out

    def fill_arrange_menu(self):
        m = self.win_arr_menu
        m.delete(0, "end")
        running = [n for n, _, run in self.other_configs() if run]
        st = "normal" if running else "disabled"
        for how, label in (("down", "↓  darunter"), ("up", "↑  darüber"),
                           ("right", "→  rechts daneben"), ("left", "←  links daneben")):
            m.add_command(label=T(label), state=st, command=lambda h=how: self.arrange(h))
        m.add_separator()
        m.add_command(label=(T("Dieses Fenster gibt Position und Größe vor; offen: ")
                             + ", ".join(running)) if running else T("Keine weiteren Fenster offen"),
                      state="disabled")

    def fill_size_menu(self):
        m = self.size_menu
        m.delete(0, "end")
        others = self.other_configs()
        if not others:
            m.add_command(label=T("Keine weiteren Konfigurationen"), state="disabled")
            return
        for name, path, run in others:
            m.add_command(label=name + (T("   (offen)") if run else ""),
                          command=lambda n=name: self.copy_size([n]))
        m.add_separator()
        m.add_command(label=T("alle"), command=lambda: self.copy_size([n for n, _, _ in others]))

    def outer_size(self):
        """Aussenmasse (mit Titelleiste/Rahmen) und Rahmenzuschlag des Fensters."""
        r = self.root
        r.update_idletasks()
        g = parse_geometry(r.geometry())
        left = max(0, r.winfo_rootx() - g[2]) if g and g[2] is not None else 0
        top = max(0, r.winfo_rooty() - g[3]) if g and g[3] is not None else 0
        return r.winfo_width() + 2 * left, r.winfo_height() + top + left

    def ensure_on_screen(self, why=""):
        """Fenster ganz in den Arbeitsbereich des naechsten Monitors holen."""
        r = self.root
        g = parse_geometry(r.geometry())
        if not g or g[2] is None:
            return
        w, h, x, y = g
        ow, oh = self.outer_size()
        nx, ny = fit_rect(x, y, ow, oh, work_area(r, (x, y, x + ow, y + oh)))
        if (nx, ny) != (x, y):
            r.geometry(f"+{nx}+{ny}")
            r.update_idletasks()
            self.sync_under()
            write_log(self.cfg_path, f"Fenster in den sichtbaren Bereich geholt ({why}): "
                                     f"+{x}+{y} -> +{nx}+{ny}")

    def arrange(self, how):
        """Laufende Fenster an dieses Fenster setzen: how = "down", "up", "right"
        oder "left"; alphabetische Reihenfolge, alle in der Groesse dieses Fensters."""
        r = self.root
        g = parse_geometry(r.geometry())
        if not g or g[2] is None:
            return
        w, h, x, y = g
        ow, oh = self.outer_size()
        area = work_area(r, (x, y, x + ow, y + oh))
        names = [n for n, _, run in self.other_configs() if run]
        dx, dy = {"down": (0, 1), "up": (0, -1), "right": (1, 0), "left": (-1, 0)}[how]
        n = len(names)
        # Umriss des ganzen Stapels (dieses Fenster + n weitere)
        bx0, by0 = min(x, x + dx * n * ow), min(y, y + dy * n * oh)
        bw, bh = ow * (1 + n * abs(dx)), oh * (1 + n * abs(dy))
        l, t, rr, b = area
        fits = bw <= rr - l and bh <= b - t
        # passt der Stapel auf den Monitor, aber nicht an dieser Stelle: ganz verschieben,
        # auch dieses Fenster (sonst landen die anderen am Rand uebereinander)
        sx, sy = fit_rect(bx0, by0, bw, bh, area) if fits else (bx0, by0)
        shift_x, shift_y = sx - bx0, sy - by0
        moved_self = bool(shift_x or shift_y)
        if moved_self:
            x, y = x + shift_x, y + shift_y
            r.geometry(f"+{x}+{y}")
            r.update_idletasks()
            self.sync_under()
        targets = {}
        for k, name in enumerate(names, 1):
            nx, ny = x + dx * k * ow, y + dy * k * oh
            targets[name.lower()] = {"geometry": f"{w}x{h}+{nx}+{ny}"}
        if not targets:
            self.flash = T("Keine weiteren Fenster offen")
        else:
            post_order(os.path.dirname(self.cfg_path), targets)
            self.flash = (T("{n} Fenster angeordnet", n=len(targets))
                          + (T(" – Stapel verschoben, damit alles auf den Monitor passt") if moved_self else "")
                          if fits else
                          T("{n} Fenster angeordnet – der Monitor ist dafür zu klein, "
                            "sie wurden an den Rand geschoben", n=len(targets)))
            write_log(self.cfg_path, f"Fenster anordnen ({how})"
                                     + (f", Stapel verschoben um {shift_x:+d}/{shift_y:+d}" if moved_self else "")
                                     + f": {targets}")
        self.update_labels()
        self.root.after(4000, self._end_flash)

    def copy_size(self, names):
        """Groesse dieses Fensters an andere Konfigurationen geben: offene Fenster
        per Auftrag, geschlossene direkt in ihre Datei (Position bleibt)."""
        w, h = self.root.winfo_width(), self.root.winfo_height()
        d = os.path.dirname(self.cfg_path)
        running = {n.lower() for n, _, run in self.other_configs() if run}
        targets, done = {}, []
        for name in names:
            if name.lower() in running:
                targets[name.lower()] = {"size": [w, h]}
                done.append(name)
                continue
            path = os.path.join(d, name + ".json")
            if config_in_use(path):
                continue
            cfg = load_config(path)
            g = parse_geometry(cfg.get("geometry"))
            cfg["geometry"] = f"{w}x{h}" + (f"+{g[2]}+{g[3]}" if g and g[2] is not None else "")
            if not save_config(path, cfg):
                done.append(name)
        if targets:
            post_order(d, targets)
        write_log(self.cfg_path, f"Größe {w}x{h} übernommen für: {', '.join(done) or '–'}")
        self.flash = (T("Größe {w} × {h} übernommen: {names}", w=w, h=h, names=", ".join(done))
                      if done else T("Nichts geändert"))
        self.update_labels()
        self.root.after(5000, self._end_flash)

    def check_order(self):
        """Auftrag eines anderen Fensters ausfuehren, falls er dieses Fenster betrifft."""
        d = os.path.dirname(self.cfg_path)
        try:
            mt = os.path.getmtime(os.path.join(d, ORDER_FILE))
        except OSError:
            return
        if mt == self._order_mtime:
            return
        self._order_mtime = mt
        oid, when, targets = read_order(d)
        if not oid or oid == self._order_seen:
            return
        self._order_seen = oid
        if abs(time.time() - when) > 30:                   # alter Auftrag
            return
        t = targets.get(config_name(self.cfg_path).lower())
        if not t:
            return
        r = self.root
        if "geometry" in t and parse_geometry(t["geometry"]):
            r.geometry(t["geometry"])
        elif "size" in t:
            w, h = (int(v) for v in t["size"])
            r.geometry(f"{w}x{h}")
        else:
            return
        r.update_idletasks()
        self.sync_under()
        write_log(self.cfg_path, f"Auftrag ausgeführt: {t}")
        self.ensure_on_screen("Auftrag")
        self.schedule_save()

    # ---------------------------------------------------------- Transparenz
    def apply_look(self, alpha=None, bg_alpha=None):
        """Deckkraft (ganzes Fenster) und Hintergrund-Deckkraft anwenden.
        Ohne Argumente aus der Konfiguration, sonst als Vorschau."""
        cfg = self.cfg
        self._look = (float(cfg.get("alpha", 100) if alpha is None else alpha),
                      float(cfg.get("bg_alpha", 100) if bg_alpha is None else bg_alpha))
        self._hover = None
        bg_on = self._look[1] < 100 and bg_supported()
        if bg_on != self.bg_on:
            self.bg_on = bg_on
            col = BG if bg_on else PANEL
            for w in (self.bar, self.lbl_in, self.lbl_out, self.lbl_state, self.grip):
                w.configure(bg=col)
            try:
                self.root.attributes("-transparentcolor", BG if bg_on else "")
            except tk.TclError:
                pass
            self.redraw()
        if bg_on:
            self.ensure_under()
        self.set_alpha(False)
        self.sync_under()
        if self.tray_active():
            self.root.after_idle(self.check_taskbar)

    # ---------------------------------------------------------- Unterlage
    # Windows kann eine Farbe nur ganz durchsichtig machen (-transparentcolor).
    # Fuer einen halbdurchsichtigen Hintergrund liegt deshalb direkt hinter dem
    # Fenster eine rahmenlose Flaeche in Hintergrundfarbe mit eigener Deckkraft.
    # Sie faengt auch die Klicks auf den Hintergrund ab (Menue, Mausrad, Strg+Ziehen).
    def ensure_under(self):
        if self.under is not None:
            return
        u = tk.Toplevel(self.root, bg=BG, highlightthickness=0, bd=0)
        u.withdraw()
        u.overrideredirect(True)                 # kein Rahmen, keine Taskleiste
        try:
            u.attributes("-alpha", 0.5)           # vor dem 1. Anzeigen: "layered"
            u.attributes("-topmost", bool(self.cfg["topmost"]))
        except tk.TclError:
            pass
        u.bind("<Button-3>", self.show_menu)
        u.bind("<Double-Button-1>", lambda e: self.open_settings())
        self.bind_move(u)
        self.bind_wheel(u)
        self.bind_side_buttons(u)
        self.under = u
        self._under_geo = None

    def sync_under(self):
        """Unterlage an Position, Groesse, Sichtbarkeit und Z-Reihenfolge des
        Fensters anpassen (wird auch alle 100 ms aufgerufen)."""
        u = self.under
        if u is None:
            return
        r = self.root
        try:
            if not self.bg_on or self.window_hidden() or not r.winfo_ismapped():
                if u.state() != "withdrawn":
                    u.withdraw()
                    self._under_geo = None
                return
            geo = (r.winfo_rootx(), r.winfo_rooty(), r.winfo_width(), r.winfo_height())
            if u.state() == "withdrawn":
                u.geometry("%dx%d+%d+%d" % (geo[2], geo[3], geo[0], geo[1]))
                u.deiconify()
                u.update_idletasks()
                self._under_noactivate()
                self._under_geo = None
            if geo != self._under_geo:
                self._under_geo = geo
                if sys.platform == "win32":
                    self._under_place(geo)        # sofort, auch waehrend Windows verschiebt
                else:
                    u.geometry("%dx%d+%d+%d" % (geo[2], geo[3], geo[0], geo[1]))
            self._under_zorder()
        except tk.TclError:
            pass

    def _under_hwnds(self):
        w = win32()
        return w, w.GetParent(self.root.winfo_id()), w.GetParent(self.under.winfo_id())

    def _under_noactivate(self):
        """Klick auf die Unterlage soll sie nicht nach vorne holen."""
        if sys.platform != "win32":
            return
        w, _, uh = self._under_hwnds()
        if uh:
            ex = w.GetWindowLongW(uh, -20)
            w.SetWindowLongW(uh, -20, ex | 0x08000000)          # WS_EX_NOACTIVATE

    def _under_place(self, geo):
        w, main, uh = self._under_hwnds()
        if main and uh:
            # direkt hinter das Fenster, Position und Groesse in einem Schritt
            w.SetWindowPos(uh, main, geo[0], geo[1], geo[2], geo[3], 0x0010 | 0x0200)

    def _under_zorder(self):
        if sys.platform != "win32":
            return
        w, main, uh = self._under_hwnds()
        if main and uh and w.GetWindow(main, 2) != uh:          # GW_HWNDNEXT
            w.SetWindowPos(uh, main, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0200)

    def check_taskbar(self):
        """Selbstheilung: Taskleisten-Knopf im Tray-Modus wieder ausblenden,
        falls ihn etwas zurueckgebracht hat (wird protokolliert)."""
        if not (tray_supported() and self.tray_active()):
            return
        try:
            bl = bool(self.cfg["borderless"])
            if not taskbar_style_ok(self.root, self.tray.hwnd, bl):
                write_log(self.cfg_path, "Taskleisten-Knopf war wieder da – erneut ausgeblendet")
                set_taskbar_button(self.root, False, self.tray.hwnd, bl)
        except Exception as e:
            write_log(self.cfg_path, f"Taskleisten-Prüfung: {type(e).__name__}: {e}")

    def set_alpha(self, hover):
        wa, ba = self._look
        a = 1.0 if hover else max(0.2, min(1.0, wa / 100))
        # Unterlage: Hintergrund-Deckkraft (mind. 1 %, damit sie Klicks annimmt)
        b = 1.0 if hover else max(0.01, min(1.0, ba / 100)) * a
        if self.under is not None:
            try:
                self.under.attributes("-alpha", min(b, 0.999) if sys.platform == "win32" else b)
            except tk.TclError:
                pass
        if sys.platform == "win32":
            # Nie ganz 1.0 (0,999 ergibt trotzdem volle Deckkraft): so ist das
            # Fenster fuer Tk von Anfang an "layered". Sonst ersetzt Tk beim
            # ersten Absenken der Deckkraft den kompletten erweiterten
            # Fensterstil – und der Taskleisten-Knopf ist im Tray-Modus wieder da.
            a = min(a, 0.999)
        try:
            self.root.attributes("-alpha", a)
        except tk.TclError:
            pass

    def _hover_poll(self):
        """Unter der Maus voll deckend (auch ueber durchsichtigen Stellen)."""
        try:
            self.sync_under()
            if ((self._look[0] < 100 or self.bg_on) and self.cfg.get("alpha_hover")
                    and not self.window_hidden() and not getattr(self, "_alpha_preview", False)):
                r = self.root
                px, py = r.winfo_pointerxy()
                x, y = r.winfo_rootx(), r.winfo_rooty()
                inside = x <= px < x + r.winfo_width() and y <= py < y + r.winfo_height()
                if inside != self._hover:
                    self._hover = inside
                    self.set_alpha(inside)
        except tk.TclError:
            return
        self._poll_n = getattr(self, "_poll_n", 0) + 1
        if self._poll_n % 10 == 0:                       # jede Sekunde
            self.check_order()
        if self._poll_n % 20 == 0:                       # alle 2 s
            self.check_taskbar()
        self.root.after(100, self._hover_poll)

    # ---------------------------------------------------------- Anzeige
    def update_title(self):
        c = self.cfg
        name = c.get("ifname") or (f"Index {c['ifindex']}" if c["ifindex"] else "")
        cn = config_name(self.cfg_path)
        t = f"[{cn}] {name} @ {c['host']} – {APP}" if c["host"] else f"[{cn}] {APP}"
        if self.readonly:
            t += T(" (nur Ansicht)")
        self.root.title(t)

    def update_labels(self):
        u = self.cfg["unit"]
        wrap = max(140, int(self.root.winfo_width() * 0.4))
        self.lbl_in.config(fg=self.cfg["color_in"])
        self.lbl_out.config(fg=self.cfg["color_out"])
        # Ø und max gelten fuer den sichtbaren Ausschnitt
        avg_in, avg_out, mi, mo, c_in, c_out = view_stats(self.visible()[0])
        self.lbl_in.config(text=f"▼ In   {fmt_rate(c_in, u):>13}   Ø {fmt_rate(avg_in, u):>13}"
                                f"   max {fmt_rate(mi, u):>13}")
        self.lbl_out.config(text=f"▲ Out  {fmt_rate(c_out, u):>13}   Ø {fmt_rate(avg_out, u):>13}"
                                 f"   max {fmt_rate(mo, u):>13}")
        if self.error:
            self.lbl_state.config(text=self.error, fg=ERR, wraplength=wrap)
        elif self.flash:
            self.lbl_state.config(text=self.flash, fg=OK_COLOR, wraplength=wrap)
        elif self.paused:
            self.lbl_state.config(text=T("Pausiert"), fg=FG_DIM)
        else:
            parts = [T("alle {i} s", i=f"{self.cfg['interval']:g}") + f" · {fmt_span(float(self.cfg['window']))}"]
            if self.info:
                parts.append(T("{kind}-Zähler", kind=self.info) + f" · {snmp_label(self.cfg)}")
            self.lbl_state.config(text="\n".join(parts), fg=FG_DIM)

    def scale_top(self, pts=None):
        """Obergrenze der Skala (bit/s) – aus dem sichtbaren Ausschnitt,
        gleich fuer Graph und Tray-Symbol."""
        div = 8 if self.cfg["unit"] == "byte" else 1
        if pts is None:
            pts = self.visible()[0]
        _, _, mi, mo, _, _ = view_stats(pts)
        return (nice_ceiling(max(mi or 0, mo or 0) / div * 1.05) or 1000) * div

    def redraw(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 120 or h < 60:
            return
        unit = self.cfg["unit"]
        ml, mr, mt, mb = 82, 14, 14, 22
        gw, gh = w - ml - mr, h - mt - mb
        x_r, y_b = w - mr, mt + gh

        pts, t_end, window, off = self.visible()
        top = self.scale_top(pts)

        # waagrechte Linien + Skala
        for k in range(5):
            y = mt + gh * k / 4
            c.create_line(ml, y, x_r, y, fill=GRID_STRONG if k in (0, 4) else GRID)
            c.create_text(ml - 8, y, text=fmt_rate(top * (4 - k) / 4, unit),
                          fill=FG_DIM, font=FONT_SMALL, anchor="e")

        # senkrechte Zeitlinien (Alter relativ zu "jetzt", auch beim Blaettern)
        tick = next((t for t in (5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200)
                     if window / t <= 6 and t / window * gw >= 60), 14400)
        right = c.create_text(x_r, y_b + 4, text=T("jetzt") if off == 0 else fmt_age(off),
                              fill=FG_DIM if off == 0 else FG, font=FONT_SMALL, anchor="ne")
        free_until = c.bbox(right)[0] - 8          # Beschriftungen nicht ueberlappen
        a = (math.floor(off / tick + 1e-9) + 1) * tick
        while a <= off + window + 1e-9:
            x = x_r - (a - off) / window * gw
            c.create_line(x, mt, x, y_b, fill=GRID)
            t = c.create_text(x, y_b + 4, text=fmt_age(a), fill=FG_DIM, font=FONT_SMALL,
                              anchor="nw" if a >= off + window - 1e-9 else "n")
            if c.bbox(t)[2] > free_until:
                c.delete(t)
            a += tick

        # Kurven; mehr Messwerte als Pixel -> pro Pixelspalte das Maximum,
        # damit kurze Spitzen nicht verschwinden. Luecken (Timeouts) trennen.
        dense = len(pts) > gw
        segs, cur, bucket = [], [], None
        for ts, vi, vo in pts:
            if vi is None:
                if bucket:
                    cur.append(bucket)
                    bucket = None
                if cur:
                    segs.append(cur)
                    cur = []
                continue
            x = x_r - (t_end - ts) / window * gw
            if not dense:
                cur.append((x, vi, vo))
                continue
            col = int(x)
            if bucket and bucket[3] == col:
                bucket[1] = max(bucket[1], vi)
                bucket[2] = max(bucket[2], vo)
                continue
            if bucket:
                cur.append(bucket)
            bucket = [x, vi, vo, col]
        if bucket:
            cur.append(bucket)
        if cur:
            segs.append(cur)

        def Y(v):
            return y_b - min(v, top) / top * gh

        fill = self.cfg.get("fill", "in")
        ci, co = self.cfg["color_in"], self.cfg["color_out"]
        # durchsichtiger Hintergrund: Flaechen als Raster, dazwischen scheint
        # der Hintergrund durch (eine echte Halbtransparenz kennt Tk nicht)
        fk = {"stipple": "gray50"} if self.bg_on else {}
        fa = 0.45 if self.bg_on else 0.22

        def area(seg, f):
            p = [seg[0][0], y_b]
            for q in seg:
                p += [q[0], Y(f(q))]
            return p + [seg[-1][0], y_b]

        for seg in segs:
            if len(seg) < 2:
                continue
            if fill in ("in", "both"):
                c.create_polygon(area(seg, lambda q: q[1]), fill=blend(ci, BG, fa), outline="", **fk)
            if fill in ("out", "both"):
                c.create_polygon(area(seg, lambda q: q[2]), fill=blend(co, BG, fa), outline="", **fk)
            if fill == "both":                    # Ueberlappung in Mischfarbe
                c.create_polygon(area(seg, lambda q: min(q[1], q[2])),
                                 fill=blend(blend(ci, co, 0.5), BG, fa + 0.10), outline="", **fk)
        # Linien: die gefuellte zuerst, die freie Linie obendrauf
        order = ((2, co), (1, ci)) if fill == "out" else ((1, ci), (2, co))
        for seg in segs:
            if len(seg) < 2:
                continue
            for k, col in order:
                c.create_line([v for q in seg for v in (q[0], Y(q[k]))], fill=col, width=1.5)

        if off > 0:
            c.create_text(x_r - 6, mt + 6, text=T("◀ zurückgeblättert {span}  ·  Ende = jetzt", span=fmt_span(off)),
                          fill=FG, font=FONT_SMALL, anchor="ne")

        if self.cfg.get("show_label", True):
            col = self.cfg.get("color_label") or FG_DIM
            label = config_name(self.cfg_path)
            if self.cfg.get("if_sum") and self.cfg.get("ifindexes"):
                label += f" · [{len(self.cfg['ifindexes'])}]"
            t = c.create_text(ml + 8, mt + 6, text=label, anchor="nw",
                              fill=col, font=("Segoe UI", 10, "bold"))
            x1, y1, x2, y2 = c.bbox(t)
            bgr = c.create_rectangle(x1 - 5, y1 - 2, x2 + 5, y2 + 2, outline=blend(col, BG, 0.35),
                                     fill="" if self.bg_on else blend(col, BG, 0.10))
            c.tag_lower(bgr, t)

        if self.paused and off == 0:
            c.create_text(ml + gw / 2, mt + gh / 2, text="PAUSE", fill=FG_DIM, font=("Segoe UI", 16, "bold"))
        elif not pts and not self.error and self.cfg["host"]:
            c.create_text(ml + gw / 2, mt + gh / 2, text=T("warte auf Daten …"), fill=FG_DIM, font=FONT)
        self.draw_size_hint()

    # ---------------------------------------------------------- Einstellungen
    def open_settings(self):
        self.ensure_visible()
        if getattr(self, "_dlg", None) and self._dlg.winfo_exists():
            self._dlg.lift()
            return
        self._dlg = SettingsDialog(self)

    def apply_settings(self, new_cfg):
        old_pts = list(self.data)
        def same_secret(k):
            try:
                return reveal_secret(new_cfg.get(k, "")) == reveal_secret(self.cfg.get(k, ""))
            except SnmpError:
                return False
        restart = (any(new_cfg.get(k) != self.cfg.get(k) for k in
                       ("host", "port", "community", "ifindex", "interval", "snmp_version",
                        "v3_user", "v3_auth", "v3_priv", "if_sum", "ifindexes"))
                   or not same_secret("v3_auth_pw") or not same_secret("v3_priv_pw"))
        self.cfg.update(new_cfg)
        self.data = deque(old_pts if not restart else [], maxlen=self.maxpoints())
        self.var_window.set(int(float(self.cfg["window"])))
        self.var_fill.set(self.cfg["fill"])
        self.apply_look()
        if restart:
            self.paused = False
            self.frozen = None
            self.offset = 0.0
            self._set_pause_label()
            self.start()
        self.update_title()
        self.save(show=True)
        self.update_labels()
        self.redraw()
        if self.tray_active():
            self.update_tray()


class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        cfg = app.cfg
        self.title(T("Einstellungen"))
        self.configure(bg=PANEL, padx=14, pady=12)
        self.resizable(False, False)
        self.transient(app.root)
        self.ifaces = []
        self.fetch_q = queue.Queue()

        def label(text, row):
            tk.Label(self, text=T(text), bg=PANEL, fg=FG, font=FONT, anchor="w").grid(
                row=row, column=0, sticky="w", pady=3, padx=(0, 10))

        def entry(value, row, width=28):
            e = tk.Entry(self, bg=FIELD, fg=FG, insertbackground=FG, relief="flat", font=FONT,
                         width=width, highlightthickness=1, highlightbackground=GRID_STRONG,
                         highlightcolor=ACCENT)
            e.insert(0, str(value))
            e.grid(row=row, column=1, columnspan=2, sticky="we", pady=3)
            return e

        label("Name", 0)
        self.e_name = entry(config_name(app.cfg_path), 0)
        if app.readonly:
            self.e_name.config(state="disabled", disabledbackground=FIELD,
                               disabledforeground=FG_DIM)
        label("Host / IP", 1)
        self.e_host = entry(cfg["host"], 1)
        label("Port", 2)
        self.e_port = entry(cfg["port"], 2)
        tk.Label(self, text="SNMP", bg=PANEL, fg=FG, font=FONT, anchor="nw").grid(
            row=3, column=0, sticky="nw", pady=(5, 3), padx=(0, 10))
        self._build_snmp(cfg, 3)

        tk.Label(self, text="Interface", bg=PANEL, fg=FG, font=FONT, anchor="nw").grid(
            row=4, column=0, sticky="nw", pady=(5, 3), padx=(0, 10))
        icell = tk.Frame(self, bg=PANEL)
        icell.grid(row=4, column=1, sticky="we", pady=3)
        icell.columnconfigure(0, weight=1)
        self.cb = ttk.Combobox(icell, state="readonly", width=34, font=FONT)
        self.cb.grid(row=0, column=0, sticky="we")
        self.v_sum = tk.BooleanVar(value=bool(cfg.get("if_sum")))
        tk.Checkbutton(icell, text=T("Summe mehrerer Interfaces"), variable=self.v_sum,
                       command=self._sum_mode, bg=PANEL, fg=FG, selectcolor=FIELD,
                       activebackground=PANEL, activeforeground=FG, font=FONT,
                       highlightthickness=0).grid(row=1, column=0, sticky="w")
        if cfg["ifindex"]:
            cur = f"{cfg['ifindex']}: {cfg['ifname']}"
            self.cb["values"] = [cur]
            self.cb.set(cur)
        self.cb.bind("<<ComboboxSelected>>", lambda e: self.update_oids())
        self.btn_fetch = self._button("Abfragen", self.fetch)
        self.btn_fetch.grid(row=4, column=2, padx=(6, 0), sticky="nwe", pady=3)

        # OIDs, nur lesbar, aber markier- und kopierbar
        self.oid_labels, self.oid_vars = [], []
        for k, txt in enumerate(("OID In", "OID Out")):
            lb = tk.Label(self, text=txt, bg=PANEL, fg=FG_DIM, font=FONT, anchor="w")
            lb.grid(row=5 + k, column=0, sticky="w", pady=2, padx=(0, 10))
            v = tk.StringVar()
            e = tk.Entry(self, textvariable=v, state="readonly", readonlybackground=PANEL,
                         fg=FG_DIM, relief="flat", font=FONT_MONO, highlightthickness=1,
                         highlightbackground=GRID, highlightcolor=ACCENT)
            e.grid(row=5 + k, column=1, sticky="we", pady=2)
            self._button("Kopieren", lambda v=v: self.copy(v.get())).grid(
                row=5 + k, column=2, padx=(6, 0), sticky="we")
            self.oid_labels.append(lb)
            self.oid_vars.append(v)
            self.oid_rows = getattr(self, "oid_rows", []) + [lb, e]

        # Summe: Ankreuzliste (ersetzt die OID-Zeilen)
        self.f_sum = tk.Frame(self, bg=PANEL)
        lf = tk.Frame(self.f_sum, bg=PANEL)
        lf.pack(side="left", fill="both", expand=True)
        self.lb_sum = tk.Listbox(lf, selectmode="multiple", height=8, activestyle="none",
                                 exportselection=False, bg=FIELD, fg=FG, font=FONT,
                                 selectbackground=ACCENT, selectforeground="white",
                                 highlightthickness=1, highlightbackground=GRID_STRONG, bd=0)
        sb = tk.Scrollbar(lf, command=self.lb_sum.yview)
        self.lb_sum.config(yscrollcommand=sb.set)
        self.lb_sum.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.lb_sum.bind("<<ListboxSelect>>", lambda e: self._sum_count())
        bf = tk.Frame(self.f_sum, bg=PANEL)
        bf.pack(side="left", fill="y", padx=(6, 0))
        self._button("alle", lambda: (self.lb_sum.select_set(0, "end"), self._sum_count()), bf).pack(fill="x")
        self._button("keine", lambda: (self.lb_sum.select_clear(0, "end"), self._sum_count()), bf).pack(fill="x", pady=(4, 0))
        self.lbl_sum = tk.Label(bf, text="", bg=PANEL, fg=FG_DIM, font=FONT_SMALL, justify="left")
        self.lbl_sum.pack(fill="x", pady=(8, 0))
        # gespeicherte Auswahl vorbelegen (Namen aus der Konfiguration)
        self._sum_items = []
        saved = [int(i) for i in (cfg.get("ifindexes") or [])]
        names = list(cfg.get("ifnames") or [])
        for k, idx in enumerate(saved):
            self._sum_items.append(f"{idx}: {names[k] if k < len(names) else ''}".rstrip())
        self._fill_sum_list(saved)

        self._oid_widgets = self.grid_slaves(row=5) + self.grid_slaves(row=6)
        self.after_idle(self._sum_mode)

        label("Intervall (s)", 7)
        self.e_int = entry(f"{cfg['interval']:g}", 7)
        label("Zeitraum (s)", 8)
        self.e_win = entry(cfg["window"], 8)
        self.e_win.grid_configure(columnspan=1)
        tk.Label(self, text=T("auch per Shift+Mausrad oder Kippen"), bg=PANEL, fg=FG_DIM,
                 font=FONT_SMALL).grid(row=8, column=2, sticky="w", padx=(6, 0))

        label("Einheit", 9)
        self.v_unit = tk.StringVar(value=cfg["unit"])
        fr = tk.Frame(self, bg=PANEL)
        fr.grid(row=9, column=1, columnspan=2, sticky="w")
        for val, txt in (("bit", "bit/s"), ("byte", "Byte/s")):
            tk.Radiobutton(fr, text=txt, value=val, variable=self.v_unit, bg=PANEL, fg=FG,
                           selectcolor=FIELD, activebackground=PANEL, activeforeground=FG,
                           font=FONT, highlightthickness=0).pack(side="left", padx=(0, 12))

        label("Farben", 10)
        self.colors = {"color_in": cfg["color_in"], "color_out": cfg["color_out"],
                       "color_label": cfg["color_label"]}
        cf = tk.Frame(self, bg=PANEL)
        cf.grid(row=10, column=1, columnspan=2, sticky="w", pady=3)
        self.swatches = {}
        for key, txt in (("color_in", "In"), ("color_out", "Out"), ("color_label", "Name")):
            tk.Label(cf, text=T(txt), bg=PANEL, fg=FG, font=FONT).pack(side="left", padx=(0, 6))
            b = tk.Button(cf, width=4, relief="flat", bd=0, cursor="hand2",
                          bg=self.colors[key], activebackground=self.colors[key],
                          highlightthickness=1, highlightbackground=GRID_STRONG,
                          command=lambda k=key: self.pick_color(k))
            b.pack(side="left", padx=(0, 18), ipady=1)
            self.swatches[key] = b
        self._button("Standard", self.reset_colors, cf).pack(side="left")

        label("Name im Graph", 11)
        self.v_label = tk.BooleanVar(value=bool(cfg.get("show_label", True)))
        tk.Checkbutton(self, text=T("oben links anzeigen"), variable=self.v_label, bg=PANEL, fg=FG,
                       selectcolor=FIELD, activebackground=PANEL, activeforeground=FG,
                       font=FONT, highlightthickness=0).grid(row=11, column=1, sticky="w")

        def check(var, text, parent=None):
            return tk.Checkbutton(parent or self, text=T(text), variable=var, bg=PANEL, fg=FG,
                                  selectcolor=FIELD, activebackground=PANEL, activeforeground=FG,
                                  disabledforeground=FG_DIM, font=FONT, highlightthickness=0)

        label("Füllung", 12)
        self.v_fill = tk.StringVar(value=cfg.get("fill", "in"))
        ff = tk.Frame(self, bg=PANEL)
        ff.grid(row=12, column=1, columnspan=2, sticky="w")
        for val, txt in (("in", "In"), ("out", "Out"), ("both", "beide"), ("none", "keine")):
            tk.Radiobutton(ff, text=T(txt), value=val, variable=self.v_fill, bg=PANEL, fg=FG,
                           selectcolor=FIELD, activebackground=PANEL, activeforeground=FG,
                           font=FONT, highlightthickness=0).pack(side="left", padx=(0, 12))

        def slider(row, var, lo, hint):
            fr = tk.Frame(self, bg=PANEL)
            fr.grid(row=row, column=1, columnspan=2, sticky="we")
            lbl = tk.Label(fr, text="", bg=PANEL, fg=FG, font=FONT, width=5, anchor="e")
            sc = tk.Scale(fr, from_=lo, to=100, resolution=5, orient="horizontal",
                          showvalue=False, variable=var, command=self._alpha_preview,
                          length=170, width=12, sliderlength=16, bg=FG_DIM, fg=FG,
                          troughcolor=FIELD, highlightthickness=0, bd=0,
                          activebackground=ACCENT, sliderrelief="flat")
            sc.pack(side="left")
            lbl.pack(side="left", padx=(4, 12))
            tk.Label(fr, text=T(hint), bg=PANEL, fg=FG_DIM, font=FONT_SMALL).pack(side="left")
            return fr, sc, lbl

        label("Hintergrund", 13)
        self.v_bga = tk.IntVar(value=int(cfg.get("bg_alpha", 100)))
        _, sc_bg, self.lbl_bga = slider(13, self.v_bga, 0, "nur Hintergrund, Kurven bleiben voll")
        if not bg_supported():
            sc_bg.config(state="disabled")
        label("Deckkraft", 14)
        self.v_alpha = tk.IntVar(value=int(cfg.get("alpha", 100)))
        _, _, self.lbl_alpha = slider(14, self.v_alpha, 20, "ganzes Fenster")
        self.v_hover = tk.BooleanVar(value=bool(cfg.get("alpha_hover", True)))
        check(self.v_hover, "unter der Maus voll deckend").grid(row=15, column=1, columnspan=2,
                                                                 sticky="w")
        self.lbl_alpha.config(text=f"{self.v_alpha.get()} %")
        self.lbl_bga.config(text=f"{self.v_bga.get()} %")

        label("Sprache", 16)
        self.lang_pref = load_settings().get("language", "auto")
        self.cb_lang = ttk.Combobox(self, state="readonly", width=30, font=FONT,
                                    values=[T(t) for _, t in LANG_CHOICES])
        self.cb_lang.set(T(dict(LANG_CHOICES).get(self.lang_pref, LANG_CHOICES[0][1])))
        self.cb_lang.grid(row=16, column=1, sticky="w", pady=(6, 3))

        self.msg = tk.Label(self, text="", bg=PANEL, fg=ERR, font=FONT, anchor="w",
                            wraplength=420, justify="left")
        self.msg.grid(row=17, column=0, columnspan=3, sticky="we", pady=(6, 0))

        tk.Label(self, text=f"{APP_LONG}  ·  Version {VERSION}", bg=PANEL, fg=FG_DIM,
                 font=FONT_SMALL).grid(row=18, column=0, columnspan=2, sticky="sw", pady=(10, 0))
        btns = tk.Frame(self, bg=PANEL)
        btns.grid(row=18, column=1, columnspan=2, sticky="e", pady=(10, 0))
        self.update_oids()
        if self._pw_err:
            self.msg.config(text=self._pw_err, fg=ERR)
        self._button("Abbrechen", self.cancel, btns).pack(side="right", padx=(6, 0))
        ok = self._button("OK", self.ok, btns)
        ok.configure(bg=ACCENT, fg="white")
        ok.pack(side="right")

        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        # bestehende Konfiguration: Interface-Liste gleich im Hintergrund laden
        if cfg.get("host") and not self._pw_err:
            self.after(150, lambda: self.fetch(auto=True))
        dark_titlebar(self)
        self.update_idletasks()
        x = app.root.winfo_rootx() + 40
        y = app.root.winfo_rooty() + 30
        # ganz auf den Monitor des Hauptfensters (Rahmen/Titelleiste grob dazugerechnet)
        w, h = self.winfo_reqwidth() + 16, self.winfo_reqheight() + 40
        rx, ry = app.root.winfo_rootx(), app.root.winfo_rooty()
        area = work_area(self, (rx, ry, rx + app.root.winfo_width(), ry + app.root.winfo_height()))
        x, y = fit_rect(x, y, w, h, area)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.e_host.focus_set()

    def _build_snmp(self, cfg, row):
        """SNMP-Version mit Community (v2c) bzw. Benutzer/Anmeldung/Verschluesselung (v3)."""
        fr = tk.Frame(self, bg=PANEL)
        fr.grid(row=row, column=1, columnspan=2, sticky="we", pady=3)
        fr.columnconfigure(2, weight=1)

        def ent(parent, value="", width=24, show=None):
            e = tk.Entry(parent, bg=FIELD, fg=FG, insertbackground=FG, relief="flat", font=FONT,
                         width=width, highlightthickness=1, highlightbackground=GRID_STRONG,
                         highlightcolor=ACCENT, show=show or "", disabledbackground=PANEL,
                         disabledforeground=FG_DIM)
            e.insert(0, value)
            return e

        self.v_ver = tk.StringVar(value="3" if str(cfg.get("snmp_version")) == "3" else "2c")
        rb = tk.Frame(fr, bg=PANEL)
        rb.grid(row=0, column=0, columnspan=3, sticky="w")
        for val, txt in (("2c", "Version 2c (Community)"), ("3", "Version 3 (Benutzer, verschlüsselt)")):
            tk.Radiobutton(rb, text=T(txt), value=val, variable=self.v_ver, command=self._snmp_mode,
                           bg=PANEL, fg=FG, selectcolor=FIELD, activebackground=PANEL,
                           activeforeground=FG, font=FONT, highlightthickness=0).pack(side="left", padx=(0, 12))

        def lab(parent, text, r):
            tk.Label(parent, text=T(text), bg=PANEL, fg=FG_DIM, font=FONT, anchor="w").grid(
                row=r, column=0, sticky="w", padx=(0, 8), pady=2)

        self.f_v2 = tk.Frame(fr, bg=PANEL)
        lab(self.f_v2, "Community", 0)
        self.e_comm = ent(self.f_v2, cfg.get("community", ""), 28)
        self.e_comm.grid(row=0, column=1, sticky="we", pady=2)

        self.f_v3 = tk.Frame(fr, bg=PANEL)
        self.f_v3.columnconfigure(2, weight=1)
        pw_err = ""
        try:
            apw = reveal_secret(cfg.get("v3_auth_pw", ""))
            ppw = reveal_secret(cfg.get("v3_priv_pw", ""))
        except SnmpError as e:
            apw = ppw = ""
            pw_err = str(e)
        lab(self.f_v3, "Benutzer", 0)
        self.e_v3user = ent(self.f_v3, cfg.get("v3_user", ""), 24)
        self.e_v3user.grid(row=0, column=1, columnspan=2, sticky="we", pady=2)
        lab(self.f_v3, "Anmeldung", 1)
        self.cb_auth = ttk.Combobox(self.f_v3, state="readonly", width=9, font=FONT,
                                    values=[T(x) for x in V3_AUTH_CHOICES])
        self.cb_auth.set(T(cfg.get("v3_auth") if cfg.get("v3_auth") in V3_AUTH_CHOICES else "SHA-256"))
        self.cb_auth.grid(row=1, column=1, sticky="w", pady=2)
        self.e_authpw = ent(self.f_v3, apw, 20, show="•")
        self.e_authpw.grid(row=1, column=2, sticky="we", padx=(6, 0), pady=2)
        lab(self.f_v3, "Verschlüsselung", 2)
        self.cb_priv = ttk.Combobox(self.f_v3, state="readonly", width=9, font=FONT,
                                    values=[T(x) for x in V3_PRIV_CHOICES])
        self.cb_priv.set(T(cfg.get("v3_priv") if cfg.get("v3_priv") in V3_PRIV_CHOICES else "AES-128"))
        self.cb_priv.grid(row=2, column=1, sticky="w", pady=2)
        self.e_privpw = ent(self.f_v3, ppw, 20, show="•")
        self.e_privpw.grid(row=2, column=2, sticky="we", padx=(6, 0), pady=2)
        self.v_showpw = tk.BooleanVar(value=False)
        tk.Checkbutton(self.f_v3, text=T("Passwörter anzeigen"), variable=self.v_showpw,
                       command=lambda: [e.config(show="" if self.v_showpw.get() else "•")
                                        for e in (self.e_authpw, self.e_privpw)],
                       bg=PANEL, fg=FG_DIM, selectcolor=FIELD, activebackground=PANEL,
                       activeforeground=FG, font=FONT_SMALL, highlightthickness=0).grid(
            row=3, column=1, columnspan=2, sticky="w")
        for c in (self.cb_auth, self.cb_priv):
            c.bind("<<ComboboxSelected>>", lambda e: self._snmp_mode())
        self._pw_err = pw_err
        self._snmp_mode()

    def _snmp_mode(self):
        v3 = self.v_ver.get() == "3"
        (self.f_v3 if v3 else self.f_v2).grid(row=1, column=0, columnspan=3, sticky="we", pady=(2, 0))
        (self.f_v2 if v3 else self.f_v3).grid_remove()
        auth = self._cbv(self.cb_auth) != "keine"
        if not auth:
            self.cb_priv.set(T("keine"))
        self.e_authpw.config(state="normal" if auth else "disabled")
        self.cb_priv.config(state="readonly" if auth else "disabled")
        self.e_privpw.config(state="normal" if auth and self._cbv(self.cb_priv) != "keine" else "disabled")

    @staticmethod
    def _cbv(cb):
        """Wert einer Auswahlliste – angezeigt wird ggf. die Uebersetzung von „keine“."""
        v = cb.get()
        return "keine" if v == T("keine") else v

    def snmp_values(self):
        """(Konfigurationswerte, Klartext-Passwoerter) oder Fehlertext."""
        if self.v_ver.get() != "3":
            return {"snmp_version": "2c", "community": self.e_comm.get()}, ("", "")
        user = self.e_v3user.get().strip()
        auth, priv = self._cbv(self.cb_auth), self._cbv(self.cb_priv)
        apw = self.e_authpw.get() if auth != "keine" else ""
        ppw = self.e_privpw.get() if auth != "keine" and priv != "keine" else ""
        if not user:
            return T("SNMPv3: Benutzername fehlt.")
        if auth != "keine" and len(apw) < 8:
            return T("SNMPv3: Auth-Passwort muss mindestens 8 Zeichen haben.")
        if priv != "keine" and auth != "keine" and len(ppw) < 8:
            return T("SNMPv3: Priv-Passwort muss mindestens 8 Zeichen haben.")
        return ({"snmp_version": "3", "community": self.e_comm.get(), "v3_user": user,
                 "v3_auth": auth, "v3_priv": priv if auth != "keine" else "keine"}, (apw, ppw))

    def _fill_sum_list(self, selected):
        lb = self.lb_sum
        lb.delete(0, "end")
        for t in self._sum_items:
            lb.insert("end", t)
        sel = {int(i) for i in selected}
        for k, t in enumerate(self._sum_items):
            if int(t.split(":")[0]) in sel:
                lb.select_set(k)
        self._sum_count()

    def _sum_count(self):
        n = len(self.lb_sum.curselection())
        self.lbl_sum.config(text=T("{n} gewählt", n=n))

    def sum_selection(self):
        """[(index, name)] der angekreuzten Interfaces."""
        out = []
        for k in self.lb_sum.curselection():
            t = self._sum_items[k]
            idx = int(t.split(":")[0])
            name = next((n for i, n, _ in self.ifaces if i == idx),
                        t.split(":", 1)[1].split("  (")[0].strip())
            out.append((idx, name))
        return out

    def _sum_mode(self):
        on = self.v_sum.get()
        if on:
            for w in self.oid_rows:
                w.grid_remove()
            for w in self.grid_slaves(row=5) + self.grid_slaves(row=6):
                if w is not self.f_sum:
                    w.grid_remove()
            self.f_sum.grid(row=5, column=0, rowspan=2, columnspan=3, sticky="nsew", pady=(2, 4))
            self.cb.config(state="disabled")
            if not self._sum_items:
                self.msg.config(text=T("Zum Auswählen erst „Abfragen“ klicken."), fg=FG_DIM)
        else:
            self.f_sum.grid_remove()
            for w in self._oid_widgets:
                w.grid()
            self.cb.config(state="readonly")

    def _alpha_preview(self, _=None):
        """Deckkraft und Hintergrund beim Schieben gleich am Fenster zeigen."""
        self.lbl_alpha.config(text=f"{self.v_alpha.get()} %")
        self.lbl_bga.config(text=f"{self.v_bga.get()} %")
        self.app._alpha_preview = True
        self.app.apply_look(self.v_alpha.get(), self.v_bga.get())

    def cancel(self):
        if getattr(self.app, "_alpha_preview", False):
            self.app._alpha_preview = False
            self.app.apply_look()                     # Vorschau zuruecknehmen
        self.destroy()

    def _button(self, text, cmd, parent=None):
        return tk.Button(parent or self, text=T(text), command=cmd, bg=FIELD, fg=FG, relief="flat",
                         activebackground=ACCENT, activeforeground="white", font=FONT,
                         padx=12, pady=3, bd=0, cursor="hand2")

    def selected_index(self):
        try:
            return int(self.cb.get().split(":")[0])
        except ValueError:
            return 0

    def update_oids(self):
        idx = self.selected_index()
        app = self.app
        if not idx:
            kind, oids = "", ["", ""]
        elif idx == app.cfg["ifindex"] and app.oids:
            kind, oids = app.info, app.oids          # tatsaechlich abgefragt
        else:
            kind, oids = "64-Bit", [f"{OID_IN64}.{idx}", f"{OID_OUT64}.{idx}"]
        for lb, v, base, o in zip(self.oid_labels, self.oid_vars, ("OID In", "OID Out"), oids):
            lb.config(text=f"{base} ({kind})" if kind else base)
            v.set(o)

    def pick_color(self, key):
        from tkinter import colorchooser
        _, hx = colorchooser.askcolor(color=self.colors[key], parent=self,
                                      title=T("Farbe für {x}", x=T({"color_in": "In", "color_out": "Out",
                                                                     "color_label": "Name"}[key])))
        if hx:
            self.set_color(key, hx)

    def set_color(self, key, hx):
        self.colors[key] = hx
        self.swatches[key].config(bg=hx, activebackground=hx)

    def reset_colors(self):
        for k in ("color_in", "color_out", "color_label"):
            self.set_color(k, DEFAULTS[k])

    def copy(self, text):
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.msg.config(text=T("Kopiert: {x}", x=text), fg=FG_DIM)

    def fetch(self, auto=False):
        host = self.e_host.get().strip()
        if not host:
            if not auto:
                self.msg.config(text=T("Bitte zuerst Host angeben."))
            return
        try:
            port = int(self.e_port.get())
        except ValueError:
            self.msg.config(text=T("Port ist keine Zahl."))
            return
        sv = self.snmp_values()
        if isinstance(sv, str):
            if not auto:
                self.msg.config(text=sv, fg=ERR)
            return
        vals, secrets = sv
        ccfg = dict(vals, host=host, port=port)
        self.btn_fetch.config(state="disabled", text="…")
        self.msg.config(text=T("Frage Interfaces ab …"), fg=FG_DIM)

        def worker():
            client = None
            try:
                client = make_client(ccfg, timeout=2.0, retries=1, secrets=secrets)
                self.fetch_q.put(("ok", list_interfaces(client)))
            except Exception as e:
                self.fetch_q.put(("err", str(e)))
            finally:
                if client:
                    client.close()

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._check_fetch)

    def _check_fetch(self):
        if not self.winfo_exists():
            return
        try:
            kind, payload = self.fetch_q.get_nowait()
        except queue.Empty:
            self.after(100, self._check_fetch)
            return
        self.btn_fetch.config(state="normal", text=T("Abfragen"))
        if kind == "err":
            self.msg.config(text=payload, fg=ERR)
            return
        self.ifaces = payload
        values = []
        for idx, name, alias in payload:
            t = f"{idx}: {name}"
            if alias and alias != name:
                t += f"  ({alias})"
            values.append(t)
        self.cb["values"] = values
        cur = self.app.cfg["ifindex"]
        pick = next((v for v in values if v.split(":")[0] == str(cur)), values[0])
        self.cb.set(pick)
        self.update_oids()
        keep = [i for i, _ in self.sum_selection()] if self._sum_items else \
            [int(i) for i in (self.app.cfg.get("ifindexes") or [])]
        self._sum_items = values
        self._fill_sum_list(keep)
        self.msg.config(text=T("{n} Interfaces gefunden.", n=len(values)), fg=FG_DIM)

    def ok(self):
        try:
            port = int(self.e_port.get())
            interval = float(self.e_int.get().replace(",", "."))
            window = int(float(self.e_win.get().replace(",", ".")))
        except ValueError:
            self.msg.config(text=T("Port, Intervall und Zeitraum müssen Zahlen sein."), fg=ERR)
            return
        host = self.e_host.get().strip()
        sel = self.cb.get()
        summe = self.sum_selection() if self.v_sum.get() else []
        if self.v_sum.get() and not summe:
            self.msg.config(text=T("Für die Summe mindestens ein Interface ankreuzen."), fg=ERR)
            return
        if summe and not sel:
            sel = f"{summe[0][0]}: {summe[0][1]}"
        if not host or not sel:
            self.msg.config(text=T("Host und Interface müssen gesetzt sein."), fg=ERR)
            return
        sv = self.snmp_values()
        if isinstance(sv, str):
            self.msg.config(text=sv, fg=ERR)
            return
        snmp_cfg, (apw, ppw) = sv
        if snmp_cfg["snmp_version"] == "3":          # bei v2c bleiben die v3-Angaben erhalten
            snmp_cfg["v3_auth_pw"] = protect_secret(apw)
            snmp_cfg["v3_priv_pw"] = protect_secret(ppw)
        if interval < 0.2 or window < 10 or window / interval > 20000:
            self.msg.config(text=T("Intervall ≥ 0,2 s, Zeitraum ≥ 10 s, höchstens 20000 Messpunkte."), fg=ERR)
            return
        name = self.e_name.get().strip()
        cur_name = config_name(self.app.cfg_path)
        if not self.app.readonly and name.lower() != cur_name.lower():
            if not valid_name(name):
                self.msg.config(text=T("Name: 1–40 Zeichen, nur Buchstaben, Ziffern, "
                                       "Leerzeichen, - und _."), fg=ERR)
                return
            new_path = os.path.join(os.path.dirname(self.app.cfg_path), name + ".json")
            if os.path.exists(new_path):
                self.msg.config(text=T("Eine Konfiguration „{name}“ gibt es schon.", name=name), fg=ERR)
                return
            lock = acquire_lock(new_path)
            if lock is None:
                self.msg.config(text=T("„{name}“ ist gerade in einem anderen Fenster offen.", name=name), fg=ERR)
                return
            err = self.app.rename_config(new_path, lock)
            if err:
                self.msg.config(text=err, fg=ERR)
                return
        idx = int(sel.split(":")[0])
        name = next((n for i, n, _ in self.ifaces if i == idx),
                    sel.split(":", 1)[1].split("  (")[0].strip())
        if summe:
            idx, name = summe[0][0], T("Summe {n} Interfaces", n=len(summe))
        self.app.apply_settings({
            **snmp_cfg,
            "if_sum": bool(summe), "ifindexes": [i for i, _ in summe] if summe else
            list(self.app.cfg.get("ifindexes") or []),
            "ifnames": [n for _, n in summe] if summe else list(self.app.cfg.get("ifnames") or []),
            "host": host, "port": port, "community": self.e_comm.get(),
            "ifindex": idx, "ifname": name, "interval": interval, "window": window,
            "unit": self.v_unit.get(),
            "color_in": self.colors["color_in"], "color_out": self.colors["color_out"],
            "color_label": self.colors["color_label"], "show_label": self.v_label.get(),
            "fill": self.v_fill.get(), "alpha": int(self.v_alpha.get()),
            "alpha_hover": self.v_hover.get(), "bg_alpha": int(self.v_bga.get()),
        })
        self.app._alpha_preview = False
        self.app.apply_look()
        lang = next((k for k, t in LANG_CHOICES if T(t) == self.cb_lang.get()), "auto")
        self.destroy()
        if lang != self.lang_pref:
            st = load_settings()
            st["language"] = lang
            if not save_settings(st):
                write_log(self.app.cfg_path, f"Sprache: {lang} – Fenster startet neu")
                self.app.restart()


# ====================================================================
def setup_style(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG,
                    arrowcolor=FG, bordercolor=GRID_STRONG, lightcolor=FIELD, darkcolor=FIELD,
                    selectbackground=FIELD, selectforeground=FG)
    style.map("TCombobox",
              fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
              selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)],
              background=[("active", GRID_STRONG)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "white")
    root.option_add("*TCombobox*Listbox.font", FONT)


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            # eigene Kennung: Taskleiste zeigt das FTG-Symbol statt Python
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FTG.TrafficGrapher")
        except Exception:
            pass
    init_lang()
    cfg_path = resolve_config_path(sys.argv[1] if len(sys.argv) > 1 else "")
    root = tk.Tk()
    apply_app_icon(root)
    setup_style(root)

    def on_error(exc, val, tb):
        # pythonw hat keine Konsole – Fehler sonst unsichtbar
        import traceback
        from tkinter import messagebox
        text = "".join(traceback.format_exception(exc, val, tb))
        write_log(cfg_path, "FEHLER\n" + text)
        messagebox.showerror(APP, T("Interner Fehler:\n\n{val}\n\nDetails stehen in {log}", val=val, log=LOGNAME))

    root.report_callback_exception = on_error
    app = App(root, cfg_path)
    if app.cfg["borderless"]:
        app.apply_borderless()          # setzt auch Tray/Taskleiste
    else:
        dark_titlebar(root)
        app.apply_tray()
    root.after(400, lambda: app.ensure_on_screen("Start"))
    root.mainloop()


if __name__ == "__main__":
    main()
