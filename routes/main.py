from flask import Blueprint, render_template, request
import geopandas as gpd
import pandas as pd

import numpy as np
import folium
import os
import unicodedata
import json


main_bp = Blueprint("main", __name__)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "..", "data")


EXCEL_PATH = os.path.join(DATA_DIR, "dataCrecimiento.xlsx")

EXCEL_POBLACION = os.path.join(DATA_DIR, "poblacionParroquias.xlsx")

GJSON_RURAL = os.path.join(DATA_DIR, "parroquiasRurales.geojson")

GJSON_URBANA = os.path.join(DATA_DIR, "parroquiasUrbanas.geojson")

GJSON_OTRAS = os.path.join(DATA_DIR, "otras.geojson")
SECTORES_CONFIG_PATH = os.path.join(DATA_DIR, "sectores.json")


DEFAULT_CRS = "EPSG:4326"
AREA_CRS = (
    "EPSG:32717"  # UTM 17S (Ecuador/Quito aprox.), para areas/perimetros en metros
)


CODIGO_OTRAS = {
    # Usamos nombre normalizado (sin tildes, mayusculas) para evitar problemas de encoding.
    "SANGOLQUI": "170501",
    "RUMIPAMBA": "170552",
    "COTOGCHOA": "170551",
    "SAN RAFAEL": "170503",
    "SAN PEDRO": "170502",
    "FAJARDO": "170504",
}


def normalizar_nombre(nombre):
    if pd.isna(nombre):
        return ""

    nombre_sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", str(nombre))
        if unicodedata.category(c) != "Mn"
    )
    return nombre_sin_tildes.upper().strip()


def asegurar_crs(gdf, crs=DEFAULT_CRS):
    if gdf.crs != crs:
        return gdf.to_crs(crs)
    return gdf


def obtener_nombre(row):
    for campo in ["nombre", "DPA_DESPAR", "dpa_despar"]:
        valor = row.get(campo, None)
        if pd.notna(valor) and str(valor).strip() != "":
            return valor
    return "Sin nombre"


def obtener_codigo(row):
    for campo in ["DPA_PARROQ", "dpa_parroq", "Cod_Parr"]:
        valor = row.get(campo, None)
        if pd.notna(valor) and str(valor).strip() != "" and str(valor) != "nan":
            return str(valor)

    nombre_norm = normalizar_nombre(obtener_nombre(row))
    return CODIGO_OTRAS.get(nombre_norm, "")


def convertir_a_porcentaje(valor):
    if pd.isna(valor):
        return None

    if isinstance(valor, (int, float, np.number)):
        # Si viene en decimal (0.03), lo pasamos a porcentaje (3.0).
        return float(valor) * 100 if -1 <= float(valor) <= 1 else float(valor)

    return None


def cargar_parroquias(scope="todas"):
    scope = (scope or "todas").lower()

    gdfs = []

    if scope in ("todas", "rurales"):
        gdf_rurales = asegurar_crs(gpd.read_file(GJSON_RURAL), DEFAULT_CRS).copy()
        gdf_rurales["tipo"] = "RURAL"
        gdf_rurales["zona_admin"] = gdf_rurales.get("A_ZONAL", None)
        gdfs.append(gdf_rurales)

    if scope in ("todas", "urbanas"):
        gdf_urbanas = asegurar_crs(gpd.read_file(GJSON_URBANA), DEFAULT_CRS).copy()
        gdf_urbanas["tipo"] = "URBANO"
        gdf_urbanas["zona_admin"] = gdf_urbanas.get("AD_ZONAL", None)
        gdfs.append(gdf_urbanas)

    if scope == "todas":
        gdf_otras = asegurar_crs(gpd.read_file(GJSON_OTRAS), DEFAULT_CRS).copy()
        gdf_otras["tipo"] = gdf_otras.get("ur_ru", "OTRAS")
        gdf_otras["zona_admin"] = gdf_otras.get("ur_ru", None)
        gdfs.append(gdf_otras)

    gdf = pd.concat(gdfs, ignore_index=True)
    gdf["nombre"] = gdf.apply(obtener_nombre, axis=1)
    gdf["codigo"] = gdf.apply(obtener_codigo, axis=1)

    cols = ["codigo", "nombre", "tipo", "zona_admin", "geometry"]
    return gdf[cols].copy()


def cargar_config_sectorial():
    if not os.path.exists(SECTORES_CONFIG_PATH):
        return {
            "por_parroquia": {},
            "por_zona": {},
            "lat_split": {"sur_max": -0.22, "norte_min": -0.15},
            "default": "OTROS",
        }

    with open(SECTORES_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg.setdefault("por_parroquia", {})
    cfg.setdefault("por_zona", {})
    cfg.setdefault("lat_split", {"sur_max": -0.22, "norte_min": -0.15})
    cfg.setdefault("default", "OTROS")
    return cfg


def clasificar_sectorial(gdf, config=None):
    gdf = gdf.copy()
    cfg = config or cargar_config_sectorial()

    # Centroides (lat/lon) para regla Norte/Sur cuando no hay match por zona o parroquia.
    gdf_proj = asegurar_crs(gdf, DEFAULT_CRS).to_crs(AREA_CRS)
    centroides_proj = gdf_proj.geometry.centroid
    centroides_wgs84 = gpd.GeoSeries(centroides_proj, crs=AREA_CRS).to_crs(DEFAULT_CRS)
    gdf["lon"] = centroides_wgs84.x.astype(float)
    gdf["lat"] = centroides_wgs84.y.astype(float)

    por_parroquia = {}
    for raw_key, sector in (cfg.get("por_parroquia") or {}).items():
        key = str(raw_key)
        if "|" in key:
            left, right = key.split("|", 1)
            nombre_key = normalizar_nombre(left)
            right = right.strip()

            if ":" in right:
                kind, value = right.split(":", 1)
                kind_key = normalizar_nombre(kind)
                value_key = normalizar_nombre(value)
                canon_key = f"{nombre_key}|{kind_key}:{value_key}"
            else:
                canon_key = f"{nombre_key}|{normalizar_nombre(right)}"

            por_parroquia[canon_key] = sector
        else:
            por_parroquia[normalizar_nombre(key)] = sector
    por_zona = {normalizar_nombre(k): v for k, v in (cfg.get("por_zona") or {}).items()}

    lat_split = cfg.get("lat_split") or {}
    sur_max = float(lat_split.get("sur_max", -0.22))
    norte_min = float(lat_split.get("norte_min", -0.15))
    default_sector = cfg.get("default", "OTROS")

    def sector_row(row):
        nombre_norm = normalizar_nombre(row.get("nombre", ""))
        tipo_norm = normalizar_nombre(row.get("tipo", ""))
        zona_norm = normalizar_nombre(row.get("zona_admin", ""))

        candidates = [
            f"{nombre_norm}|TIPO:{tipo_norm}",
            f"{nombre_norm}|ZONA:{zona_norm}",
            f"{nombre_norm}|{tipo_norm}",
            f"{nombre_norm}|{zona_norm}",
            nombre_norm,
        ]
        for candidate in candidates:
            if candidate in por_parroquia:
                return por_parroquia[candidate]

        if zona_norm in por_zona:
            return por_zona[zona_norm]

        # Regla fallback para urbanas: Norte/Centro/Sur por latitud
        if row.get("tipo") == "URBANO":
            lat = row.get("lat", None)
            if lat is not None and not pd.isna(lat):
                if float(lat) <= sur_max:
                    return "SUR"
                if float(lat) >= norte_min:
                    return "NORTE"
                return "CENTRO"

        return default_sector

    gdf["sector"] = gdf.apply(sector_row, axis=1)
    return gdf


@main_bp.route("/")
def mapa_rural():

    # Cargar parroquias rurales

    gdf_rurales = gpd.read_file(GJSON_RURAL)

    # Asegurar que esté en EPSG:4326 (WGS84)

    if gdf_rurales.crs != "EPSG:4326":

        gdf_rurales = gdf_rurales.to_crs("EPSG:4326")

    # Cargar parroquias de otras.geojson y filtrar las rurales

    gdf_otras = gpd.read_file(GJSON_OTRAS)

    if gdf_otras.crs != "EPSG:4326":

        gdf_otras = gdf_otras.to_crs("EPSG:4326")

    # Filtrar solo las rurales de otras y excluir FAJARDO

    gdf_otras_rurales = gdf_otras[
        (gdf_otras["ur_ru"] == "RURAL") & (gdf_otras["nombre"] != "FAJARDO")
    ].copy()

    # Combinar ambos GeoDataFrames

    gdf_rurales = pd.concat([gdf_rurales, gdf_otras_rurales], ignore_index=True)

    # Cargar datos de crecimiento desde Excel

    df_crecimiento = pd.read_excel(EXCEL_PATH)

    # Convertir Cod_Parr a string para hacer match

    df_crecimiento["Cod_Parr"] = df_crecimiento["Cod_Parr"].astype(str)

    # Crear diccionario de codigo -> tasa de crecimiento

    tasa_dict = dict(
        zip(
            df_crecimiento["Cod_Parr"],
            df_crecimiento["Tasa de crecimiento anual poblacion"],
        )
    )

    # Función para obtener color según la tasa de crecimiento

    def get_color(tasa):

        if tasa is None:
            return "transparent"

        # Convertir a porcentaje si está en decimal

        tasa_porcentaje = tasa * 100 if tasa < 1 else tasa

        if tasa_porcentaje < -1.64:

            return "#E6F2FF"  # Azul muy claro (casi blanco)

        elif tasa_porcentaje < -0.46:

            return "#CCE5FF"  # Azul muy claro

        elif tasa_porcentaje < 1.18:

            return "#99CCFF"  # Azul claro

        elif tasa_porcentaje < 2.44:

            return "#66B3FF"  # Azul medio claro

        elif tasa_porcentaje < 3.32:

            return "#3399FF"  # Azul medio
        else:

            return "#0070C0"  # Azul oscuro

    # Crear mapa centrado en Ecuador

    m = folium.Map(location=[-0.20, -78.50], zoom_start=11, tiles="cartodbpositron")

    # Añadir leyenda

    legend_html = """

    <div style="position: fixed; 

                bottom: 50px; right: 10px; width: 250px; height: auto; 

                background-color: white; border:2px solid grey; z-index:9999; font-size:14px;

                padding: 10px; border-radius: 5px;">

        <p style="margin: 0 0 10px 0; font-weight: bold;">Tasa de crecimiento anual población</p>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #E6F2FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>-2.82 - -1.64</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #CCE5FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>-1.63 - -0.46</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #99CCFF; border: 1px solid black; margin-right: 10px;"></div>

            <span>-0.45 - 1.18</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #66B3FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>1.18 - 2.44</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #3399FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>2.44 - 3.32</span>

        </div>

        <div style="display: flex; align-items: center;">

            <div style="width: 20px; height: 20px; background-color: #0070C0; border: 1px solid black; margin-right: 10px;"></div>

            <span>3.32 - 4.93</span>

        </div>

    </div>
    """

    m.get_root().html.add_child(folium.Element(legend_html))

    # Añadir capas: polígonos y etiquetas (nombres) para poder mostrar/ocultar.

    fg_parroquias = folium.FeatureGroup(name="Parroquias Rurales", show=True).add_to(m)
    fg_nombres = folium.FeatureGroup(name="Nombres (Rurales)", show=True).add_to(m)

    # Mapeo de códigos para parroquias de otras.geojson

    codigo_otras = {
        "SANGOLQUÍ": "170501",
        "RUMIPAMBA": "170552",
        "COTOGCHOA": "170551",
        "SAN RAFAEL": "170503",
        "SAN PEDRO": "170502",
    }

    for _, row in gdf_rurales.iterrows():

        # Obtener nombre y código de la parroquia (compatible con ambos GeoJSON)

        nombre = row.get("DPA_DESPAR", row.get("nombre", "Sin nombre"))

        if pd.isna(nombre):

            nombre = row.get("nombre", "Sin nombre")

        if pd.isna(nombre):

            nombre = "Sin nombre"

        codigo = str(row.get("DPA_PARROQ", ""))

        if pd.isna(codigo) or codigo == "nan":

            # Si no hay código, buscar en el mapeo de otras.geojson

            codigo = codigo_otras.get(nombre, "")

        # Obtener tasa de crecimiento

        tasa = tasa_dict.get(codigo, None)

        # Obtener color según la tasa

        fill_color = get_color(tasa)

        folium.GeoJson(
            {
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": {"nombre": nombre},
            },
            style_function=lambda _, color=fill_color: {
                "fillColor": color,
                "color": "black",
                "weight": 0.5,
                "fillOpacity": 0.7,
            },
            tooltip=folium.GeoJsonTooltip(fields=["nombre"], aliases=["Parroquia:"]),
        ).add_to(fg_parroquias)

        # Añadir etiqueta con el nombre y la tasa de crecimiento en el centroide

        centroide = row.geometry.centroid

        if tasa is not None:

            tasa_porcentaje = tasa * 100

            html_label = f"""

            <div class="parroquia-label" style="font-weight: bold; color: black; text-align: center; white-space: nowrap;">

                <div>{nombre}</div>

                <div>{tasa_porcentaje:.2f}%</div>

            </div>
            """
        else:

            html_label = f"""

            <div class="parroquia-label" style="font-weight: bold; color: black; text-align: center; white-space: nowrap;">

                <div>{nombre}</div>

            </div>
            """

        folium.Marker(
            location=[centroide.y, centroide.x],
            icon=folium.DivIcon(html=html_label),
        ).add_to(fg_nombres)

    # Añadir control de capas

    folium.LayerControl().add_to(m)

    return render_template(
        "index.html",
        mapa=m.get_root().render(),
        map_name=m.get_name(),
        ruta_activa="rurales",
    )


@main_bp.route("/urbanas")
def mapa_urbanas():

    # Cargar parroquias urbanas

    gdf_urbanas = gpd.read_file(GJSON_URBANA)

    # Asegurar que esté en EPSG:4326 (WGS84)

    if gdf_urbanas.crs != "EPSG:4326":

        gdf_urbanas = gdf_urbanas.to_crs("EPSG:4326")

    # Cargar parroquias de otras.geojson y filtrar las urbanas

    gdf_otras = gpd.read_file(GJSON_OTRAS)

    if gdf_otras.crs != "EPSG:4326":

        gdf_otras = gdf_otras.to_crs("EPSG:4326")

    # Filtrar solo las urbanas de otras y excluir FAJARDO

    gdf_otras_urbanas = gdf_otras[
        (gdf_otras["ur_ru"] == "URBANO") & (gdf_otras["nombre"] != "FAJARDO")
    ].copy()

    # Combinar ambos GeoDataFrames

    gdf_urbanas = pd.concat([gdf_urbanas, gdf_otras_urbanas], ignore_index=True)

    # Cargar datos de crecimiento desde Excel

    df_crecimiento = pd.read_excel(EXCEL_PATH)

    # Convertir Cod_Parr a string para hacer match

    df_crecimiento["Cod_Parr"] = df_crecimiento["Cod_Parr"].astype(str)

    # Crear diccionario de codigo -> tasa de crecimiento

    tasa_dict = dict(
        zip(
            df_crecimiento["Cod_Parr"],
            df_crecimiento["Tasa de crecimiento anual poblacion"],
        )
    )

    # Función para obtener color según la tasa de crecimiento

    def get_color(tasa):

        if tasa is None:
            return "transparent"

        # Convertir a porcentaje si está en decimal

        tasa_porcentaje = tasa * 100 if tasa < 1 else tasa

        if tasa_porcentaje < -1.64:

            return "#E6F2FF"  # Azul muy claro (casi blanco)

        elif tasa_porcentaje < -0.46:

            return "#CCE5FF"  # Azul muy claro

        elif tasa_porcentaje < 1.18:

            return "#99CCFF"  # Azul claro

        elif tasa_porcentaje < 2.44:

            return "#66B3FF"  # Azul medio claro

        elif tasa_porcentaje < 3.32:

            return "#3399FF"  # Azul medio
        else:

            return "#0070C0"  # Azul oscuro

    # Crear mapa centrado en Ecuador

    m = folium.Map(location=[-0.20, -78.50], zoom_start=11, tiles="cartodbpositron")

    # Añadir leyenda

    legend_html = """

    <div style="position: fixed; 

                bottom: 50px; right: 10px; width: 250px; height: auto; 

                background-color: white; border:2px solid grey; z-index:9999; font-size:14px;

                padding: 10px; border-radius: 5px;">

        <p style="margin: 0 0 10px 0; font-weight: bold;">Tasa de crecimiento anual población</p>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #E6F2FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>-2.82 - -1.64</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #CCE5FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>-1.63 - -0.46</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #99CCFF; border: 1px solid black; margin-right: 10px;"></div>

            <span>-0.45 - 1.18</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #66B3FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>1.18 - 2.44</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #3399FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>2.44 - 3.32</span>

        </div>

        <div style="display: flex; align-items: center;">

            <div style="width: 20px; height: 20px; background-color: #0070C0; border: 1px solid black; margin-right: 10px;"></div>

            <span>3.32 - 4.93</span>

        </div>

    </div>
    """

    m.get_root().html.add_child(folium.Element(legend_html))

    # Mapeo de códigos para parroquias de otras.geojson

    codigo_otras = {
        "SANGOLQUÍ": "170501",
        "RUMIPAMBA": "170552",
        "COTOGCHOA": "170551",
        "SAN PEDRO": "170502",
        "SAN RAFAEL": "170503",
        "FAJARDO": "170504",
    }

    # Añadir capas: polígonos y etiquetas (nombres) para poder mostrar/ocultar.

    fg_parroquias = folium.FeatureGroup(name="Parroquias Urbanas", show=True).add_to(m)
    fg_nombres = folium.FeatureGroup(name="Nombres (Urbanas)", show=True).add_to(m)

    for _, row in gdf_urbanas.iterrows():

        # Obtener nombre y código de la parroquia (compatible con ambos GeoJSON)

        nombre = row.get("dpa_despar", row.get("nombre", "Sin nombre"))

        if pd.isna(nombre):

            nombre = row.get("nombre", "Sin nombre")

        if pd.isna(nombre):

            nombre = "Sin nombre"

        codigo = str(row.get("dpa_parroq", ""))

        if pd.isna(codigo) or codigo == "nan":

            # Si no hay código, buscar en el mapeo de otras.geojson

            codigo = codigo_otras.get(nombre, "")

        # Obtener tasa de crecimiento

        tasa = tasa_dict.get(codigo, None)

        # Obtener color según la tasa

        fill_color = get_color(tasa)

        folium.GeoJson(
            {
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": {"nombre": nombre},
            },
            style_function=lambda _, color=fill_color: {
                "fillColor": color,
                "color": "black",
                "weight": 0.2,
                "fillOpacity": 0.7,
            },
            tooltip=folium.GeoJsonTooltip(fields=["nombre"], aliases=["Parroquia:"]),
        ).add_to(fg_parroquias)

        # Añadir etiqueta con el nombre y la tasa de crecimiento en el centroide

        centroide = row.geometry.centroid

        if tasa is not None:

            tasa_porcentaje = tasa * 100

            html_label = f"""

            <div class="parroquia-label" style="font-weight: bold; color: black; text-align: center; white-space: nowrap;">

                <div>{nombre}</div>

                <div>{tasa_porcentaje:.2f}%</div>

            </div>
            """
        else:

            html_label = f"""

            <div class="parroquia-label" style="font-weight: bold; color: black; text-align: center; white-space: nowrap;">

                <div>{nombre}</div>

            </div>
            """

        folium.Marker(
            location=[centroide.y, centroide.x],
            icon=folium.DivIcon(html=html_label),
        ).add_to(fg_nombres)

    # Añadir control de capas

    folium.LayerControl().add_to(m)

    return render_template(
        "index.html",
        mapa=m.get_root().render(),
        map_name=m.get_name(),
        ruta_activa="urbanas",
    )


@main_bp.route("/poblacion")
def mapa_poblacion():

    # Función para normalizar nombres (sin tildes y en mayúsculas)

    def normalizar_nombre(nombre):

        if pd.isna(nombre):
            return ""

        # Remover tildes

        nombre_sin_tildes = "".join(
            c
            for c in unicodedata.normalize("NFD", str(nombre))
            if unicodedata.category(c) != "Mn"
        )

        # Convertir a mayúsculas

        return nombre_sin_tildes.upper()

    # Cargar todas las parroquias (rurales, urbanas y otras)

    gdf_rurales = gpd.read_file(GJSON_RURAL)

    gdf_urbanas = gpd.read_file(GJSON_URBANA)

    gdf_otras = gpd.read_file(GJSON_OTRAS)

    # Asegurar que todas estén en EPSG:4326 (WGS84)

    if gdf_rurales.crs != "EPSG:4326":

        gdf_rurales = gdf_rurales.to_crs("EPSG:4326")

    if gdf_urbanas.crs != "EPSG:4326":

        gdf_urbanas = gdf_urbanas.to_crs("EPSG:4326")

    if gdf_otras.crs != "EPSG:4326":

        gdf_otras = gdf_otras.to_crs("EPSG:4326")

    # Combinar todos los GeoDataFrames (incluyendo FAJARDO)

    gdf_todas = pd.concat([gdf_rurales, gdf_urbanas, gdf_otras], ignore_index=True)

    # Función auxiliar para obtener el nombre de la parroquia desde múltiples campos posibles

    def obtener_nombre(row):

        # Verificar todos los campos posibles en orden

        for campo in ["nombre", "DPA_DESPAR", "dpa_despar"]:

            valor = row.get(campo, None)

            if pd.notna(valor) and valor != "":

                return valor

        return "Sin nombre"

    # Normalizar nombres de parroquias en el GeoDataFrame

    gdf_todas["nombre_normalizado"] = gdf_todas.apply(
        lambda row: normalizar_nombre(obtener_nombre(row)),
        axis=1,
    )

    # Cargar datos de población desde Excel

    df_poblacion = pd.read_excel(EXCEL_POBLACION)

    # Normalizar nombres de parroquias en el Excel

    df_poblacion["Parroquia_normalizada"] = df_poblacion["Parroquia"].apply(
        normalizar_nombre
    )

    # Convertir porcentaje a número para cálculos

    def convertir_porcentaje_a_numero(valor):

        if pd.isna(valor):

            return None

        if isinstance(valor, (int, float)):

            return valor * 100 if -1 <= valor <= 1 else valor

        return None

    df_poblacion["Porcentaje_numero"] = df_poblacion["Porcentaje"].apply(
        convertir_porcentaje_a_numero
    )

    # Rangos personalizados para mejor distinción visual

    # Basados en la distribución real de los datos (muchas parroquias pequeñas, pocas grandes)

    rangos = [0, 0.5, 1.0, 2.0, 5.0, 10.0, 35.0]

    # Función para obtener color según el porcentaje de población

    def get_color_poblacion(porcentaje_val):

        if porcentaje_val is None:

            return "#CCCCCC"  # Gris para sin datos

        # Colores de menor a mayor (azul claro a azul oscuro)

        if porcentaje_val < rangos[1]:  # 0 - 0.5%

            return "#E6F2FF"  # Azul muy claro

        elif porcentaje_val < rangos[2]:  # 0.5 - 1.0%

            return "#CCE5FF"  # Azul claro

        elif porcentaje_val < rangos[3]:  # 1.0 - 2.0%

            return "#99CCFF"  # Azul medio claro

        elif porcentaje_val < rangos[4]:  # 2.0 - 5.0%

            return "#66B3FF"  # Azul medio

        elif porcentaje_val < rangos[5]:  # 5.0 - 10.0%

            return "#3399FF"  # Azul medio oscuro

        else:  # 10.0% en adelante

            return "#0070C0"  # Azul oscuro

    # Mantener el porcentaje como texto para mostrar

    def formatear_porcentaje(valor):

        if pd.isna(valor):

            return None

        if isinstance(valor, (int, float)):

            porcentaje_val = valor * 100 if -1 <= valor <= 1 else valor

            return f"{porcentaje_val:.2f}%"

        return str(valor).strip()

    df_poblacion["Porcentaje_texto"] = df_poblacion["Porcentaje"].apply(
        formatear_porcentaje
    )

    # Crear diccionarios de nombre normalizado -> porcentaje

    poblacion_dict_texto = dict(
        zip(df_poblacion["Parroquia_normalizada"], df_poblacion["Porcentaje_texto"])
    )

    poblacion_dict_numero = dict(
        zip(df_poblacion["Parroquia_normalizada"], df_poblacion["Porcentaje_numero"])
    )

    # Crear mapa centrado en Ecuador

    m = folium.Map(location=[-0.20, -78.50], zoom_start=11, tiles="cartodbpositron")

    # Añadir leyenda

    legend_html = """

    <div style="position: fixed; 

                bottom: 50px; right: 10px; width: 250px; height: auto; 

                background-color: white; border:2px solid grey; z-index:9999; font-size:14px;

                padding: 10px; border-radius: 5px;">

        <p style="margin: 0 0 10px 0; font-weight: bold;">Población parroquias</p>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #E6F2FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>0.00% - 0.50%</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #CCE5FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>0.50% - 1.00%</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #99CCFF; border: 1px solid black; margin-right: 10px;"></div>

            <span>1.00% - 2.00%</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #66B3FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>2.00% - 5.00%</span>

        </div>

        <div style="display: flex; align-items: center; margin-bottom: 8px;">

            <div style="width: 20px; height: 20px; background-color: #3399FF; border: 1px solid black; margin-right: 10px;"></div>

            <span>5.00% - 10.00%</span>

        </div>

        <div style="display: flex; align-items: center;">

            <div style="width: 20px; height: 20px; background-color: #0070C0; border: 1px solid black; margin-right: 10px;"></div>

            <span>10.00% - 35.00%</span>

        </div>

    </div>
    """

    m.get_root().html.add_child(folium.Element(legend_html))

    # Añadir capa de todas las parroquias

    fg_parroquias = folium.FeatureGroup(name="Todas las Parroquias").add_to(m)

    for _, row in gdf_todas.iterrows():

        # Obtener nombre original de la parroquia usando la función auxiliar

        nombre_original = obtener_nombre(row)

        # Obtener nombre normalizado

        nombre_normalizado = row["nombre_normalizado"]

        # Obtener porcentaje de población (texto para mostrar y número para color)

        porcentaje_texto = poblacion_dict_texto.get(nombre_normalizado, None)

        porcentaje_numero = poblacion_dict_numero.get(nombre_normalizado, None)

        # Obtener color según el porcentaje

        fill_color = get_color_poblacion(porcentaje_numero)

        folium.GeoJson(
            {
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": {"nombre": nombre_original},
            },
            style_function=lambda _, color=fill_color: {
                "fillColor": color,
                "color": "black",
                "weight": 2,
                "fillOpacity": 0.7,
            },
            tooltip=folium.GeoJsonTooltip(fields=["nombre"], aliases=["Parroquia:"]),
        ).add_to(fg_parroquias)

        # Añadir etiqueta con el nombre y el porcentaje en el centroide

        centroide = row.geometry.centroid

        if porcentaje_texto is not None:

            html_label = f"""

            <div class="parroquia-label" style="font-weight: bold; color: black; text-align: center; white-space: nowrap;">

                <div>{nombre_original}</div>

                <div>{porcentaje_texto}</div>

            </div>
            """
        else:

            html_label = f"""

            <div class="parroquia-label" style="font-weight: bold; color: black; text-align: center; white-space: nowrap;">

                <div>{nombre_original}</div>

            </div>
            """

        folium.Marker(
            location=[centroide.y, centroide.x],
            icon=folium.DivIcon(html=html_label),
        ).add_to(fg_parroquias)

    # Añadir control de capas

    folium.LayerControl().add_to(m)

    return render_template(
        "index.html",
        mapa=m.get_root().render(),
        map_name=m.get_name(),
        ruta_activa="poblacion",
    )


def mapa_clusters():
    k = request.args.get("k", default=5, type=int)
    scope = request.args.get("scope", default="todas", type=str)
    incluir_espacial = bool(request.args.get("espacial", default=0, type=int))

    gdf = cargar_parroquias(scope=scope)
    gdf = clusterizar_parroquias(gdf, k=k, incluir_espacial=incluir_espacial)

    m = folium.Map(location=[-0.20, -78.50], zoom_start=11, tiles="cartodbpositron")

    # 7 azules bien diferenciados (para tus 7 sectores).
    palette = [
        "#001F3F",  # navy
        "#003F8C",  # dark blue
        "#0057B8",  # azure
        "#1E88E5",  # bright blue
        "#42A5F5",  # light blue
        "#00B0FF",  # cyan-blue
        "#90CAF9",  # very light blue
    ]

    def color_cluster(cid):
        if cid is None or pd.isna(cid):
            return "#cccccc"
        return palette[(int(cid) - 1) % len(palette)]

    conteo = gdf["cluster"].value_counts().sort_index().to_dict()

    items = "\n".join(
        f"""
        <div style="display:flex; align-items:center; margin-bottom:6px;">
          <div style="width:18px; height:18px; background-color:{color_cluster(cid)}; border:1px solid #111; margin-right:8px;"></div>
          <span>Cluster {cid}: {conteo[cid]} parroquias</span>
        </div>
        """
        for cid in sorted(conteo.keys())
    )

    legend_html = f"""
    <div style="position: fixed;
                bottom: 50px; right: 10px; width: 260px; height: auto;
                background-color: white; border:2px solid grey; z-index:9999; font-size:13px;
                padding: 10px; border-radius: 5px;">
        <p style="margin: 0 0 10px 0; font-weight: bold;">Clusters por parroquia</p>
        <p style="margin: 0 0 10px 0; font-size: 12px;">k={k} | scope={scope} | espacial={int(incluir_espacial)}</p>
        {items}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    fg = folium.FeatureGroup(name="Clusters").add_to(m)

    for _, row in gdf.iterrows():
        cid = row.get("cluster", None)
        fill_color = color_cluster(cid)

        tasa = row.get("tasa_pct", None)
        pob = row.get("pob_pct", None)
        area = row.get("area_km2", None)

        props = {
            "Parroquia": row.get("nombre", "Sin nombre"),
            "Codigo": row.get("codigo", ""),
            "Tipo": row.get("tipo", ""),
            "Cluster": int(cid) if pd.notna(cid) else None,
            "Tasa_%": None if tasa is None or pd.isna(tasa) else round(float(tasa), 2),
            "Pob_%": None if pob is None or pd.isna(pob) else round(float(pob), 2),
            "Area_km2": (
                None if area is None or pd.isna(area) else round(float(area), 2)
            ),
        }

        folium.GeoJson(
            {
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": props,
            },
            style_function=lambda _, color=fill_color: {
                "fillColor": color,
                "color": "black",
                "weight": 2,
                "fillOpacity": 0.7,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[
                    "Parroquia",
                    "Codigo",
                    "Tipo",
                    "Cluster",
                    "Tasa_%",
                    "Pob_%",
                    "Area_km2",
                ],
                aliases=[
                    "Parroquia:",
                    "Codigo:",
                    "Tipo:",
                    "Cluster:",
                    "Tasa (%):",
                    "Poblacion (%):",
                    "Area (km²):",
                ],
                localize=True,
            ),
        ).add_to(fg)

        centroide_lat = row.get("lat", None)
        centroide_lon = row.get("lon", None)
        html_label = f"""
        <div class="parroquia-label" style="font-weight: bold; color: black; text-align: center; white-space: nowrap;">
            <div>{row.get('nombre','Sin nombre')}</div>
            <div>Cluster {int(cid)}</div>
        </div>
        """
        folium.Marker(
            location=[centroide_lat, centroide_lon],
            icon=folium.DivIcon(html=html_label),
        ).add_to(fg)

    folium.LayerControl().add_to(m)

    return render_template(
        "index.html",
        mapa=m.get_root().render(),
        map_name=m.get_name(),
        ruta_activa="clusters",
    )


@main_bp.route("/sectores")
def mapa_sectores():
    scope = request.args.get("scope", default="todas", type=str)
    gdf = cargar_parroquias(scope=scope)
    gdf = clasificar_sectorial(gdf)

    m = folium.Map(location=[-0.20, -78.50], zoom_start=11, tiles="cartodbpositron")

    # 7 colores combinando azules y cafés pastel
    palette = [
        "#C8A882",  # Caramelo pastel
        "#A8C8E1",  # Azul pastel suave
        "#D4C5B9",  # Café con leche
        "#7BB3D9",  # Azul medio
        "#A68A6D",  # Café oscuro pastel
        "#4A7BA7",  # Azul profundo
        "#F0E6D2",  # Crema claro
    ]

    sectores = sorted([s for s in gdf["sector"].dropna().unique().tolist()])
    color_by_sector = {s: palette[i % len(palette)] for i, s in enumerate(sectores)}

    conteo = gdf["sector"].value_counts().to_dict()
    items = "\n".join(
        f"""
        <div style="display:flex; align-items:center; margin-bottom:6px;">
          <div style="width:18px; height:18px; background-color:{color_by_sector.get(s, '#cccccc')}; border:1px solid #111; margin-right:8px;"></div>
          <span>{s}: {conteo.get(s, 0)} parroquias</span>
        </div>
        """
        for s in sectores
    )

    legend_html = f"""
    <div style="position: fixed;
                bottom: 50px; right: 10px; width: 280px; height: auto;
                background-color: white; border:2px solid grey; z-index:9999; font-size:13px;
                padding: 10px; border-radius: 5px;">
        <p style="margin: 0 0 10px 0; font-weight: bold;">Sectores por parroquia</p>
        <p style="margin: 0 0 10px 0; font-size: 12px;">scope={scope} | config=`data/sectores.json`</p>
        {items}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    # Capas separadas para poder mostrar/ocultar los nombres.
    fg = folium.FeatureGroup(name="Sectores", show=True).add_to(m)
    fg_nombres = folium.FeatureGroup(name="Nombres (Sectores)", show=True).add_to(m)

    for _, row in gdf.iterrows():
        sector = row.get("sector", "OTROS")
        fill_color = color_by_sector.get(sector, "#cccccc")

        props = {
            "Parroquia": row.get("nombre", "Sin nombre"),
            "Codigo": row.get("codigo", ""),
            "Tipo": row.get("tipo", ""),
            "Zona": row.get("zona_admin", ""),
            "Sector": sector,
        }

        folium.GeoJson(
            {
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": props,
            },
            style_function=lambda _, color=fill_color: {
                "fillColor": color,
                "color": "black",
                "weight": 0.1,
                "fillOpacity": 0.7,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["Parroquia", "Codigo", "Tipo", "Zona", "Sector"],
                aliases=["Parroquia:", "Codigo:", "Tipo:", "Zona:", "Sector:"],
                localize=True,
            ),
        ).add_to(fg)
        
        html_label = f"""
        <div class="parroquia-label" style="font-weight: bold; color: black; text-align: center; white-space: nowrap;">
            <div>{row.get('nombre','Sin nombre')}</div>
            <div>{sector}</div>
        </div>
        """
        folium.Marker(
            location=[row.get("lat", None), row.get("lon", None)],
            icon=folium.DivIcon(html=html_label),
        ).add_to(fg_nombres)

    folium.LayerControl().add_to(m)

    return render_template(
        "index.html",
        mapa=m.get_root().render(),
        map_name=m.get_name(),
        ruta_activa="sectores",
    )
