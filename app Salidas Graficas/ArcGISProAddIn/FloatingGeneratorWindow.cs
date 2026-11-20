using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using ArcGIS.Desktop.Core.Geoprocessing;
using ArcGIS.Desktop.Framework;
using ArcGIS.Desktop.Framework.Controls;

namespace SalidasGraficasAddIn;

internal sealed class FloatingGeneratorWindow : ProWindow
{
    private static FloatingGeneratorWindow? _instance;
    private readonly TextBox _beneficiary;
    private readonly Button _runButton;
    private readonly TextBlock _status;
    private readonly ProgressBar _progress;

    private FloatingGeneratorWindow()
    {
        Title = "Salidas Gráficas - Monitoreo";
        Width = 430;
        Height = 310;
        MinWidth = 390;
        MinHeight = 280;
        ResizeMode = ResizeMode.CanResize;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        Owner = FrameworkApplication.Current.MainWindow;
        ShowInTaskbar = false;

        var root = new Grid { Margin = new Thickness(22) };
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

        var title = new TextBlock
        {
            Text = "Actualizar plantilla cargada",
            FontSize = 20,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 0, 0, 8)
        };
        Grid.SetRow(title, 0);
        root.Children.Add(title);

        var explanation = new TextBlock
        {
            Text = "Escribe el nombre del beneficiario. Se actualizarán directamente el layout activo, sus consultas, textos, áreas y extensión.",
            TextWrapping = TextWrapping.Wrap,
            Foreground = Brushes.DimGray,
            Margin = new Thickness(0, 0, 0, 16)
        };
        Grid.SetRow(explanation, 1);
        root.Children.Add(explanation);

        var inputPanel = new StackPanel { Margin = new Thickness(0, 0, 0, 14) };
        inputPanel.Children.Add(new TextBlock
        {
            Text = "Nombre del beneficiario",
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 0, 0, 5)
        });
        _beneficiary = new TextBox
        {
            Height = 32,
            FontSize = 14,
            VerticalContentAlignment = VerticalAlignment.Center
        };
        _beneficiary.KeyDown += (_, e) =>
        {
            if (e.Key == System.Windows.Input.Key.Enter && _runButton?.IsEnabled == true)
                _ = RunAsync();
        };
        inputPanel.Children.Add(_beneficiary);
        Grid.SetRow(inputPanel, 2);
        root.Children.Add(inputPanel);

        var actionPanel = new Grid();
        actionPanel.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        actionPanel.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        _progress = new ProgressBar
        {
            IsIndeterminate = true,
            Height = 5,
            Visibility = Visibility.Collapsed,
            Margin = new Thickness(0, 14, 16, 0)
        };
        actionPanel.Children.Add(_progress);
        _runButton = new Button
        {
            Content = "Actualizar plantilla",
            MinWidth = 150,
            Height = 36,
            FontWeight = FontWeights.SemiBold
        };
        _runButton.Click += async (_, _) => await RunAsync();
        Grid.SetColumn(_runButton, 1);
        actionPanel.Children.Add(_runButton);
        Grid.SetRow(actionPanel, 3);
        root.Children.Add(actionPanel);

        _status = new TextBlock
        {
            Text = "Abre la plantilla en una vista de layout antes de actualizar.",
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 16, 0, 0)
        };
        Grid.SetRow(_status, 4);
        root.Children.Add(_status);

        Content = root;
        Closed += (_, _) => _instance = null;
    }

    public static void ShowGenerator()
    {
        if (_instance is null)
        {
            _instance = new FloatingGeneratorWindow();
            _instance.Show();
        }
        else
        {
            if (_instance.WindowState == WindowState.Minimized)
                _instance.WindowState = WindowState.Normal;
            _instance.Activate();
        }
        _instance._beneficiary.Focus();
    }

    private async System.Threading.Tasks.Task RunAsync()
    {
        var name = _beneficiary.Text.Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            _status.Text = "Escribe el nombre del beneficiario.";
            _beneficiary.Focus();
            return;
        }

        var toolbox = FindPackagedToolbox();
        if (toolbox is null)
        {
            System.Windows.MessageBox.Show("No se encontró el motor incluido. Reinstala el complemento.", "Salidas Gráficas");
            return;
        }

        _runButton.IsEnabled = false;
        _beneficiary.IsEnabled = false;
        _progress.Visibility = Visibility.Visible;
        _status.Text = "Consultando Excel y GDB; actualizando el layout cargado...";

        try
        {
            var toolPath = Path.Combine(toolbox, "GenerarSalidaAutomatica");
            var template = Path.Combine(Path.GetDirectoryName(toolbox)!, "Plantilla_Monitoreo_Florencia.pagx");
            const string projectRoot = @"F:\Trabajos Independientes Amazon GIS\Proyecto Restauracion FA Amazonas";
            var gdb = Path.Combine(projectRoot, "Base de Datos Geografica", "Base_Restautacion_compilada", "Base_Restauracion_ajustada.gdb");
            var excel = Path.Combine(projectRoot, "Tablas de Datos Geoestadisticos.xlsx");
            var outputDirectory = Path.Combine(projectRoot, "Salidas Graficas Automaticas");

            if (!File.Exists(template))
                throw new FileNotFoundException("No se encontró la plantilla incluida.", template);
            if (!Directory.Exists(gdb))
                throw new DirectoryNotFoundException("No se encontró la geodatabase configurada: " + gdb);
            if (!File.Exists(excel))
                throw new FileNotFoundException("No se encontró el Excel configurado.", excel);

            IReadOnlyList<string> arguments = Geoprocessing.MakeValueArray(
                template, gdb, excel, name, outputDirectory, 300, 12, true);
            var result = await Geoprocessing.ExecuteToolAsync(
                toolPath, arguments, null, null, GPExecuteToolFlags.Default);

            if (result is null)
                throw new InvalidOperationException("ArcGIS Pro no devolvió un resultado al ejecutar el motor de actualización.");

            var details = result.Messages is null
                ? string.Empty
                : string.Join(Environment.NewLine,
                    result.Messages.Where(m => m is not null).Select(m => m.Text ?? string.Empty));
            if (result.IsFailed)
            {
                _status.Text = "No se pudo actualizar la plantilla.";
                if (string.IsNullOrWhiteSpace(details))
                    details = "ArcGIS Pro indicó que la ejecución falló, pero no devolvió mensajes. Verifica que el layout de monitoreo esté cargado y activo.";
                System.Windows.MessageBox.Show(details, "Error al actualizar");
            }
            else
            {
                _status.Text = "Plantilla actualizada correctamente para: " + name;
            }
        }
        catch (Exception ex)
        {
            _status.Text = "Ocurrió un error durante la actualización.";
            System.Windows.MessageBox.Show(
                ex.Message + "\n\nTipo: " + ex.GetType().Name,
                "Salidas Gráficas");
        }
        finally
        {
            _progress.Visibility = Visibility.Collapsed;
            _runButton.IsEnabled = true;
            _beneficiary.IsEnabled = true;
            _beneficiary.SelectAll();
            _beneficiary.Focus();
        }
    }

    private static string? FindPackagedToolbox()
    {
        var directory = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        if (string.IsNullOrWhiteSpace(directory))
            return null;
        var direct = Path.Combine(directory, "Resources", "SalidasGraficas.pyt");
        if (File.Exists(direct))
            return direct;
        return Directory.EnumerateFiles(directory, "SalidasGraficas.pyt", SearchOption.AllDirectories)
            .FirstOrDefault();
    }
}
