from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")
    return pd.read_csv(ruta)


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")


def rango_archivo(nombre: str, ruta: Path, columna_fecha: str) -> dict[str, object]:
    df = leer_csv(ruta)
    fechas = pd.to_datetime(df[columna_fecha], errors="coerce").dropna()
    out: dict[str, object] = {
        "fuente": nombre,
        "archivo": str(ruta),
        "filas": len(df),
        "columnas": len(df.columns),
        "fecha_inicio": str(fechas.min().date()) if not fechas.empty else "",
        "fecha_fin": str(fechas.max().date()) if not fechas.empty else "",
        "fechas_unicas": int(fechas.nunique()),
    }
    if "afp" in df.columns:
        out["afps"] = ", ".join(sorted(df["afp"].dropna().astype(str).unique()))
    return out


def particion_602020(fechas: pd.Series) -> pd.DataFrame:
    fechas_unicas = (
        pd.to_datetime(fechas, errors="coerce")
        .dropna()
        .drop_duplicates()
        .sort_values()
        .reset_index(drop=True)
    )
    n = len(fechas_unicas)
    if n < 10:
        raise ValueError("No hay suficientes fechas para particion temporal.")

    i_train = int(n * 0.60)
    i_valid = int(n * 0.80)

    bloques = [
        ("entrenamiento", 0, i_train),
        ("validacion", i_train, i_valid),
        ("test_final", i_valid, n),
    ]
    rows = []
    for nombre, ini, fin in bloques:
        parte = fechas_unicas.iloc[ini:fin]
        rows.append(
            {
                "bloque": nombre,
                "fecha_inicio": str(parte.min().date()),
                "fecha_fin": str(parte.max().date()),
                "fechas": int(len(parte)),
                "porcentaje": round(len(parte) / n * 100.0, 2),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    fuentes = [
        (
            "cartera_detallada_ca0001",
            processed / "ca0001_fondo3_hoja10_base_canonica_reconciliada.csv",
            "fecha_cartera",
        ),
        (
            "cartera_economica_fp1356",
            processed / "fp1356_cartera_economica_detalle_v2.csv",
            "fecha_cartera",
        ),
        (
            "cuota_sbs",
            processed / "sbs_fondo3_base_maestra.csv",
            "fecha",
        ),
        (
            "mercados",
            processed / "mercados_precios_ajustados.csv",
            "fecha",
        ),
        (
            "pesos_diarios_aplicados",
            processed / "fondo3_pesos_diarios_aplicados.csv",
            "fecha",
        ),
    ]

    disponibilidad = pd.DataFrame(
        [rango_archivo(nombre, ruta, fecha) for nombre, ruta, fecha in fuentes]
    )

    pesos = leer_csv(processed / "fondo3_pesos_diarios_aplicados.csv")
    particion = particion_602020(pesos["fecha"])

    escribir_csv(
        disponibilidad,
        processed / "cartera_replicante_disponibilidad_datos.csv",
    )
    escribir_csv(
        particion,
        processed / "cartera_replicante_particion_temporal_602020.csv",
    )

    manifiesto = {
        "proyecto": "cartera_replicante_intradia",
        "criterio_particion": "60% entrenamiento, 20% validacion, 20% test final, siempre en orden temporal",
        "archivo_base_particion": "fondo3_pesos_diarios_aplicados.csv",
        "particion": particion.to_dict(orient="records"),
        "nota": "No se mezclan fechas al azar porque es serie de tiempo.",
    }
    (processed / "cartera_replicante_particion_temporal_602020.json").write_text(
        json.dumps(manifiesto, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Disponibilidad de datos")
    print(disponibilidad.to_string(index=False))
    print("\nParticion temporal 60/20/20")
    print(particion.to_string(index=False))


if __name__ == "__main__":
    main()

