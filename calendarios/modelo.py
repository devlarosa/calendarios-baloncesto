"""Modelo común de partido, utilidades y exportadores (CSV, JSON, ICS)."""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

MADRID = ZoneInfo("Europe/Madrid")
USER_AGENT = "Mozilla/5.0 (compatible; calendarios-baloncesto/1.0)"


@dataclass
class Partido:
    id: int
    temporada: str
    competicion: str
    grupo: str
    jornada: str
    fecha: str | None          # ISO 8601 con zona horaria si se conoce la hora; solo fecha si no
    local: str
    local_id: int | None
    visitante: str
    visitante_id: int | None
    puntos_local: int | None
    puntos_visitante: int | None
    jugado: bool
    condicion: str             # "Local" / "Visitante" respecto al equipo buscado
    rival: str
    resultado: str             # "V" / "D" / "" respecto al equipo buscado
    pabellon: str
    url: str
    uid: str = ""              # identificador único del evento en el ICS
    notas: str = ""            # texto extra para la descripción del evento (p.ej. canales de TV)


# ---------------------------------------------------------------------------------------- utilidades
def sesion() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def norm(s: str) -> str:
    """Mayúsculas sin acentos ni espacios repetidos, para comparar nombres de equipos."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(s).lower()).strip("-")


def temporada_actual() -> int:
    """Año de inicio de la temporada en curso: desde agosto, la que empieza ese año."""
    hoy = datetime.now(MADRID)
    return hoy.year if hoy.month >= 8 else hoy.year - 1


def resultado(es_local: bool, pl: int | None, pv: int | None) -> str:
    if pl is None or pv is None:
        return ""
    propios, ajenos = (pl, pv) if es_local else (pv, pl)
    return "V" if propios > ajenos else "D"


def incluir(es_local: bool, solo: str | None) -> bool:
    """Filtro de condición: solo='casa', 'fuera' o None (todos)."""
    return solo is None or (solo == "casa") == es_local


# --------------------------------------------------------------------------------------- exportadores
def exportar_csv(partidos: list[Partido], ruta: Path):
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel abre bien los acentos
        w = csv.DictWriter(f, fieldnames=list(asdict(partidos[0]).keys()), delimiter=";")
        w.writeheader()
        w.writerows(asdict(p) for p in partidos)


def exportar_json(partidos: list[Partido], ruta: Path):
    ruta.write_text(json.dumps([asdict(p) for p in partidos], ensure_ascii=False, indent=2), encoding="utf-8")


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def _ics_plegar(linea: str, maximo: int = 75) -> str:
    """Parte las líneas de más de 75 octetos (RFC 5545 §3.1) sin cortar caracteres UTF-8.

    Las continuaciones empiezan por un espacio, que cuenta dentro de su límite."""
    trozos, actual, tam = [], "", 0
    for c in linea:
        n = len(c.encode("utf-8"))
        if tam + n > maximo:
            trozos.append(actual)
            actual, tam = " ", 1
        actual += c
        tam += n
    trozos.append(actual)
    return "\r\n".join(trozos)


def exportar_ics(partidos: list[Partido], ruta: Path, nombre_cal: str, duracion_min: int = 120,
                 aviso_min: int | list[int] = 0, prefijo_competicion: bool = False):
    """aviso_min: minutos de antelación de cada recordatorio (un número o una lista; 0 = sin aviso)."""
    avisos = [a for a in (aviso_min if isinstance(aviso_min, list) else [aviso_min]) if a > 0]
    ahora = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//calendarios-baloncesto//ES", "CALSCALE:GREGORIAN",
              f"X-WR-CALNAME:{_ics_escape(nombre_cal)}", "X-WR-TIMEZONE:Europe/Madrid"]
    for p in partidos:
        if not p.fecha:
            continue
        titulo = f"{p.local} - {p.visitante}"
        if p.jugado:
            titulo = f"{p.local} {p.puntos_local}-{p.puntos_visitante} {p.visitante}"
        if prefijo_competicion:
            titulo = f"[{p.competicion}] {titulo}"
        lineas += ["BEGIN:VEVENT", f"UID:{p.uid or f'partido-{p.id}'}", f"DTSTAMP:{ahora}"]
        if "T" in p.fecha:
            ini = datetime.fromisoformat(p.fecha).astimezone(timezone.utc)
            fin = ini + timedelta(minutes=duracion_min)
            lineas += [f"DTSTART:{ini:%Y%m%dT%H%M%SZ}", f"DTEND:{fin:%Y%m%dT%H%M%SZ}"]
        else:  # sin hora confirmada: evento de día completo
            d = datetime.fromisoformat(p.fecha).date()
            lineas += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"]
            titulo += " (hora por confirmar)"
        desc = " - ".join(x for x in (f"{p.competicion} {p.temporada}", p.grupo, p.jornada) if x)
        if p.notas:
            desc += f"\n{p.notas}"
        if p.url:
            desc += f"\n{p.url}"
        lineas += [f"SUMMARY:{_ics_escape(titulo)}", f"DESCRIPTION:{_ics_escape(desc)}"]
        if p.pabellon:
            lineas.append(f"LOCATION:{_ics_escape(p.pabellon)}")
        if p.url:
            lineas.append(f"URL:{p.url}")
        for aviso in ([] if p.jugado else avisos):
            lineas += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(titulo)}",
                       f"TRIGGER:-PT{aviso}M", "END:VALARM"]
        lineas.append("END:VEVENT")
    lineas.append("END:VCALENDAR")
    ruta.write_bytes(("\r\n".join(_ics_plegar(l) for l in lineas) + "\r\n").encode("utf-8"))
