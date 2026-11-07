#!/usr/bin/env python3
"""Genera los calendarios definidos en calendarios.json (FEB, ACB, Euroliga) en CSV, JSON e ICS.

Ejemplos:
    python calendario.py                              # todos los calendarios -> ./salida
    python calendario.py real_madrid                  # solo uno (por su 'archivo')
    python calendario.py --formatos ics --salida docs # lo que hace la tarea programada
    python calendario.py --temporada 2025             # otra temporada
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from calendarios import FUENTES
from calendarios.modelo import exportar_csv, exportar_ics, exportar_json, temporada_actual


def generar(cal: dict, temporada: int, salida: Path, formatos: set[str], detalles: bool) -> bool:
    partidos = []
    for f in cal["fuentes"]:
        opciones = {k: v for k, v in f.items() if k not in ("fuente", "equipo")}
        if f["fuente"] == "feb":
            opciones["detalles"] = detalles
        fuente = FUENTES[f["fuente"]]()
        nuevos = fuente.partidos(f["equipo"], temporada, solo=cal.get("solo"), **opciones)
        if not nuevos:
            print(f"Aviso: {f['fuente']} no devuelve partidos de '{f['equipo']}'.", file=sys.stderr)
        partidos += nuevos
    if not partidos:
        print(f"ERROR: el calendario '{cal['archivo']}' no tiene partidos.", file=sys.stderr)
        return False
    partidos.sort(key=lambda p: p.fecha or "")

    base = salida / cal["archivo"]
    if "csv" in formatos:
        exportar_csv(partidos, base.with_suffix(".csv"))
    if "json" in formatos:
        exportar_json(partidos, base.with_suffix(".json"))
    if "ics" in formatos:
        competiciones = sorted({p.competicion for p in partidos})
        nombre = f"{cal['nombre']} - {' y '.join(competiciones)} {temporada}/{temporada + 1}"
        exportar_ics(partidos, base.with_suffix(".ics"), nombre, aviso_min=cal.get("aviso", 0),
                     prefijo_competicion=len(competiciones) > 1)

    print(f"\n== {cal['nombre']} ({cal['archivo']}): {len(partidos)} partidos")
    for comp in sorted({p.competicion for p in partidos}):
        ps = [p for p in partidos if p.competicion == comp]
        print(f"   {comp:<20} {len(ps):>3} partidos, balance "
              f"{sum(p.resultado == 'V' for p in ps)}V-{sum(p.resultado == 'D' for p in ps)}D")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Genera calendarios de baloncesto (FEB, ACB, Euroliga).")
    ap.add_argument("calendarios", nargs="*", help="'archivo' de los calendarios a generar (def.: todos)")
    ap.add_argument("--config", default=Path(__file__).with_name("calendarios.json"), type=Path)
    ap.add_argument("--temporada", type=int, default=temporada_actual(), help="Año de inicio, p.ej. 2026 = 2026/2027")
    ap.add_argument("--formatos", default="csv,json,ics", help="Lista separada por comas: csv,json,ics")
    ap.add_argument("--salida", default="salida", type=Path, help="Carpeta de salida (def.: ./salida)")
    ap.add_argument("--sin-detalles", action="store_true",
                    help="FEB: no entrar en cada partido (más rápido, sin hora de los jugados ni pabellón)")
    args = ap.parse_args(argv)

    config = json.loads(args.config.read_text(encoding="utf-8"))["calendarios"]
    elegidos = [c for c in config if not args.calendarios or c["archivo"] in args.calendarios]
    if args.calendarios and len(elegidos) != len(args.calendarios):
        conocidos = ", ".join(c["archivo"] for c in config)
        raise SystemExit(f"Calendario desconocido. Disponibles: {conocidos}")

    args.salida.mkdir(parents=True, exist_ok=True)
    formatos = {f.strip().lower() for f in args.formatos.split(",")}
    ok = [generar(c, args.temporada, args.salida, formatos, not args.sin_detalles) for c in elegidos]
    print(f"\nFicheros en {args.salida.resolve()}/")
    if not all(ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
