import arcpy
import math


class Toolbox(object):
    def __init__(self):
        self.label = "Herramientas de V\u00e9rtices"
        self.alias = "V\u00e9rticesCardinales"
        self.tools = [SeleccionPuntosCardinales]


class SeleccionPuntosCardinales(object):
    def __init__(self):
        self.label = "Seleccion Puntos Cardinales"
        self.description = (
            "Detecta y selecciona autom\u00e1ticamente todas las esquinas "
            "de cada pol\u00edgono mediante el orden de los v\u00e9rtices."
        )
        self.can_run_background = False

    def getParameterInfo(self):
        param_in = arcpy.Parameter(
            displayName="Capa de Puntos de Entrada",
            name="in_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input")
        param_in.filter.list = ["Point"]

        param_out = arcpy.Parameter(
            displayName="Capa de Salida (Esquinas)",
            name="out_features",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output")

        param_poly = arcpy.Parameter(
            displayName="Campo identificador de pol\u00edgono",
            name="polygon_field",
            datatype="Field",
            parameterType="Required",
            direction="Input")
        param_poly.parameterDependencies = [param_in.name]

        return [param_in, param_out, param_poly]

    @staticmethod
    def _dist_punto_linea(p, a, b):
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0, min(1, t))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    @classmethod
    def _rdp(cls, pts_idx, inicio, fin, epsilon, pts_xy):
        if fin - inicio < 2:
            return [pts_idx[inicio], pts_idx[fin]]
        dmax = 0
        idx = inicio
        a = pts_xy[pts_idx[inicio]]
        b = pts_xy[pts_idx[fin]]
        for i in range(inicio + 1, fin):
            d = cls._dist_punto_linea(pts_xy[pts_idx[i]], a, b)
            if d > dmax:
                dmax = d
                idx = i
        if dmax > epsilon:
            izq = cls._rdp(pts_idx, inicio, idx, epsilon, pts_xy)
            der = cls._rdp(pts_idx, idx, fin, epsilon, pts_xy)
            return izq[:-1] + der
        else:
            return [pts_idx[inicio], pts_idx[fin]]

    def execute(self, parameters, messages):
        input_fc = parameters[0].valueAsText
        output_fc = parameters[1].valueAsText
        poly_field = parameters[2].valueAsText

        desc = arcpy.Describe(input_fc)
        oid_field = desc.OIDFieldName

        grupos = {}
        with arcpy.da.SearchCursor(
            input_fc, [oid_field, poly_field, "SHAPE@XY"]
        ) as cursor:
            for oid, pid, xy in cursor:
                if pid not in grupos:
                    grupos[pid] = []
                grupos[pid].append({"oid": oid, "xy": xy})

        num_pol = len(grupos)
        messages.addMessage(f"{num_pol} pol\u00edgono(s), {sum(len(g) for g in grupos.values())} puntos totales")

        esquinas = []
        for pid, pts in grupos.items():
            n = len(pts)
            if n < 3:
                esquinas.extend(p["oid"] for p in pts)
                continue

            pts_ord = sorted(pts, key=lambda p: p["oid"])
            xs = [p["xy"][0] for p in pts_ord]
            ys = [p["xy"][1] for p in pts_ord]
            diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            epsilon = diag * 0.02

            pts_xy = [p["xy"] for p in pts_ord]
            pts_xy.append(pts_ord[0]["xy"])
            idx_orden = list(range(n + 1))

            simplificados = self._rdp(idx_orden, 0, n, epsilon, pts_xy)

            vistos = set()
            for idx in simplificados:
                oid = pts_ord[0]["oid"] if idx == n else pts_ord[idx]["oid"]
                if oid not in vistos:
                    vistos.add(oid)
                    esquinas.append(oid)

        if not esquinas:
            messages.addErrorMessage("No se detectaron esquinas.")
            return

        where = f"{oid_field} IN ({','.join(map(str, esquinas))})"
        arcpy.management.SelectLayerByAttribute(input_fc, "NEW_SELECTION", where)
        arcpy.management.CopyFeatures(input_fc, output_fc)
        arcpy.management.SelectLayerByAttribute(input_fc, "CLEAR_SELECTION")

        messages.addMessage(f"OK: {len(esquinas)} esquinas detectadas en {num_pol} pol\u00edgono(s)")
