# Generador de salidas gráficas para ArcGIS Pro

Esta caja de herramientas importa la plantilla de monitoreo de Florencia, conecta los datos del beneficiario, filtra sus áreas, completa la información del plano, centra el mapa y exporta el resultado. Su herramienta principal solo requiere la GDB, el Excel y el nombre del beneficiario.

## Instalación como complemento de ArcGIS Pro

Para ArcGIS Pro 3.3 o posterior, haz doble clic en `SalidasGraficas_Flotante.esriAddInX`, acepta la instalación y reinicia ArcGIS Pro. Aparecerá la pestaña **SALIDAS GRÁFICAS** con el botón **Ventana de salidas**.

El botón abre una ventana independiente y flotante. La ventana no muestra el panel de Geoprocesamiento: recibe el nombre y ejecuta el proceso internamente sobre el layout de monitoreo que esté abierto o cargado en el proyecto.

El complemento incluye internamente la plantilla PAGX y la caja de herramientas, por lo que no depende de que esos dos archivos permanezcan en una ubicación externa.

## Instalación manual como caja de herramientas

1. Mantén juntos estos archivos:
   - `SalidasGraficas.pyt`
   - `Plantilla_Monitoreo_Florencia.pagx`
2. Abre tu proyecto en **ArcGIS Pro 3.6**.
3. En el panel **Catálogo**, haz clic derecho en **Cajas de herramientas** → **Agregar caja de herramientas**.
4. Selecciona `SalidasGraficas.pyt`.
5. Abre **Generar salida automática por nombre**.

## Uso

1. Selecciona la geodatabase maestra y el Excel de beneficiarios.
2. Escribe el nombre del beneficiario. La búsqueda ignora mayúsculas y tildes; también acepta un fragmento si solo existe una coincidencia.
3. Selecciona la carpeta de salida y ejecuta.

La herramienta detecta la capa de áreas y sus campos, consulta el beneficiario en todas las hojas del Excel, repara las fuentes cartográficas de la plantilla cuyos nombres coincidan con clases de la GDB, calcula las áreas activa y pasiva directamente desde la geometría y genera un PDF con el nombre del beneficiario.

La herramienta secundaria **Generar salida gráfica** mantiene controles manuales para casos especiales.

La herramienta intenta reutilizar la simbología de las capas `Area Restauracion` y `Ubicacion Areas de Restauracion` de la plantilla. Para conservarla íntegramente, la geometría y los campos de entrada deben ser compatibles con los originales.

## Resultado

- Layout tamaño carta vertical basado en la plantilla suministrada.
- Filtro por beneficiario mediante consulta de definición.
- Textos del beneficiario actualizados.
- Zoom automático al área de restauración con margen configurable.
- Exportación predeterminada a 300 DPI.
- Opción de conservar el layout generado dentro del proyecto abierto.

## Consideraciones

- Ejecuta la herramienta dentro de ArcGIS Pro; usa `ArcGISProject("CURRENT")`.
- Si el proyecto o la salida están bloqueados por otra aplicación, ciérralos antes de ejecutar.
- Las capas cartográficas auxiliares de la plantilla conservan sus rutas originales. Si aparecen con fuente rota, repáralas una vez desde **Propiedades de la capa → Fuente**; ArcGIS Pro conservará esa reparación en el proyecto.
