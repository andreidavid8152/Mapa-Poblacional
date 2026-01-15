from flask import Blueprint, render_template
import geopandas as gpd
import pandas as pd
import folium
import os

main_bp = Blueprint("main", __name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "data")

EXCEL_PATH = os.path.join(DATA_DIR, "dataCrecimiento.xlsx")
GJSON_RURAL = os.path.join(DATA_DIR, "parroquiasRurales.geojson")
GJSON_URBANA = os.path.join(DATA_DIR, "parroquiasUrbanas.geojson")
GJSON_OTRAS = os.path.join(DATA_DIR, "otras.geojson")


@main_bp.route("/")
def mapa():
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
    gdf_otras_rurales = gdf_otras[(gdf_otras["ur_ru"] == "RURAL") & (gdf_otras["nombre"] != "FAJARDO")].copy()

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
            return "#D4C4EB"  # Morado muy claro
        elif tasa_porcentaje < -0.46:
            return "#9B8BC7"  # Morado claro
        elif tasa_porcentaje < 1.18:
            return "#7B8ED1"  # Azul claro
        elif tasa_porcentaje < 2.44:
            return "#5B79D8"  # Azul medio
        elif tasa_porcentaje < 3.32:
            return "#3B5FCB"  # Azul oscuro
        else:
            return "#1E3E94"  # Azul muy oscuro

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
            <div style="width: 20px; height: 20px; background-color: #D4C4EB; border: 1px solid black; margin-right: 10px;"></div>
            <span>-2.82 - -1.64</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <div style="width: 20px; height: 20px; background-color: #9B8BC7; border: 1px solid black; margin-right: 10px;"></div>
            <span>-1.63 - -0.46</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <div style="width: 20px; height: 20px; background-color: #7B8ED1; border: 1px solid black; margin-right: 10px;"></div>
            <span>-0.45 - 1.18</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <div style="width: 20px; height: 20px; background-color: #5B79D8; border: 1px solid black; margin-right: 10px;"></div>
            <span>1.18 - 2.44</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <div style="width: 20px; height: 20px; background-color: #3B5FCB; border: 1px solid black; margin-right: 10px;"></div>
            <span>2.44 - 3.32</span>
        </div>
        <div style="display: flex; align-items: center;">
            <div style="width: 20px; height: 20px; background-color: #1E3E94; border: 1px solid black; margin-right: 10px;"></div>
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
            <div style="font-size: 9px; font-weight: bold; color: black; text-align: center;">
                <div>{nombre}</div>
                <div>{tasa_porcentaje:.2f}%</div>
            </div>
            """
        else:
            html_label = f"""
            <div style="font-size: 9px; font-weight: bold; color: black; text-align: center;">
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
    gdf_otras_urbanas = gdf_otras[(gdf_otras["ur_ru"] == "URBANO") & (gdf_otras["nombre"] != "FAJARDO")].copy()

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
            return "#D4C4EB"  # Morado muy claro
        elif tasa_porcentaje < -0.46:
            return "#9B8BC7"  # Morado claro
        elif tasa_porcentaje < 1.18:
            return "#7B8ED1"  # Azul claro
        elif tasa_porcentaje < 2.44:
            return "#5B79D8"  # Azul medio
        elif tasa_porcentaje < 3.32:
            return "#3B5FCB"  # Azul oscuro
        else:
            return "#1E3E94"  # Azul muy oscuro

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
            <div style="width: 20px; height: 20px; background-color: #D4C4EB; border: 1px solid black; margin-right: 10px;"></div>
            <span>-2.82 - -1.64</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <div style="width: 20px; height: 20px; background-color: #9B8BC7; border: 1px solid black; margin-right: 10px;"></div>
            <span>-1.63 - -0.46</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <div style="width: 20px; height: 20px; background-color: #7B8ED1; border: 1px solid black; margin-right: 10px;"></div>
            <span>-0.45 - 1.18</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <div style="width: 20px; height: 20px; background-color: #5B79D8; border: 1px solid black; margin-right: 10px;"></div>
            <span>1.18 - 2.44</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <div style="width: 20px; height: 20px; background-color: #3B5FCB; border: 1px solid black; margin-right: 10px;"></div>
            <span>2.44 - 3.32</span>
        </div>
        <div style="display: flex; align-items: center;">
            <div style="width: 20px; height: 20px; background-color: #1E3E94; border: 1px solid black; margin-right: 10px;"></div>
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
            <div style="font-size: 9px; font-weight: bold; color: black; text-align: center;">
                <div>{nombre}</div>
                <div>{tasa_porcentaje:.2f}%</div>
            </div>
            """
        else:
            html_label = f"""
            <div style="font-size: 9px; font-weight: bold; color: black; text-align: center;">
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
