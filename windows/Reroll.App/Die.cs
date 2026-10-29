using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;

namespace Reroll.App;

/// <summary>Reroll's mark: a die. Filled (black, white pips) or outlined (as in the play list,
/// where the face is the number of kills).</summary>
public sealed class Die : Grid
{
    static readonly Dictionary<int, int[]> Faces = new()
    {
        [1] = [4], [2] = [0, 8], [3] = [0, 4, 8], [4] = [0, 2, 6, 8], [5] = [0, 2, 4, 6, 8], [6] = [0, 2, 3, 5, 6, 8],
    };

    readonly Border _body = new();
    readonly Ellipse[] _pips = new Ellipse[9];

    public Die()
    {
        var grid = new Grid();
        for (int i = 0; i < 3; i++)
        {
            grid.RowDefinitions.Add(new RowDefinition());
            grid.ColumnDefinitions.Add(new ColumnDefinition());
        }
        for (int i = 0; i < 9; i++)
        {
            _pips[i] = new Ellipse { HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
            Grid.SetRow(_pips[i], i / 3);
            Grid.SetColumn(_pips[i], i % 3);
            grid.Children.Add(_pips[i]);
        }
        _body.Child = grid;
        Children.Add(_body);
        Apply();
    }

    public int Face { get => (int)GetValue(FaceProperty); set => SetValue(FaceProperty, value); }
    public static readonly DependencyProperty FaceProperty =
        DependencyProperty.Register(nameof(Face), typeof(int), typeof(Die), new PropertyMetadata(2, (d, _) => ((Die)d).Apply()));

    public double Size { get => (double)GetValue(SizeProperty); set => SetValue(SizeProperty, value); }
    public static readonly DependencyProperty SizeProperty =
        DependencyProperty.Register(nameof(Size), typeof(double), typeof(Die), new PropertyMetadata(26.0, (d, _) => ((Die)d).Apply()));

    public bool Outline { get => (bool)GetValue(OutlineProperty); set => SetValue(OutlineProperty, value); }
    public static readonly DependencyProperty OutlineProperty =
        DependencyProperty.Register(nameof(Outline), typeof(bool), typeof(Die), new PropertyMetadata(false, (d, _) => ((Die)d).Apply()));

    void Apply()
    {
        var s = Size;
        Width = Height = s;
        _body.CornerRadius = new CornerRadius(s * 0.24);
        _body.Padding = new Thickness(s * 0.14);
        var ink = new SolidColorBrush(Colors.Black);
        var paper = new SolidColorBrush(Colors.White);
        _body.Background = Outline ? paper : ink;
        _body.BorderBrush = ink;
        _body.BorderThickness = new Thickness(Outline ? Math.Max(1.5, s * 0.07) : 0);
        var on = Faces.GetValueOrDefault(Math.Clamp(Face, 1, 6), Faces[1]);
        for (int i = 0; i < 9; i++)
        {
            _pips[i].Width = _pips[i].Height = s * 0.17;
            _pips[i].Fill = Outline ? ink : paper;
            _pips[i].Opacity = on.Contains(i) ? 1 : 0;
        }
    }
}
