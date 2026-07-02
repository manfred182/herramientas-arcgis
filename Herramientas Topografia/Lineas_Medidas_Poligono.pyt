# -*- coding: utf-8 -*-
"""
Python Toolbox para crear lineas y medidas de los lados de poligonos.

Compatible con ArcGIS Desktop 10.x (Python 2.7) y ArcGIS Pro 3.x
(Python 3.x), usando unicamente ArcPy y sintaxis comun a ambas versiones.
"""

from __future__ import print_function

import math
import os

import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "Herramientas Topografia"
        self.alias = "herramientas_topografia"
        self.tools = [LineasMedidasPoligono]


class LineasMedidasPoligono(object):
    def __init__(self):
        self.label = "Crear lineas y medidas de poligono"
        self.description = (
            "Genera una entidad de linea por cada lado de uno o varios "
            "poligonos, calculando longitud, azimut, rumbo y coordenadas "
            "de vertices. Opcionalmente crea puntos de vertices."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        in_polygons = arcpy.Parameter(
            displayName="Poligonos de entrada",
            name="in_polygons",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        in_polygons.filter.list = ["Polygon"]

        out_lines = arcpy.Parameter(
            displayName="Lineas de lados de salida",
            name="out_lines",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )

        out_vertices = arcpy.Parameter(
            displayName="Puntos de vertices de salida (opcional)",
            name="out_vertices",
            datatype="DEFeatureClass",
            parameterType="Optional",
            direction="Output",
        )

        id_field = arcpy.Parameter(
            displayName="Campo identificador del poligono (opcional)",
            name="id_field",
            datatype="Field",
            parameterType="Optional",
            direction="Input",
        )
        id_field.parameterDependencies = [in_polygons.name]

        length_unit = arcpy.Parameter(
            displayName="Unidad de longitud",
            name="length_unit",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        length_unit.filter.type = "ValueList"
        length_unit.filter.list = [
            "Unidades de coordenadas",
            "Metros",
            "Kilometros",
            "Pies",
            "Millas",
        ]
        length_unit.value = "Unidades de coordenadas"

        close_ring = arcpy.Parameter(
            displayName="Crear segmento de cierre",
            name="close_ring",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        close_ring.value = True

        return [
            in_polygons,
            out_lines,
            out_vertices,
            id_field,
            length_unit,
            close_ring,
        ]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        if parameters[0].value:
            try:
                desc = arcpy.Describe(parameters[0].value)
                sr = desc.spatialReference
                if sr and sr.name and sr.name != "Unknown":
                    if getattr(sr, "type", "") == "Geographic":
                        parameters[4].setWarningMessage(
                            "La capa esta en coordenadas geograficas. "
                            "Para medidas topograficas precisas, proyecte "
                            "los poligonos a un sistema plano antes de "
                            "ejecutar la herramienta."
                        )
                else:
                    parameters[0].setWarningMessage(
                        "La referencia espacial es desconocida; revise las "
                        "unidades de longitud resultantes."
                    )
            except Exception:
                pass
        return

    def execute(self, parameters, messages):
        in_fc = parameters[0].valueAsText
        out_lines = parameters[1].valueAsText
        out_vertices = parameters[2].valueAsText
        id_field = parameters[3].valueAsText
        length_unit_label = parameters[4].valueAsText
        close_ring = _as_bool(parameters[5].value)

        desc = arcpy.Describe(in_fc)
        oid_field = desc.OIDFieldName
        spatial_ref = desc.spatialReference
        has_z = _describe_bool(desc, "hasZ")
        has_m = _describe_bool(desc, "hasM")
        unit_code = _length_unit_code(length_unit_label)

        _create_output_fc(out_lines, "POLYLINE", spatial_ref, has_z, has_m)
        line_fields = _add_line_fields(out_lines)

        make_vertices = bool(out_vertices)
        vertex_fields = None
        if make_vertices:
            _create_output_fc(out_vertices, "POINT", spatial_ref, has_z, has_m)
            vertex_fields = _add_vertex_fields(out_vertices)

        search_fields = [oid_field, "SHAPE@"]
        if id_field:
            search_fields.append(id_field)

        line_insert_fields = [
            "SHAPE@",
            line_fields["POLY_OID"],
            line_fields["ID_POL"],
            line_fields["PARTE"],
            line_fields["ANILLO"],
            line_fields["SEGMENTO"],
            line_fields["V_INI"],
            line_fields["V_FIN"],
            line_fields["X_INI"],
            line_fields["Y_INI"],
            line_fields["X_FIN"],
            line_fields["Y_FIN"],
            line_fields["LONGITUD"],
            line_fields["AZIMUT"],
            line_fields["RUMBO"],
        ]

        vertex_insert_fields = None
        if make_vertices:
            vertex_insert_fields = [
                "SHAPE@",
                vertex_fields["POLY_OID"],
                vertex_fields["ID_POL"],
                vertex_fields["PARTE"],
                vertex_fields["ANILLO"],
                vertex_fields["VERT_ID"],
                vertex_fields["X"],
                vertex_fields["Y"],
            ]

        total_polygons = 0
        total_lines = 0
        total_vertices = 0
        warned_length = False

        line_cursor = arcpy.da.InsertCursor(out_lines, line_insert_fields)
        vertex_cursor = None
        try:
            if make_vertices:
                vertex_cursor = arcpy.da.InsertCursor(
                    out_vertices, vertex_insert_fields
                )

            with arcpy.da.SearchCursor(in_fc, search_fields) as rows:
                for row in rows:
                    total_polygons += 1
                    oid_value = row[0]
                    polygon = row[1]
                    id_value = ""
                    if id_field:
                        id_value = _to_text(row[2])

                    if polygon is None or _is_empty_geometry(polygon):
                        arcpy.AddWarning(
                            "El poligono OID {0} no tiene geometria.".format(
                                oid_value
                            )
                        )
                        continue

                    for part_id, ring_id, vertices in _iter_polygon_rings(polygon):
                        if len(vertices) < 2:
                            continue

                        if make_vertices:
                            for vertex_id, point in enumerate(vertices, 1):
                                point_geom = arcpy.PointGeometry(
                                    _copy_point(point), spatial_ref
                                )
                                vertex_cursor.insertRow(
                                    [
                                        point_geom,
                                        oid_value,
                                        id_value,
                                        part_id,
                                        ring_id,
                                        vertex_id,
                                        point.X,
                                        point.Y,
                                    ]
                                )
                                total_vertices += 1

                        segment_pairs = _segment_pairs(vertices, close_ring)
                        for seg_id, item in enumerate(segment_pairs, 1):
                            from_index, to_index, p1, p2 = item
                            line_geom = arcpy.Polyline(
                                arcpy.Array([_copy_point(p1), _copy_point(p2)]),
                                spatial_ref,
                                has_z,
                                has_m,
                            )
                            try:
                                length_value = _measure_length(
                                    line_geom, unit_code
                                )
                            except Exception as length_error:
                                if not warned_length:
                                    arcpy.AddWarning(
                                        "No fue posible convertir la longitud "
                                        "a la unidad solicitada. Se usaran las "
                                        "unidades de coordenadas. Detalle: {0}".format(
                                            length_error
                                        )
                                    )
                                    warned_length = True
                                length_value = line_geom.length

                            azimuth = _azimuth_degrees(p1, p2)
                            bearing = _bearing_text(azimuth)

                            line_cursor.insertRow(
                                [
                                    line_geom,
                                    oid_value,
                                    id_value,
                                    part_id,
                                    ring_id,
                                    seg_id,
                                    from_index,
                                    to_index,
                                    p1.X,
                                    p1.Y,
                                    p2.X,
                                    p2.Y,
                                    length_value,
                                    azimuth,
                                    bearing,
                                ]
                            )
                            total_lines += 1
        finally:
            del line_cursor
            if vertex_cursor:
                del vertex_cursor

        arcpy.AddMessage(
            "Proceso terminado: {0} poligono(s), {1} linea(s) y {2} vertice(s).".format(
                total_polygons, total_lines, total_vertices
            )
        )


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "si", "yes")


def _describe_bool(desc, name):
    try:
        value = getattr(desc, name)
        if isinstance(value, bool):
            return value
        return str(value).lower() == "true"
    except Exception:
        return False


def _is_empty_geometry(geometry):
    try:
        return geometry.isEmpty
    except Exception:
        try:
            return geometry.pointCount == 0
        except Exception:
            return False


def _to_text(value):
    if value is None:
        return ""
    try:
        return str(value)
    except UnicodeEncodeError:
        return value.encode("utf-8")


def _length_unit_code(label):
    mapping = {
        "Unidades de coordenadas": None,
        "Metros": "METERS",
        "Kilometros": "KILOMETERS",
        "Pies": "FEET",
        "Millas": "MILES",
    }
    return mapping.get(label, None)


def _create_output_fc(out_fc, geometry_type, spatial_ref, has_z, has_m):
    if arcpy.Exists(out_fc):
        if arcpy.env.overwriteOutput:
            arcpy.Delete_management(out_fc)
        else:
            raise Exception(
                "La salida ya existe y overwriteOutput esta desactivado: {0}".format(
                    out_fc
                )
            )

    out_path = os.path.dirname(out_fc)
    out_name = os.path.basename(out_fc)
    if not out_path:
        out_path = arcpy.env.workspace
    if not out_path:
        raise Exception(
            "La ruta de salida debe incluir una carpeta o geodatabase."
        )

    z_flag = "ENABLED" if has_z else "DISABLED"
    m_flag = "ENABLED" if has_m else "DISABLED"
    arcpy.CreateFeatureclass_management(
        out_path,
        out_name,
        geometry_type,
        "",
        m_flag,
        z_flag,
        spatial_ref,
    )


def _add_line_fields(fc):
    fields = {}
    fields["POLY_OID"] = _add_field(fc, "POLY_OID", "LONG")
    fields["ID_POL"] = _add_field(fc, "ID_POL", "TEXT", 100)
    fields["PARTE"] = _add_field(fc, "PARTE", "LONG")
    fields["ANILLO"] = _add_field(fc, "ANILLO", "LONG")
    fields["SEGMENTO"] = _add_field(fc, "SEGMENTO", "LONG")
    fields["V_INI"] = _add_field(fc, "V_INI", "LONG")
    fields["V_FIN"] = _add_field(fc, "V_FIN", "LONG")
    fields["X_INI"] = _add_field(fc, "X_INI", "DOUBLE")
    fields["Y_INI"] = _add_field(fc, "Y_INI", "DOUBLE")
    fields["X_FIN"] = _add_field(fc, "X_FIN", "DOUBLE")
    fields["Y_FIN"] = _add_field(fc, "Y_FIN", "DOUBLE")
    fields["LONGITUD"] = _add_field(fc, "LONGITUD", "DOUBLE")
    fields["AZIMUT"] = _add_field(fc, "AZIMUT", "DOUBLE")
    fields["RUMBO"] = _add_field(fc, "RUMBO", "TEXT", 32)
    return fields


def _add_vertex_fields(fc):
    fields = {}
    fields["POLY_OID"] = _add_field(fc, "POLY_OID", "LONG")
    fields["ID_POL"] = _add_field(fc, "ID_POL", "TEXT", 100)
    fields["PARTE"] = _add_field(fc, "PARTE", "LONG")
    fields["ANILLO"] = _add_field(fc, "ANILLO", "LONG")
    fields["VERT_ID"] = _add_field(fc, "VERT_ID", "LONG")
    fields["X"] = _add_field(fc, "X", "DOUBLE")
    fields["Y"] = _add_field(fc, "Y", "DOUBLE")
    return fields


def _add_field(fc, name, field_type, length=None):
    workspace = os.path.dirname(fc)
    field_name = arcpy.ValidateFieldName(name, workspace)
    if field_type == "TEXT":
        arcpy.AddField_management(fc, field_name, field_type, "", "", length)
    else:
        arcpy.AddField_management(fc, field_name, field_type)
    return field_name


def _iter_polygon_rings(polygon):
    for part_index in range(polygon.partCount):
        part = polygon.getPart(part_index)
        ring_index = 1
        current = []

        for point in part:
            if point:
                current.append(point)
            else:
                clean_ring = _clean_ring(current)
                if len(clean_ring) > 0:
                    yield part_index + 1, ring_index, clean_ring
                    ring_index += 1
                current = []

        clean_ring = _clean_ring(current)
        if len(clean_ring) > 0:
            yield part_index + 1, ring_index, clean_ring


def _clean_ring(points):
    clean = [point for point in points if point]
    if len(clean) > 1 and _same_xy(clean[0], clean[-1]):
        clean = clean[:-1]
    return clean


def _same_xy(p1, p2):
    return p1.X == p2.X and p1.Y == p2.Y


def _segment_pairs(vertices, close_ring):
    pairs = []
    count = len(vertices)
    last = count if close_ring else count - 1
    for index in range(last):
        from_index = index + 1
        to_index = index + 2
        if index == count - 1:
            to_index = 1
            p2 = vertices[0]
        else:
            p2 = vertices[index + 1]
        pairs.append((from_index, to_index, vertices[index], p2))
    return pairs


def _copy_point(point):
    new_point = arcpy.Point()
    new_point.X = point.X
    new_point.Y = point.Y
    try:
        new_point.Z = point.Z
    except Exception:
        pass
    try:
        new_point.M = point.M
    except Exception:
        pass
    return new_point


def _measure_length(line_geom, unit_code):
    if unit_code:
        return line_geom.getLength("PLANAR", unit_code)
    return line_geom.length


def _azimuth_degrees(p1, p2):
    dx = p2.X - p1.X
    dy = p2.Y - p1.Y
    if dx == 0 and dy == 0:
        return 0.0
    angle = math.degrees(math.atan2(dx, dy))
    if angle < 0:
        angle += 360.0
    return angle


def _bearing_text(azimuth):
    azimuth = azimuth % 360.0

    if azimuth == 0:
        return "N 00d00m00s E"
    if azimuth == 90:
        return "N 90d00m00s E"
    if azimuth == 180:
        return "S 00d00m00s E"
    if azimuth == 270:
        return "N 90d00m00s W"

    if 0 < azimuth < 90:
        prefix = "N"
        suffix = "E"
        bearing = azimuth
    elif 90 < azimuth < 180:
        prefix = "S"
        suffix = "E"
        bearing = 180.0 - azimuth
    elif 180 < azimuth < 270:
        prefix = "S"
        suffix = "W"
        bearing = azimuth - 180.0
    else:
        prefix = "N"
        suffix = "W"
        bearing = 360.0 - azimuth

    return "{0} {1} {2}".format(prefix, _format_dms(bearing), suffix)


def _format_dms(angle):
    degrees_value = int(angle)
    minutes_full = (angle - degrees_value) * 60.0
    minutes_value = int(minutes_full)
    seconds_value = int(round((minutes_full - minutes_value) * 60.0))

    if seconds_value == 60:
        seconds_value = 0
        minutes_value += 1
    if minutes_value == 60:
        minutes_value = 0
        degrees_value += 1

    return "{0:02d}d{1:02d}m{2:02d}s".format(
        degrees_value, minutes_value, seconds_value
    )
