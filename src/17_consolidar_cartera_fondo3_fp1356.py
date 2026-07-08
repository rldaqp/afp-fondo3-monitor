from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/149 Safari/537.36"
)


def normalizar(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def normalizar_clave(valor: object) -> str:
    texto = normalizar(valor).lower()
    texto = (
        texto.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )
    return texto


def numerico(valor: object) -> float:
    if pd.isna(valor):
        return np.nan

    if isinstance(valor, (int, float, np.integer, np.floating)):
        return float(valor)

    texto = normalizar(valor)
    if not texto:
        return np.nan

    texto = texto.replace(",", "")
    texto = texto.replace("%", "")

    try:
        return float(texto)
    except ValueError:
        return np.nan


def crear_sesion() -> requests.Session:
    sesion = requests.Session()
    sesion.headers.update({"User-Agent": USER_AGENT})
    return sesion


def descargar_archivo(
    sesion: requests.Session,
    url: str,
    nombre: str,
    carpeta: Path,
) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / nombre

    if destino.exists() and destino.stat().st_size > 1_000:
        return destino

    respuesta = sesion.get(url, timeout=120, allow_redirects=True)
    respuesta.raise_for_status()

    contenido = respuesta.content
    if len(contenido) < 1_000:
        raise RuntimeError(
            f"{nombre} es demasiado pequeño y podría ser una página de error."
        )

    destino.write_bytes(contenido)
    return destino


def preparar_excel(archivo: Path) -> tuple[BytesIO, str]:
    contenido = archivo.read_bytes()

    if contenido.startswith(b"PK"):
        return BytesIO(contenido), "openpyxl"

    if contenido.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return BytesIO(contenido), "xlrd"

    inicio = contenido[:500].lower()
    if b"<html" in inicio or b"<!doctype html" in inicio:
        raise ValueError(
            f"{archivo.name} contiene HTML y no un archivo Excel."
        )

    raise ValueError(
        f"{archivo.name} no tiene una firma XLS/XLSX reconocida."
    )


def elegir_hoja_fondo3(archivo: Path) -> str:
    fuente, motor = preparar_excel(archivo)
    libro = pd.ExcelFile(fuente, engine=motor)

    candidatas = [
        hoja
        for hoja in libro.sheet_names
        if "fondo3" in hoja.lower().replace(" ", "")
    ]

    if candidatas:
        return candidatas[0]

    # Respaldo: buscar una hoja cuyo contenido mencione Fondo Tipo 3.
    for hoja in libro.sheet_names:
        fuente_hoja, motor_hoja = preparar_excel(archivo)
        muestra = pd.read_excel(
            fuente_hoja,
            sheet_name=hoja,
            header=None,
            nrows=15,
            engine=motor_hoja,
        )

        texto = " ".join(
            normalizar_clave(x)
            for x in muestra.to_numpy().ravel()
        )

        if "fondo de pensiones tipo 3" in texto or "fondo tipo 3" in texto:
            return hoja

    raise ValueError(
        f"No se encontró la hoja del Fondo 3. Hojas: {libro.sheet_names}"
    )


def leer_hoja_fondo3(archivo: Path) -> tuple[str, pd.DataFrame]:
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


def detectar_fecha(
    tabla: pd.DataFrame,
    anio: int,
    mes: int,
) -> pd.Timestamp:
    limite_filas = min(10, len(tabla))
    limite_cols = min(8, len(tabla.columns))

    for i in range(limite_filas):
        for j in range(limite_cols):
            valor = tabla.iat[i, j]

            if isinstance(valor, pd.Timestamp):
                return valor.normalize()

            texto = normalizar(valor)
            if not texto:
                continue

            if re.search(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", texto):
                fecha = pd.to_datetime(texto, errors="coerce")
                if pd.notna(fecha):
                    return pd.Timestamp(fecha).normalize()

    # Respaldo: último día del mes según el inventario.
    return pd.Timestamp(year=anio, month=mes, day=1) + pd.offsets.MonthEnd(0)


def detectar_encabezado(
    tabla: pd.DataFrame,
) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """
    Retorna:
      fila con AFP,
      fila con Monto/%,
      columnas (monto, porcentaje) por AFP.
    """
    fila_afp = None
    columnas_afp: dict[str, int] = {}

    for i, fila in tabla.iterrows():
        detectadas: dict[str, int] = {}

        for j, valor in enumerate(fila.tolist()):
            clave = normalizar_clave(valor)

            for afp in AFPS:
                if afp.lower() in clave:
                    detectadas[afp] = j

        if len(detectadas) >= 3:
            fila_afp = i
            columnas_afp = detectadas
            break

    if fila_afp is None:
        raise ValueError(
            "No se encontró una fila de encabezado con las AFP."
        )

    fila_sub = None
    for i in range(fila_afp + 1, min(fila_afp + 5, len(tabla))):
        texto = " | ".join(
            normalizar_clave(x)
            for x in tabla.iloc[i].tolist()
        )
        if "monto" in texto and ("%" in texto or "participacion" in texto):
            fila_sub = i
            break

    if fila_sub is None:
        fila_sub = fila_afp + 1

    pares: dict[str, tuple[int, int]] = {}

    # En la estructura observada, el nombre de cada AFP está sobre la
    # primera columna del par Monto / %. Se valida con la subfila.
    for afp, col_inicio in columnas_afp.items():
        col_monto = col_inicio
        col_pct = col_inicio + 1

        if col_pct >= len(tabla.columns):
            raise ValueError(
                f"No se pudo formar el par Monto/% para {afp}."
            )

        etiqueta_monto = normalizar_clave(tabla.iat[fila_sub, col_monto])
        etiqueta_pct = normalizar_clave(tabla.iat[fila_sub, col_pct])

        # Si el encabezado combinado se desplazó, buscar Monto y % cerca.
        if "monto" not in etiqueta_monto:
            candidatos = range(
                max(0, col_inicio - 1),
                min(len(tabla.columns), col_inicio + 3),
            )
            encontrado = None
            for j in candidatos:
                if "monto" in normalizar_clave(tabla.iat[fila_sub, j]):
                    encontrado = j
                    break
            if encontrado is not None:
                col_monto = encontrado
                col_pct = encontrado + 1

        if (
            "%" not in normalizar(tabla.iat[fila_sub, col_pct])
            and "participacion" not in etiqueta_pct
            and "porcentaje" not in etiqueta_pct
        ):
            # La estructura histórica puede dejar la celda "%" vacía.
            # Se conserva la columna inmediatamente posterior al monto.
            pass

        pares[afp] = (col_monto, col_pct)

    faltantes = [afp for afp in AFPS if afp not in pares]
    if faltantes:
        raise ValueError(
            f"No se detectaron todas las AFP. Faltan: {faltantes}"
        )

    return fila_afp, fila_sub, pares


def clasificar_tipo_fila(
    descripcion: str,
    nivel: int,
) -> str:
    clave = normalizar_clave(descripcion)

    if "total" in clave:
        return "total"

    if nivel == 1:
        return "categoria_nivel_1"

    if nivel == 2:
        return "categoria_nivel_2"

    return "instrumento_o_detalle"


def es_nota(descripcion: str) -> bool:
    clave = normalizar_clave(descripcion)

    patrones = [
        r"^\d+/\s",
        r"^nota",
        r"^fuente",
        r"^elaboracion",
        r"^incluye",
    ]

    return any(re.search(patron, clave) for patron in patrones)


def construir_filas_estructurales(
    tabla: pd.DataFrame,
    fila_inicio_datos: int,
    primera_col_numerica: int,
    pares: dict[str, tuple[int, int]],
) -> list[dict]:
    filas: list[dict] = []
    jerarquia: list[str] = [""] * max(1, primera_col_numerica)

    for i in range(fila_inicio_datos, len(tabla)):
        textos = [
            normalizar(tabla.iat[i, j])
            for j in range(primera_col_numerica)
        ]

        posiciones = [j for j, texto in enumerate(textos) if texto]

        if not posiciones:
            continue

        nivel_col = max(posiciones)
        descripcion = textos[nivel_col]

        valores_numericos = []
        for afp in AFPS:
            col_monto, col_pct = pares[afp]
            valores_numericos.extend(
                [
                    numerico(tabla.iat[i, col_monto]),
                    numerico(tabla.iat[i, col_pct]),
                ]
            )

        tiene_numeros = any(pd.notna(x) for x in valores_numericos)

        if es_nota(descripcion) and not tiene_numeros:
            continue

        if not tiene_numeros:
            continue

        # Actualizar la jerarquía y borrar niveles inferiores.
        jerarquia[nivel_col] = descripcion
        for j in range(nivel_col + 1, len(jerarquia)):
            jerarquia[j] = ""

        nivel_profundidad = nivel_col + 1

        filas.append(
            {
                "fila_python": i,
                "fila_excel_aprox": i + 1,
                "nivel_profundidad": nivel_profundidad,
                "descripcion": descripcion,
                "ruta_jerarquica": " > ".join(
                    x for x in jerarquia if x
                ),
                "nivel_1": jerarquia[0] if len(jerarquia) >= 1 else "",
                "nivel_2": jerarquia[1] if len(jerarquia) >= 2 else "",
                "nivel_3": jerarquia[2] if len(jerarquia) >= 3 else "",
                "tipo_fila": clasificar_tipo_fila(
                    descripcion,
                    nivel_profundidad,
                ),
            }
        )

    # Una fila es hoja cuando la siguiente fila no pertenece a un nivel
    # jerárquico más profundo.
    for indice, fila in enumerate(filas):
        if indice == len(filas) - 1:
            fila["es_hoja"] = True
        else:
            nivel_actual = fila["nivel_profundidad"]
            nivel_siguiente = filas[indice + 1]["nivel_profundidad"]
            fila["es_hoja"] = nivel_siguiente <= nivel_actual

    return filas


def procesar_archivo(
    archivo: Path,
    anio: int,
    mes: int,
) -> tuple[pd.DataFrame, dict]:
    hoja, tabla = leer_hoja_fondo3(archivo)
    fecha_cartera = detectar_fecha(tabla, anio, mes)

    fila_afp, fila_sub, pares = detectar_encabezado(tabla)
    primera_col_numerica = min(
        col_monto for col_monto, _ in pares.values()
    )
    fila_inicio_datos = fila_sub + 1

    estructura = construir_filas_estructurales(
        tabla,
        fila_inicio_datos,
        primera_col_numerica,
        pares,
    )

    registros: list[dict] = []

    for fila in estructura:
        i = fila["fila_python"]

        for afp in AFPS:
            col_monto, col_pct = pares[afp]
            monto = numerico(tabla.iat[i, col_monto])
            participacion = numerico(tabla.iat[i, col_pct])

            if pd.isna(monto) and pd.isna(participacion):
                continue

            registros.append(
                {
                    "fecha_cartera": fecha_cartera,
                    "anio": fecha_cartera.year,
                    "mes": fecha_cartera.month,
                    "afp": afp,
                    "fondo": 3,
                    "monto_miles_soles": monto,
                    "participacion_pct": participacion,
                    "archivo_fuente": archivo.name,
                    "hoja_fuente": hoja,
                    **{
                        clave: valor
                        for clave, valor in fila.items()
                        if clave != "fila_python"
                    },
                }
            )

    largo = pd.DataFrame(registros)

    if largo.empty:
        raise ValueError(
            "La hoja fue leída, pero no se obtuvieron registros."
        )

    nivel1 = largo[
        (largo["nivel_profundidad"] == 1)
        & (~largo["descripcion"].str.contains(
            "total",
            case=False,
            na=False,
        ))
    ]

    suma_nivel1 = (
        nivel1.groupby("afp")["participacion_pct"]
        .sum(min_count=1)
        .to_dict()
    )

    total_100 = {}
    filas_total = largo[
        largo["descripcion"].str.contains(
            "total",
            case=False,
            na=False,
        )
    ]

    for afp in AFPS:
        valores = filas_total.loc[
            filas_total["afp"] == afp,
            "participacion_pct",
        ].dropna()

        total_100[afp] = bool(
            ((valores >= 99.0) & (valores <= 101.0)).any()
        )

    control = {
        "fecha_cartera": fecha_cartera,
        "archivo": archivo.name,
        "hoja": hoja,
        "fila_encabezado_afp": fila_afp + 1,
        "fila_encabezado_monto_pct": fila_sub + 1,
        "primera_columna_numerica": primera_col_numerica + 1,
        "filas_estructurales": len(estructura),
        "observaciones_largas": len(largo),
        "afp_detectadas": largo["afp"].nunique(),
        "suma_nivel1_pct_habitat": suma_nivel1.get("Habitat", np.nan),
        "suma_nivel1_pct_integra": suma_nivel1.get("Integra", np.nan),
        "suma_nivel1_pct_prima": suma_nivel1.get("Prima", np.nan),
        "suma_nivel1_pct_profuturo": suma_nivel1.get("Profuturo", np.nan),
        "total_100_habitat": total_100.get("Habitat", False),
        "total_100_integra": total_100.get("Integra", False),
        "total_100_prima": total_100.get("Prima", False),
        "total_100_profuturo": total_100.get("Profuturo", False),
    }

    alertas = []

    if control["afp_detectadas"] != 4:
        alertas.append("No se detectaron las cuatro AFP")

    for afp in AFPS:
        valor = suma_nivel1.get(afp, np.nan)
        if pd.notna(valor) and not (98.0 <= valor <= 102.0):
            alertas.append(
                f"Suma nivel 1 fuera de 98-102 para {afp}: {valor:.4f}"
            )

    control["estado"] = "revisar" if alertas else "correcto"
    control["alertas"] = " | ".join(alertas)

    return largo, control


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    raw = raiz / "data" / "raw" / "sbs" / "fp1356_cartera"

    ruta_inventario = processed / "fp1356_inventario_enlaces.csv"

    if not ruta_inventario.exists():
        raise FileNotFoundError(
            "No existe fp1356_inventario_enlaces.csv. "
            "Ejecuta primero el módulo 15."
        )

    inventario = pd.read_csv(ruta_inventario)
    columnas_requeridas = {"anio", "mes", "url", "archivo"}

    faltantes = columnas_requeridas - set(inventario.columns)
    if faltantes:
        raise ValueError(
            f"Al inventario le faltan columnas: {sorted(faltantes)}"
        )

    inventario = inventario.sort_values(
        ["anio", "mes", "archivo"]
    ).reset_index(drop=True)

    sesion = crear_sesion()
    bases = []
    controles = []
    errores = []

    print(
        f"Procesando {len(inventario)} archivos mensuales FP-1356..."
    )

    for numero, fila in inventario.iterrows():
        posicion = numero + 1
        anio = int(fila["anio"])
        mes = int(fila["mes"])
        nombre = str(fila["archivo"])
        url = str(fila["url"])

        print(
            f"\n[{posicion}/{len(inventario)}] "
            f"{anio}-{mes:02d} {nombre}"
        )

        try:
            archivo = descargar_archivo(
                sesion,
                url,
                nombre,
                raw,
            )

            largo, control = procesar_archivo(
                archivo,
                anio,
                mes,
            )

            bases.append(largo)
            controles.append(control)

            print(
                f"  Correcto: {len(largo):,} observaciones | "
                f"{control['filas_estructurales']} filas estructurales | "
                f"estado={control['estado']}"
            )

            if control["alertas"]:
                print(f"  Alerta: {control['alertas']}")

        except Exception as error:
            errores.append(
                {
                    "anio": anio,
                    "mes": mes,
                    "archivo": nombre,
                    "url": url,
                    "error": str(error),
                }
            )
            print(f"  ERROR: {error}")

    if not bases:
        raise RuntimeError(
            "No fue posible consolidar ningún archivo FP-1356."
        )

    base = pd.concat(
        bases,
        ignore_index=True,
        sort=False,
    )

    base = base.sort_values(
        [
            "fecha_cartera",
            "afp",
            "fila_excel_aprox",
        ]
    ).reset_index(drop=True)

    resumen_nivel1 = base[
        (base["nivel_profundidad"] == 1)
        & (~base["descripcion"].str.contains(
            "total",
            case=False,
            na=False,
        ))
    ].copy()

    instrumentos_hoja = base[
        base["es_hoja"].astype(bool)
        & (~base["descripcion"].str.contains(
            "total",
            case=False,
            na=False,
        ))
    ].copy()

    catalogo = (
        base[
            [
                "nivel_profundidad",
                "nivel_1",
                "nivel_2",
                "nivel_3",
                "descripcion",
                "ruta_jerarquica",
                "tipo_fila",
                "es_hoja",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            [
                "nivel_profundidad",
                "ruta_jerarquica",
            ]
        )
        .reset_index(drop=True)
    )

    control_df = pd.DataFrame(controles)
    errores_df = pd.DataFrame(errores)

    rutas = {
        "base_larga": (
            processed / "fp1356_fondo3_cartera_largo.csv"
        ),
        "nivel1": (
            processed / "fp1356_fondo3_resumen_nivel1.csv"
        ),
        "hojas": (
            processed / "fp1356_fondo3_instrumentos_hoja.csv"
        ),
        "catalogo": (
            processed / "fp1356_fondo3_catalogo_descripciones.csv"
        ),
        "control": (
            processed / "fp1356_fondo3_control_calidad.csv"
        ),
        "errores": (
            processed / "fp1356_fondo3_errores.csv"
        ),
    }

    base.to_csv(
        rutas["base_larga"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen_nivel1.to_csv(
        rutas["nivel1"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    instrumentos_hoja.to_csv(
        rutas["hojas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    catalogo.to_csv(
        rutas["catalogo"],
        index=False,
        encoding="utf-8-sig",
    )
    control_df.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    errores_df.to_csv(
        rutas["errores"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nCONSOLIDACIÓN FP-1356 TERMINADA")
    print("=" * 100)
    print(f"Archivos del inventario: {len(inventario)}")
    print(f"Archivos correctos: {len(controles)}")
    print(f"Archivos con error: {len(errores)}")
    print(f"Observaciones consolidadas: {len(base):,}")
    print(
        "Rango:",
        base["fecha_cartera"].min().date(),
        "a",
        base["fecha_cartera"].max().date(),
    )
    print(
        "Meses únicos:",
        base["fecha_cartera"].nunique(),
    )
    print(
        "AFP:",
        ", ".join(sorted(base["afp"].unique())),
    )

    latest = base["fecha_cartera"].max()
    ultima = resumen_nivel1[
        resumen_nivel1["fecha_cartera"] == latest
    ][
        [
            "fecha_cartera",
            "afp",
            "descripcion",
            "monto_miles_soles",
            "participacion_pct",
        ]
    ].copy()

    print(
        f"\nCOMPOSICIÓN NIVEL 1 DEL ÚLTIMO MES ({latest.date()})"
    )
    print("-" * 100)
    print(
        ultima.sort_values(
            ["afp", "participacion_pct"],
            ascending=[True, False],
        ).to_string(index=False)
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nInterpretación:\n"
        "- base_larga contiene subtotales e instrumentos con su jerarquía.\n"
        "- resumen_nivel1 contiene las grandes categorías de cartera y "
        "debería sumar aproximadamente 100 % por AFP y mes.\n"
        "- instrumentos_hoja conserva las filas terminales de la jerarquía "
        "para el análisis detallado.\n"
        "- Los archivos marcados como revisar no se eliminan; quedan "
        "registrados en el control de calidad.\n"
        "- La composición publicada permitirá contrastar las exposiciones "
        "estadísticas, pero no prueba por sí sola causalidad diaria."
    )


if __name__ == "__main__":
    main()
