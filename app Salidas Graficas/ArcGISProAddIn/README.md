# Complemento para la cinta de ArcGIS Pro

El proyecto genera `SalidasGraficasAddIn.esriAddInX`, un instalador de doble clic compatible con ArcGIS Pro 3.3 o posterior.

Una vez instalado, ArcGIS Pro muestra la pestaña **SALIDAS GRÁFICAS**, el grupo **Monitoreo** y el botón **Ventana de salidas**. El botón abre una ventana flotante propia; el motor se ejecuta en segundo plano y actualiza directamente el layout de monitoreo cargado, sin abrir el panel de Geoprocesamiento.

Para recompilar:

```powershell
dotnet build .\SalidasGraficasAddIn.csproj -c Release
```

El paquete se genera bajo `bin\Release\net8.0-windows`.
