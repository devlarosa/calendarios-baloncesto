#!/usr/bin/env python3
"""Genera los calendarios escolares de escolar.json en ICS (eventos de día completo).

    python escolar.py --salida docs
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from calendarios.modelo import _ics_escape, _ics_plegar, slug


def exportar(cal: dict, ruta: Path):
    ahora = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//calendarios-baloncesto//ES", "CALSCALE:GREGORIAN",
              f"X-WR-CALNAME:{_ics_escape(cal['nombre'])}", "X-WR-TIMEZONE:Europe/Madrid"]
    for ev in cal["eventos"]:
        ini = date.fromisoformat(ev["desde"])
        fin = date.fromisoformat(ev.get("hasta", ev["desde"])) + timedelta(days=1)  # DTEND no incluido
        desc = "\n".join(x for x in (ev.get("nota", ""), f"Fuente: {cal['fuente']}") if x)
        uid = f"{cal['archivo']}-{ini:%Y%m%d}-{fin:%Y%m%d}-{slug(ev['titulo'])}@calendarios-baloncesto"
        lineas += ["BEGIN:VEVENT", f"UID:{uid}",
                   f"DTSTAMP:{ahora}", f"DTSTART;VALUE=DATE:{ini:%Y%m%d}", f"DTEND;VALUE=DATE:{fin:%Y%m%d}",
                   f"SUMMARY:{_ics_escape(ev['titulo'])}", f"DESCRIPTION:{_ics_escape(desc)}",
                   "TRANSP:TRANSPARENT", "END:VEVENT"]
    lineas.append("END:VCALENDAR")
    ruta.write_bytes(("\r\n".join(_ics_plegar(l) for l in lineas) + "\r\n").encode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=Path(__file__).with_name("escolar.json"), type=Path)
    ap.add_argument("--salida", default="salida", type=Path)
    args = ap.parse_args(argv)
    args.salida.mkdir(parents=True, exist_ok=True)
    for cal in json.loads(args.config.read_text(encoding="utf-8"))["calendarios"]:
        exportar(cal, args.salida / f"{cal['archivo']}.ics")
        print(f"{cal['nombre']}: {len(cal['eventos'])} eventos -> {args.salida / cal['archivo']}.ics")


if __name__ == "__main__":
    main()
