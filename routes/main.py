from flask import Blueprint, render_template
import geopandas as gpd
import pandas as pd

import numpy as np
import folium
import os
import unicodedata


main_bp = Blueprint("main", __name__)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "..", "data")


EXCEL_PATH = os.path.join(DATA_DIR, "dataCrecimiento.xlsx")

EXCEL_POBLACION = os.path.join(DATA_DIR, "poblacionParroquias.xlsx")

GJSON_RURAL = os.path.join(DATA_DIR, "parroquiasRurales.geojson")

GJSON_URBANA = os.path.join(DATA_DIR, "parroquiasUrbanas.geojson")

GJSON_OTRAS = os.path.join(DATA_DIR, "otras.geojson")


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

    # Añadir capa de parroquias rurales

    fg_parroquias = folium.FeatureGroup(name="Parroquias Rurales").add_to(m)

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
                "weight": 2,
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
        ).add_to(fg_parroquias)

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

    # Añadir capa de parroquias urbanas

    fg_parroquias = folium.FeatureGroup(name="Parroquias Urbanas").add_to(m)

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
                "weight": 2,
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
        ).add_to(fg_parroquias)

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
