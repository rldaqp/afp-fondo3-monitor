from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import pandas as pd


PALABRAS_ENCABEZADO = [
    "afp",
    "habitat",
    "integra",
    "prima",
    "profuturo",
    "fondo",
    "tipo 3",
    "emisor",
    "instrumento",
    "moneda",
    "pais",
    "país",
    "isin",
    "nemonico",
    "nemónico",
    "monto",
    "valor",
    "participacion",
    "participación",
    "administradora",
    "fondo mutuo",
    "etf",
]


def preparar_excel(archivo: Path) -> tuple[BytesIO, str]:
    contenido = archivo.read_bytes()

    if contenido.startswith(b"PK"):
        return BytesIO(contenido), "openpyxl"

    if contenido.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return BytesIO(contenido), "xlrd"

    raise ValueError(
        f"{archivo.name} no es un XLS/XLSX reconocido."
    )


def normalizar(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def periodo_desde_nombre(nombre: str) -> tuple[int, int]:
    codigos = {
        "en": 1,
        "fe": 2,
        "ma": 3,
        "ab": 4,
        "my": 5,
        "jn": 6,
        "jl": 7,
        "ag": 8,
        "se": 9,
        "oc": 10,
        "no": 11,
        "di": 12,
    }

    coincidencia = re.search(
        r"CA-0001-([a-z]{2})(20\d{2})",
        nombre.lower(),
    )

    if not coincidencia:
        return (0, 0)

    codigo = coincidencia.group(1)
    anio = int(coincidencia.group(2))
    return anio, codigos.get(codigo, 0)


def leer_hoja(
    archivo: Path,
    hoja: str,
) -> pd.DataFrame:
    fuente, motor = preparar_excel(archivo)

    tabla = pd.read_excel(
        fuente,
        sheet_name=hoja,
        header=None,
        engine=motor,
    )

    tabla = tabla.dropna(how="all").dropna(axis=1, how="all")
    return tabla.reset_index(drop=True)


def puntuar_filas(
    tabla: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for indice, fila in tabla.iterrows():
        valores = [
            normalizar(valor)
            for valor in fila.tolist()
        ]
        texto = " | ".join(valores).lower()

        detectadas = [
            palabra
            for palabra in PALABRAS_ENCABEZADO
            if palabra in texto
        ]

        celdas_no_vacias = sum(bool(valor) for valor in valores)
        puntaje = len(detectadas) + min(celdas_no_vacias, 10) * 0.1

        filas.append(
            {
                "fila_python": indice,
                "fila_excel_aprox": indice + 1,
                "puntaje": puntaje,
                "celdas_no_vacias": celdas_no_vacias,
                "palabras_detectadas": " | ".join(detectadas),
                "texto_fila": texto,
            }
        )

    return pd.DataFrame(filas).sort_values(
        ["puntaje", "celdas_no_vacias", "fila_python"],
        ascending=[False, False, True],
    )


def vista_contexto(
    tabla: pd.DataFrame,
    fila_candidata: int,
    antes: int = 5,
    despues: int = 18,
) -> pd.DataFrame:
    inicio = max(0, fila_candidata - antes)
    fin = min(len(tabla), fila_candidata + despues + 1)

    vista = tabla.iloc[inicio:fin].copy()
    vista.columns = [
        f"C{numero}"
        for numero in range(1, len(vista.columns) + 1)
    ]
    vista.insert(
        0,
        "fila_excel_aprox",
        range(inicio + 1, fin + 1),
    )

    for columna in vista.columns:
        vista[columna] = vista[columna].map(normalizar)

    return vista


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    raw = raiz / "data" / "raw" / "sbs" / "ca0001_composicion"
    processed = raiz / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    ruta_inventario_hojas = (
        processed / "ca0001_inventario_hojas.csv"
    )

    if not ruta_inventario_hojas.exists():
        raise FileNotFoundError(
            "No existe ca0001_inventario_hojas.csv. "
            "Ejecuta primero el módulo 23."
        )

    inventario = pd.read_csv(ruta_inventario_hojas)

    archivos = sorted(
        [
            archivo
            for archivo in raw.iterdir()
            if archivo.is_file()
            and archivo.suffix.lower() in {".xls", ".xlsx"}
            and "ca-0001" in archivo.name.lower()
        ],
        key=lambda x: periodo_desde_nombre(x.name),
    )

    if not archivos:
        raise FileNotFoundError(
            "No se encontraron archivos CA-0001 descargados."
        )

    ultimo_archivo = archivos[-1]
    anio, mes = periodo_desde_nombre(ultimo_archivo.name)

    inventario_ultimo = inventario[
        inventario["archivo"] == ultimo_archivo.name
    ].copy()

    if inventario_ultimo.empty:
        raise ValueError(
            f"No hay inventario de hojas para {ultimo_archivo.name}."
        )

    # Seleccionar las hojas con mayor puntaje, sin duplicados.
    hojas_seleccionadas = (
        inventario_ultimo.sort_values(
            "puntaje_relevancia",
            ascending=False,
        )
        .drop_duplicates("hoja")
        .head(10)["hoja"]
        .astype(str)
        .tolist()
    )

    # Asegurar las hojas que ya aparecieron como especialmente relevantes.
    for hoja in ["1", "2", "3", "6", "7", "9", "11", "13"]:
        if hoja in inventario_ultimo["hoja"].astype(str).tolist():
            if hoja not in hojas_seleccionadas:
                hojas_seleccionadas.append(hoja)

    contextos = []
    candidatos = []
    resumen_hojas = []

    print("\n" + "=" * 128)
    print(f"ARCHIVO ANALIZADO: {ultimo_archivo.name}")
    print(f"PERIODO: {anio}-{mes:02d}")
    print(f"HOJAS SELECCIONADAS: {', '.join(hojas_seleccionadas)}")
    print("=" * 128)

    for hoja in hojas_seleccionadas:
        tabla = leer_hoja(
            ultimo_archivo,
            hoja,
        )
        diagnostico = puntuar_filas(tabla)
        mejor = diagnostico.iloc[0]
        fila_candidata = int(mejor["fila_python"])

        resumen_hojas.append(
            {
                "anio": anio,
                "mes": mes,
                "archivo": ultimo_archivo.name,
                "hoja": hoja,
                "filas": len(tabla),
                "columnas": len(tabla.columns),
                "fila_candidata": fila_candidata + 1,
                "puntaje_fila": mejor["puntaje"],
                "palabras_detectadas": mejor["palabras_detectadas"],
            }
        )

        diagnostico = diagnostico.head(12).copy()
        diagnostico.insert(0, "archivo", ultimo_archivo.name)
        diagnostico.insert(1, "hoja", hoja)
        candidatos.append(diagnostico)

        vista = vista_contexto(
            tabla,
            fila_candidata,
        )
        vista.insert(0, "hoja", hoja)
        vista.insert(0, "archivo", ultimo_archivo.name)
        contextos.append(vista)

        print("\n" + "-" * 128)
        print(
            f"HOJA {hoja} | "
            f"{len(tabla)} filas × {len(tabla.columns)} columnas | "
            f"fila candidata: {fila_candidata + 1}"
        )
        print(
            f"Palabras detectadas: "
            f"{mejor['palabras_detectadas']}"
        )
        print("-" * 128)
        print(vista.to_string(index=False))

    contextos_df = pd.concat(
        contextos,
        ignore_index=True,
        sort=False,
    )
    candidatos_df = pd.concat(
        candidatos,
        ignore_index=True,
        sort=False,
    )
    resumen_df = pd.DataFrame(resumen_hojas)

    rutas = {
        "contextos": (
            processed / "ca0001_contextos_hojas_relevantes.csv"
        ),
        "candidatos": (
            processed / "ca0001_candidatos_encabezado.csv"
        ),
        "resumen": (
            processed / "ca0001_resumen_estructura_ultimo_archivo.csv"
        ),
    }

    contextos_df.to_csv(
        rutas["contextos"],
        index=False,
        encoding="utf-8-sig",
    )
    candidatos_df.to_csv(
        rutas["candidatos"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen_df.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nDIAGNÓSTICO ESTRUCTURAL CA-0001 TERMINADO")
    print("=" * 100)
    print(f"Archivo: {ultimo_archivo.name}")
    print(f"Hojas analizadas: {len(hojas_seleccionadas)}")
    print("\nResumen:")
    print(resumen_df.to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nComparte especialmente los bloques de las hojas 1, 2 y 3, "
        "y también 11 y 13. Esas hojas parecen contener la composición "
        "por emisor/instrumento y los cuadros diferenciados por AFP."
    )


if __name__ == "__main__":
    main()
