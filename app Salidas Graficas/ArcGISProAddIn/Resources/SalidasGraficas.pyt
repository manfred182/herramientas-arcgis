# -*- coding: utf-8 -*-
"""Caja de herramientas para generar salidas graficas desde ArcGIS Pro."""

import os
import re
import unicodedata
import arcpy


TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.join(TOOL_DIR, "Plantilla_Monitoreo_Florencia.pagx")
DEFAULT_PROJECT_ROOT = r"F:\Trabajos Independientes Amazon GIS\Proyecto Restauracion FA Amazonas"
DEFAULT_GDB = os.path.join(
    DEFAULT_PROJECT_ROOT, "Base de Datos Geografica", "Base_Restautacion_compilada",
    "Base_Restauracion_ajustada.gdb")
DEFAULT_EXCEL = os.path.join(DEFAULT_PROJECT_ROOT, "Tablas de Datos Geoestadisticos.xlsx")


class Toolbox:
    def __init__(self):
        self.label = "Salidas Graficas - Monitoreo"
        self.alias = "salidas_monitoreo"
        self.tools = [GenerarSalidaAutomatica, GenerarSalidaGrafica]


class GenerarSalidaAutomatica:
    def __init__(self):
        self.label = "Generar salida automatica por nombre"
        self.description = (
            "Recibe un nombre, busca sus datos en Excel y la GDB, calcula areas "
            "por tipo de restauracion y genera el plano automaticamente."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p = []
        p.append(_param("Plantilla PAGX", "plantilla", "DEFile", "Required", "Input"))
        p[-1].filter.list = ["pagx"]
        p[-1].value = DEFAULT_TEMPLATE
        p.append(_param("Geodatabase maestra", "gdb", "DEWorkspace", "Required", "Input"))
        if os.path.isdir(DEFAULT_GDB):
            p[-1].value = DEFAULT_GDB
        p.append(_param("Excel de beneficiarios", "excel", "DEFile", "Required", "Input"))
        p[-1].filter.list = ["xlsx", "xls"]
        if os.path.isfile(DEFAULT_EXCEL):
            p[-1].value = DEFAULT_EXCEL
        p.append(_param("Nombre del beneficiario", "beneficiario", "GPString", "Required", "Input"))
        p.append(_param("Carpeta de salidas", "carpeta_salida", "DEFolder", "Required", "Input"))
        p[-1].value = os.path.join(TOOL_DIR, "Salidas")
        p.append(_param("Resolucion (DPI)", "dpi", "GPLong", "Required", "Input"))
        p[-1].value = 300
        p[-1].filter.type = "ValueList"
        p[-1].filter.list = [150, 200, 300, 400, 600]
        p.append(_param("Margen alrededor del predio (%)", "margen", "GPDouble", "Required", "Input"))
        p[-1].value = 12
        p.append(_param("Conservar layout en el proyecto", "conservar", "GPBoolean", "Required", "Input"))
        p[-1].value = True
        p.append(_param("PDF generado", "pdf", "DEFile", "Derived", "Output"))
        return p

    def updateParameters(self, parameters):
        if parameters[1].altered and parameters[1].valueAsText and not parameters[4].altered:
            parameters[4].value = os.path.join(os.path.dirname(parameters[1].valueAsText), "Salidas_Graficas")
        return

    def updateMessages(self, parameters):
        gdb = parameters[1].valueAsText
        if gdb and not gdb.lower().endswith(".gdb"):
            parameters[1].setErrorMessage("Selecciona una geodatabase de archivos (.gdb).")
        return

    def execute(self, parameters, messages):
        template = parameters[0].valueAsText
        gdb = parameters[1].valueAsText
        excel = parameters[2].valueAsText
        typed_name = parameters[3].valueAsText.strip()
        output_dir = parameters[4].valueAsText
        dpi = int(parameters[5].value)
        margin = float(parameters[6].value)
        keep_layout = bool(parameters[7].value)

        messages.addMessage("Buscando capas y campos en la geodatabase...")
        inventory = _gdb_inventory(gdb)
        area_fc = _find_area_feature_class(inventory)
        area_fields = {f.name.lower(): f.name for f in arcpy.ListFields(area_fc)}
        owner_field = _candidate_field(area_fields, ["Propietario", "NOMBRES_Y_APELLIDOS", "BENEFICIARIO", "NOMBRE"])
        type_field = _candidate_field(area_fields, ["Tipo_Restauracion", "TIPO_RESTAURACION", "TIPO", "RESTAURACION"])
        if not owner_field:
            raise arcpy.ExecuteError("No se encontro un campo de propietario en la capa de areas: " + area_fc)

        owner = _canonical_value(area_fc, owner_field, typed_name)
        if owner is None:
            raise arcpy.ExecuteError("No se encontro el beneficiario '{}' en la GDB.".format(typed_name))
        where = _where_equals(area_fc, owner_field, owner)

        messages.addMessage("Beneficiario encontrado: " + owner)
        messages.addMessage("Leyendo informacion del Excel...")
        excel_data = _find_excel_record(excel, owner)

        totals = _area_totals(area_fc, where, type_field)
        active = totals.get("activa", 0.0)
        passive = totals.get("pasiva", 0.0)
        total = sum(totals.values())
        messages.addMessage("Area activa: {} | pasiva: {} | total: {}".format(
            _format_area(active), _format_area(passive), _format_area(total)))

        aprx = arcpy.mp.ArcGISProject("CURRENT")
        layout = _loaded_monitoring_layout(aprx)
        using_loaded_layout = layout is not None
        if using_loaded_layout:
            messages.addMessage("Actualizando directamente el layout cargado: " + layout.name)
        else:
            messages.addMessage("No hay plantilla cargada; se importara el PAGX incluido.")
            old_layouts = {x.name for x in aprx.listLayouts()}
            aprx.importDocument(template)
            layouts = [x for x in aprx.listLayouts() if x.name not in old_layouts]
            if not layouts:
                raise arcpy.ExecuteError("No fue posible importar el layout PAGX.")
            layout = layouts[-1]
            layout.name = _unique_layout_name(aprx, _safe_name(owner), layout)
        frames = layout.listElements("MAPFRAME_ELEMENT", "Layers Map Frame")
        if not frames:
            raise arcpy.ExecuteError("No se encontro 'Layers Map Frame' en la plantilla.")
        frame = frames[0]

        # Repara automaticamente cada capa de la plantilla cuyo nombre exista en la GDB.
        area_layer = None
        for layer in frame.map.listLayers():
            if layer.isGroupLayer:
                continue
            source = _match_dataset(inventory, layer.name)
            if source:
                updated = _replace_or_add_layer(frame.map, layer.name, source, messages)
                if layer.name.lower() == "area restauracion":
                    area_layer = updated
        if area_layer is None:
            area_layer = _replace_or_add_layer(frame.map, "Area Restauracion", area_fc, messages)
        area_layer.definitionQuery = where

        _set_text(layout, "Text 6", owner)
        _set_text(layout, "Text 7", _record_value(excel_data, ["No_DE_CEDULA", "CEDULA", "IDENTIFICACION", "DOCUMENTO"]))
        _set_text(layout, "Text 8", _record_value(excel_data, ["NOMBRE_DEL_PREDIO_O_FINCA", "PREDIO", "NOMBRE_PREDIO", "FINCA"]))
        _set_text(layout, "Text 9", _record_value(excel_data, ["VEREDA"]))
        _set_text(layout, "Text 10", _record_value(excel_data, ["CORREGIMIENTO"]))
        _set_text(layout, "Text 11", _format_area(active))
        _set_text(layout, "Text 12", _format_area(passive))
        _replace_summary_text(layout, active, passive, total)

        arcpy.management.SelectLayerByAttribute(area_layer, "NEW_SELECTION", where)
        try:
            frame.camera.setExtent(frame.getLayerExtent(area_layer, True, True))
            frame.camera.scale *= 1.0 + margin / 100.0
        finally:
            arcpy.management.SelectLayerByAttribute(area_layer, "CLEAR_SELECTION")

        os.makedirs(output_dir, exist_ok=True)
        output = os.path.join(output_dir, _safe_name(owner) + ".pdf")
        layout.exportToPDF(output, resolution=dpi, image_quality="BEST", embed_fonts=True)
        if keep_layout or using_loaded_layout:
            aprx.save()
        else:
            aprx.deleteItem(layout)
        parameters[8].value = output
        messages.addMessage("Plano generado: " + output)


class GenerarSalidaGrafica:
    def __init__(self):
        self.label = "Generar salida grafica"
        self.description = (
            "Importa la plantilla de monitoreo, conecta las capas del beneficiario, "
            "completa los textos, ajusta la extension y exporta a PDF o PNG."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p = []

        p.append(_param("Plantilla PAGX", "plantilla", "DEFile", "Required", "Input"))
        p[0].filter.list = ["pagx"]
        p[0].value = DEFAULT_TEMPLATE

        p.append(_param("Capa de areas de restauracion", "areas", "GPFeatureLayer", "Required", "Input"))
        p.append(_param("Campo del propietario", "campo_propietario", "Field", "Required", "Input"))
        p[2].parameterDependencies = [p[1].name]

        p.append(_param("Propietario / beneficiario", "propietario", "GPString", "Required", "Input"))

        p.append(_param("Capa de ubicacion (puntos)", "ubicacion", "GPFeatureLayer", "Optional", "Input"))

        field_specs = [
            ("Campo de identificacion", "campo_id"),
            ("Campo de nombre del predio", "campo_predio"),
            ("Campo de vereda", "campo_vereda"),
            ("Campo de corregimiento", "campo_corregimiento"),
            ("Campo de tipo de restauracion", "campo_tipo"),
        ]
        for label, name in field_specs:
            q = _param(label, name, "Field", "Optional", "Input")
            q.parameterDependencies = [p[1].name]
            p.append(q)

        p.append(_param("Margen alrededor del predio (%)", "margen", "GPDouble", "Required", "Input"))
        p[-1].value = 12
        p[-1].filter.type = "Range"
        p[-1].filter.list = [0, 100]

        p.append(_param("Titulo del plano", "titulo", "GPString", "Optional", "Input"))
        p[-1].value = "MONITOREO DE AREAS DE RESTAURACION"

        p.append(_param("Archivo de salida", "salida", "DEFile", "Required", "Output"))
        p[-1].filter.list = ["pdf", "png"]

        p.append(_param("Resolucion (DPI)", "dpi", "GPLong", "Required", "Input"))
        p[-1].value = 300
        p[-1].filter.type = "ValueList"
        p[-1].filter.list = [150, 200, 300, 400, 600]

        p.append(_param("Conservar el layout en el proyecto", "conservar_layout", "GPBoolean", "Required", "Input"))
        p[-1].value = True

        p.append(_param("Layout generado", "layout_generado", "GPString", "Derived", "Output"))
        return p

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        if parameters[1].altered and not parameters[2].altered:
            parameters[2].value = _first_existing_field(parameters[1].value, [
                "NOMBRES_Y_APELLIDOS", "PROPIETARIO", "Propietario", "NOMBRE", "Nombre"
            ])

        guesses = {
            5: ["No_DE_CEDULA", "CEDULA", "IDENTIFICACION", "ID"],
            6: ["NOMBRE_DEL_PREDIO_O_FINCA", "PREDIO", "NOMBRE_PREDIO"],
            7: ["VEREDA", "Vereda"],
            8: ["CORREGIMIENTO", "Corregimiento"],
            9: ["TIPO_RESTAURACION", "TIPO", "Tipo_Restauracion"],
        }
        if parameters[1].altered:
            for index, names in guesses.items():
                if not parameters[index].altered:
                    parameters[index].value = _first_existing_field(parameters[1].value, names)

        if parameters[3].altered and parameters[3].value and not parameters[12].altered:
            safe = _safe_name(parameters[3].valueAsText)
            parameters[12].value = os.path.join(TOOL_DIR, "Salidas", safe + ".pdf")
        return

    def updateMessages(self, parameters):
        template = parameters[0].valueAsText
        if template and not os.path.isfile(template):
            parameters[0].setErrorMessage("No se encontro la plantilla PAGX.")
        output = parameters[12].valueAsText
        if output and os.path.splitext(output)[1].lower() not in (".pdf", ".png"):
            parameters[12].setErrorMessage("La salida debe terminar en .pdf o .png.")
        return

    def execute(self, parameters, messages):
        template = parameters[0].valueAsText
        areas = parameters[1].valueAsText
        owner_field = parameters[2].valueAsText
        owner = parameters[3].valueAsText
        points = parameters[4].valueAsText
        id_field = parameters[5].valueAsText
        predio_field = parameters[6].valueAsText
        vereda_field = parameters[7].valueAsText
        correg_field = parameters[8].valueAsText
        type_field = parameters[9].valueAsText
        margin = float(parameters[10].value or 0)
        title = parameters[11].valueAsText or "MONITOREO DE AREAS DE RESTAURACION"
        output = os.path.abspath(parameters[12].valueAsText)
        dpi = int(parameters[13].value)
        keep_layout = bool(parameters[14].value)

        os.makedirs(os.path.dirname(output), exist_ok=True)
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        before = {layout.name for layout in aprx.listLayouts()}

        messages.addMessage("Importando plantilla cartografica...")
        aprx.importDocument(template)
        layouts = [layout for layout in aprx.listLayouts() if layout.name not in before]
        if not layouts:
            layouts = aprx.listLayouts("LUIS FROILAN CANO CABRERA")
        if not layouts:
            raise arcpy.ExecuteError("ArcGIS Pro no pudo importar el layout de la plantilla.")
        layout = layouts[-1]
        layout.name = _unique_layout_name(aprx, _safe_name(owner), layout)

        frames = layout.listElements("MAPFRAME_ELEMENT", "Layers Map Frame")
        if not frames:
            raise arcpy.ExecuteError("La plantilla no contiene 'Layers Map Frame'.")
        frame = frames[0]
        map_obj = frame.map

        area_layer = _replace_or_add_layer(map_obj, "Area Restauracion", areas, messages)
        point_layer = None
        if points:
            point_layer = _replace_or_add_layer(map_obj, "Ubicacion Areas de Restauracion", points, messages)

        where = _where_equals(areas, owner_field, owner)
        area_layer.definitionQuery = where
        if point_layer:
            point_fields = {f.name.lower(): f.name for f in arcpy.ListFields(points)}
            point_owner_field = point_fields.get(owner_field.lower())
            if point_owner_field:
                point_layer.definitionQuery = _where_equals(points, point_owner_field, owner)

        values = _read_attributes(areas, where, [id_field, predio_field, vereda_field, correg_field])
        text_values = {
            "Text 6": owner,
            "Text 7": values.get(id_field, ""),
            "Text 8": values.get(predio_field, ""),
            "Text 9": values.get(vereda_field, ""),
            "Text 10": values.get(correg_field, ""),
        }
        for element_name, value in text_values.items():
            _set_text(layout, element_name, value)
        _set_text(layout, "Title", title)

        if type_field:
            types = _distinct_values(areas, where, type_field)
            messages.addMessage("Tipos de restauracion: " + (", ".join(types) if types else "sin dato"))

        messages.addMessage("Ajustando extension al area seleccionada...")
        arcpy.management.SelectLayerByAttribute(area_layer, "NEW_SELECTION", where)
        try:
            extent = frame.getLayerExtent(area_layer, True, True)
            frame.camera.setExtent(extent)
            frame.camera.scale *= 1.0 + (margin / 100.0)
        finally:
            arcpy.management.SelectLayerByAttribute(area_layer, "CLEAR_SELECTION")

        messages.addMessage("Exportando: " + output)
        extension = os.path.splitext(output)[1].lower()
        if extension == ".pdf":
            layout.exportToPDF(output, resolution=dpi, image_quality="BEST", embed_fonts=True)
        else:
            layout.exportToPNG(output, resolution=dpi, color_mode="32-BIT_WITH_ALPHA")

        if keep_layout:
            aprx.save()
            parameters[15].value = layout.name
        else:
            aprx.deleteItem(layout)
            parameters[15].value = "(layout temporal eliminado)"

        parameters[12].value = output
        messages.addMessage("Salida grafica generada correctamente.")


def _param(display, name, datatype, parameter_type, direction):
    return arcpy.Parameter(
        displayName=display,
        name=name,
        datatype=datatype,
        parameterType=parameter_type,
        direction=direction,
    )


def _first_existing_field(layer, candidates):
    if not layer:
        return None
    try:
        fields = {f.name.lower(): f.name for f in arcpy.ListFields(layer)}
        for candidate in candidates:
            if candidate.lower() in fields:
                return fields[candidate.lower()]
    except Exception:
        pass
    return None


def _safe_name(value):
    value = unicodedata.normalize("NFKD", value or "Salida_Grafica")
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return value[:100] or "Salida_Grafica"


def _unique_layout_name(aprx, base, current):
    names = {layout.name for layout in aprx.listLayouts() if layout is not current}
    candidate = base
    number = 2
    while candidate in names:
        candidate = "{}_{}".format(base, number)
        number += 1
    return candidate


def _replace_or_add_layer(map_obj, template_name, source, messages):
    matches = map_obj.listLayers(template_name)
    if matches:
        layer = matches[0]
        old = layer.connectionProperties
        desc = arcpy.Describe(source)
        new = {
            "connection_info": {"database": desc.path},
            "dataset": desc.name,
            "workspace_factory": "File Geodatabase" if str(desc.path).lower().endswith(".gdb") else "Shape File",
        }
        try:
            layer.updateConnectionProperties(old, new, validate=True)
            messages.addMessage("Fuente actualizada conservando simbologia: " + template_name)
            return layer
        except Exception as exc:
            messages.addWarningMessage("No se pudo reutilizar la simbologia de '{}': {}".format(template_name, exc))
            layer.visible = False
    layer = map_obj.addDataFromPath(source)
    layer.name = template_name + " (datos)"
    return layer


def _where_equals(dataset, field_name, value):
    field = next(f for f in arcpy.ListFields(dataset) if f.name.lower() == field_name.lower())
    delimited = arcpy.AddFieldDelimiters(dataset, field.name)
    if field.type in ("String", "Guid"):
        return "{} = '{}'".format(delimited, (value or "").replace("'", "''"))
    return "{} = {}".format(delimited, value)


def _read_attributes(dataset, where, requested_fields):
    fields = [name for name in requested_fields if name]
    if not fields:
        return {}
    with arcpy.da.SearchCursor(dataset, fields, where_clause=where) as rows:
        row = next(rows, None)
    if row is None:
        raise arcpy.ExecuteError("No se encontraron areas para el propietario indicado.")
    return {name: ("" if value is None else str(value)) for name, value in zip(fields, row)}


def _distinct_values(dataset, where, field_name):
    with arcpy.da.SearchCursor(dataset, [field_name], where_clause=where) as rows:
        return sorted({str(row[0]) for row in rows if row[0] not in (None, "")})


def _set_text(layout, element_name, value):
    elements = layout.listElements("TEXT_ELEMENT", element_name)
    if elements:
        elements[0].text = "" if value is None else str(value)


def _loaded_monitoring_layout(aprx):
    """Prefiere la vista de layout activa y luego cualquier layout compatible cargado."""
    try:
        active = aprx.activeView
        if active and hasattr(active, "listElements"):
            if active.listElements("MAPFRAME_ELEMENT", "Layers Map Frame"):
                return active
    except Exception:
        pass
    for layout in aprx.listLayouts():
        if layout.listElements("MAPFRAME_ELEMENT", "Layers Map Frame"):
            return layout
    return None


def _normalize(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).strip().casefold()


def _gdb_inventory(gdb):
    datasets = []
    for dirpath, _, filenames in arcpy.da.Walk(gdb, datatype=["FeatureClass", "RasterDataset"]):
        datasets.extend(os.path.join(dirpath, name) for name in filenames)
    if not datasets:
        raise arcpy.ExecuteError("La geodatabase no contiene clases de entidad.")
    return datasets


def _find_area_feature_class(inventory):
    ranked = []
    for path in inventory:
        try:
            desc = arcpy.Describe(path)
            if getattr(desc, "shapeType", None) != "Polygon":
                continue
            names = {f.name.lower() for f in arcpy.ListFields(path)}
            score = 0
            normalized = _normalize(os.path.basename(path))
            if "area_restauracion" in normalized.replace(" ", "_"):
                score += 10
            if any(x in names for x in ("propietario", "nombres_y_apellidos", "beneficiario")):
                score += 6
            if any(x in names for x in ("tipo_restauracion", "tipo_restaura", "tipo")):
                score += 3
            ranked.append((score, path))
        except Exception:
            continue
    if not ranked or max(ranked)[0] == 0:
        raise arcpy.ExecuteError("No se identifico automaticamente la capa de areas de restauracion.")
    return max(ranked)[1]


def _candidate_field(field_lookup, candidates):
    for candidate in candidates:
        if candidate.lower() in field_lookup:
            return field_lookup[candidate.lower()]
    normalized = {_normalize(key).replace("_", ""): value for key, value in field_lookup.items()}
    for candidate in candidates:
        key = _normalize(candidate).replace("_", "")
        if key in normalized:
            return normalized[key]
    return None


def _canonical_value(dataset, field_name, typed_value):
    wanted = _normalize(typed_value)
    partial = []
    with arcpy.da.SearchCursor(dataset, [field_name]) as rows:
        for row in rows:
            if row[0] is None:
                continue
            normalized = _normalize(row[0])
            if normalized == wanted:
                return str(row[0])
            if wanted and wanted in normalized:
                partial.append(str(row[0]))
    unique = sorted(set(partial))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        raise arcpy.ExecuteError("El nombre coincide con varias personas: " + "; ".join(unique[:10]))
    return None


def _find_excel_record(workbook, owner):
    old_workspace = arcpy.env.workspace
    try:
        arcpy.env.workspace = workbook
        tables = arcpy.ListTables() or []
        for table in tables:
            table_path = os.path.join(workbook, table)
            fields = {f.name.lower(): f.name for f in arcpy.ListFields(table_path)}
            owner_field = _candidate_field(fields, ["NOMBRES_Y_APELLIDOS", "PROPIETARIO", "BENEFICIARIO", "NOMBRE"])
            if not owner_field:
                continue
            names = [f.name for f in arcpy.ListFields(table_path) if f.type not in ("OID", "Geometry", "Blob", "Raster")]
            with arcpy.da.SearchCursor(table_path, names) as rows:
                owner_index = names.index(owner_field)
                for row in rows:
                    if _normalize(row[owner_index]) == _normalize(owner):
                        return {name: value for name, value in zip(names, row)}
    finally:
        arcpy.env.workspace = old_workspace
    raise arcpy.ExecuteError("Se encontro el nombre en la GDB, pero no en ninguna hoja del Excel.")


def _record_value(record, candidates):
    lookup = {key.lower(): key for key in record}
    field = _candidate_field(lookup, candidates)
    value = record.get(field, "") if field else ""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _area_totals(dataset, where, type_field):
    totals = {}
    fields = ["SHAPE@AREA"] + ([type_field] if type_field else [])
    spatial_reference = arcpy.Describe(dataset).spatialReference
    meters = getattr(spatial_reference, "metersPerUnit", 1.0) or 1.0
    with arcpy.da.SearchCursor(dataset, fields, where_clause=where) as rows:
        for row in rows:
            square_meters = float(row[0]) * meters * meters
            raw_type = row[1] if type_field else "total"
            key = _normalize(raw_type)
            if "activ" in key and "pasiv" not in key:
                key = "activa"
            elif "pasiv" in key:
                key = "pasiva"
            elif not key:
                key = "sin tipo"
            totals[key] = totals.get(key, 0.0) + square_meters
    if not totals:
        raise arcpy.ExecuteError("El beneficiario no tiene poligonos para calcular areas.")
    return totals


def _format_area(square_meters):
    hectares = int(square_meters // 10000)
    remainder = int(round(square_meters - hectares * 10000))
    if remainder == 10000:
        hectares += 1
        remainder = 0
    return "{} Ha + {} m2".format(hectares, remainder)


def _match_dataset(inventory, layer_name):
    wanted = _normalize(layer_name).replace("_", " ")
    exact = []
    for path in inventory:
        name = _normalize(os.path.basename(path)).replace("_", " ")
        if name == wanted:
            exact.append(path)
    return exact[0] if exact else None


def _replace_summary_text(layout, active, passive, total):
    elements = layout.listElements("TEXT_ELEMENT", "Text")
    if not elements:
        return
    text = elements[0].text
    text = re.sub(r"(Área de restauración Activa:\s*).*?(?=\r|\n)",
                  r"\g<1>" + _format_area(active), text, flags=re.IGNORECASE)
    text = re.sub(r"(Área de restauración Pasiva:\s*).*?(?=\r|\n)",
                  r"\g<1>" + _format_area(passive), text, flags=re.IGNORECASE)
    text = re.sub(r"(Área Total Intervenida:\s*).*?(?=\r|\n|$)",
                  r"\g<1>" + _format_area(total), text, flags=re.IGNORECASE)
    elements[0].text = text
