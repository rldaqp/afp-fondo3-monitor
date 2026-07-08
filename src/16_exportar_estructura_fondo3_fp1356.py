from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import pandas as pd


AFPS = ["habitat", "integra", "prima", "profuturo"]


def preparar_excel(archivo: Path) -> tuple[BytesIO, str]:
    contenido = archivo.read_bytes()

    if contenido.startswith(b"PK"):
        return BytesIO(contenido), "openpyxl"

    if contenido.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return BytesIO(contenido), "xlrd"

    raise ValueError(
        f"{archivo.name} no es un Excel XLS/XLSX reconocido."
    )


def normalizar(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def extraer_periodo(nombre: str) -> tuple[int, int]:
    """
    Convierte nombres como FP-1356-my2026.XLS en (2026, 5).
    """
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
        r"FP-1356-([a-z]{2})(20\d{2})",
        nombre.lower(),
    )

    if not coincidencia:
        return (0, 0)

    codigo = coincidencia.group(1)
    anio = int(coincidencia.group(2))
    mes = codigos.get(codigo, 0)

    return anio, mes


def elegir_hoja_fondo3(archivo: Path) -> str:
    fuente, motor = preparar_excel(archivo)
    libro = pd.ExcelFile(fuente, engine=motor)

    candidatas = [
        hoja
        for hoja in libro.sheet_names
        if "fondo3" in hoja.lower().replace(" ", "")
    ]

    if not candidatas:
        raise ValueError(
            f"No se encontró una hoja Fondo3 en {archivo.name}. "
            f"Hojas: {libro.sheet_names}"
        )

    return candidatas[0]


def leer_hoja(archivo: Path) -> tuple[str, pd.DataFrame]:
    hoja = elegir_hoja_fondo3(archivo)
    fuente, motor = preparar_excel(archivo)

    tabla = pd.read_excel(
        fuente,
        sheet_name=hoja,
        header=None,
        engine=motor,
    )

    tabla = tabla.dropna(how="all").dropna(axis=1, how="all")
    tabla = tabla.reset_index(drop=True)

    return hoja, tabla


def puntuar_filas_encabezado(tabla: pd.DataFrame) -> pd.DataFrame:
    filas = []

    for indice, fila in tabla.iterrows():
        texto = " | ".join(
            normalizar(valor).lower()
            for valor in fila.tolist()
        )

        afp_detectadas = [
            afp for afp in AFPS if afp in texto
        ]

        palabras = []
        for palabra in [
            "instrumento",
            "monto",
            "participación",
            "participacion",
            "porcentaje",
            "%",
            "total",
        ]:
            if palabra in texto:
                palabras.append(palabra)

        filas.append(
            {
                "fila_python": indice,
                "fila_excel_aprox": indice + 1,
                "numero_afp_detectadas": len(afp_detectadas),
                "afp_detectadas": " | ".join(afp_detectadas),
                "palabras_encabezado": " | ".join(palabras),
                "texto_fila": texto,
            }
        )

    diagnostico = pd.DataFrame(filas)

    return diagnostico.sort_values(
        [
            "numero_afp_detectadas",
            "fila_python",
        ],
        ascending=[False, True],
    )


def tabla_con_indices(
    tabla: pd.DataFrame,
    archivo: Path,
    hoja: str,
    anio: int,
    mes: int,
) -> pd.DataFrame:
    salida = tabla.copy()
    salida.columns = [
        f"C{numero}"
        for numero in range(1, len(salida.columns) + 1)
    ]

    salida.insert(0, "fila_excel_aprox", range(1, len(salida) + 1))
    salida.insert(0, "hoja", hoja)
    salida.insert(0, "archivo", archivo.name)
    salida.insert(0, "mes", mes)
    salida.insert(0, "anio", anio)

    return salida


def imprimir_contexto(
    tabla: pd.DataFrame,
    fila_candidata: int,
    archivo: Path,
    hoja: str,
) -> None:
    inicio = max(0, fila_candidata - 4)
    fin = min(len(tabla), fila_candidata + 16)

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

    print("\n" + "=" * 120)
    print(f"ARCHIVO: {archivo.name}")
    print(f"HOJA: {hoja}")
    print(
        f"Fila candidata de encabezado: "
        f"{fila_candidata + 1}"
    )
    print("-" * 120)
    print(vista.to_string(index=False))


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]

    carpeta_raw = (
        raiz / "data" / "raw" / "sbs" / "fp1356_cartera"
    )
    carpeta_processed = raiz / "data" / "processed"
    carpeta_processed.mkdir(parents=True, exist_ok=True)

    if not carpeta_raw.exists():
        raise FileNotFoundError(
            f"No existe la carpeta: {carpeta_raw}"
        )

    archivos = [
        archivo
        for archivo in carpeta_raw.iterdir()
        if archivo.is_file()
        and archivo.suffix.lower() in {".xls", ".xlsx"}
        and "fp-1356" in archivo.name.lower()
    ]

    archivos = sorted(
        archivos,
        key=lambda archivo: extraer_periodo(archivo.name),
    )

    if not archivos:
        raise FileNotFoundError(
            "No se encontraron archivos FP-1356 descargados."
        )

    seleccion = archivos[-3:]

    vistas = []
    candidatos = []

    for archivo in seleccion:
        anio, mes = extraer_periodo(archivo.name)
        hoja, tabla = leer_hoja(archivo)

        diagnostico = puntuar_filas_encabezado(tabla)
        mejor = diagnostico.iloc[0]
        fila_candidata = int(mejor["fila_python"])

        imprimir_contexto(
            tabla,
            fila_candidata,
            archivo,
            hoja,
        )

        vista = tabla_con_indices(
            tabla,
            archivo,
            hoja,
            anio,
            mes,
        )
        vistas.append(vista)

        diagnostico.insert(0, "archivo", archivo.name)
        diagnostico.insert(1, "hoja", hoja)
        diagnostico.insert(2, "anio", anio)
        diagnostico.insert(3, "mes", mes)
        candidatos.append(diagnostico.head(15))

    vista_total = pd.concat(
        vistas,
        ignore_index=True,
        sort=False,
    )

    candidatos_total = pd.concat(
        candidatos,
        ignore_index=True,
        sort=False,
    )

    ultimo_archivo = seleccion[-1]
    ultimo_nombre = ultimo_archivo.name

    vista_ultimo = vista_total[
        vista_total["archivo"] == ultimo_nombre
    ].copy()

    ruta_vista_total = (
        carpeta_processed
        / "fp1356_vista_completa_ultimos3.csv"
    )
    ruta_vista_ultimo = (
        carpeta_processed
        / "fp1356_vista_ultimo_fondo3.csv"
    )
    ruta_candidatos = (
        carpeta_processed
        / "fp1356_candidatos_encabezado.csv"
    )

    vista_total.to_csv(
        ruta_vista_total,
        index=False,
        encoding="utf-8-sig",
    )
    vista_ultimo.to_csv(
        ruta_vista_ultimo,
        index=False,
        encoding="utf-8-sig",
    )
    candidatos_total.to_csv(
        ruta_candidatos,
        index=False,
        encoding="utf-8-sig",
    )

    print("\nDIAGNÓSTICO TERMINADO")
    print("=" * 90)
    print(f"Archivos revisados: {len(seleccion)}")
    print(f"Último archivo: {ultimo_nombre}")
    print(f"Filas del último archivo: {len(vista_ultimo)}")
    print(
        "Columnas de datos del último archivo:",
        len(
            [
                columna
                for columna in vista_ultimo.columns
                if columna.startswith("C")
            ]
        ),
    )

    print("\nArchivos creados:")
    print(f" - {ruta_vista_total.resolve()}")
    print(f" - {ruta_vista_ultimo.resolve()}")
    print(f" - {ruta_candidatos.resolve()}")

    print(
        "\nComparte el bloque mostrado alrededor del encabezado. "
        "También puedes subir fp1356_vista_ultimo_fondo3.csv. "
        "Con ello se construirá el consolidador definitivo de los "
        "137 meses."
    )


if __name__ == "__main__":
    main()
