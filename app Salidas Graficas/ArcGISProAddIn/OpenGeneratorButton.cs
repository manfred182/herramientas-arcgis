using ArcGIS.Desktop.Framework.Contracts;

namespace SalidasGraficasAddIn;

internal class OpenGeneratorButton : Button
{
    protected override void OnClick()
    {
        FloatingGeneratorWindow.ShowGenerator();
    }
}
