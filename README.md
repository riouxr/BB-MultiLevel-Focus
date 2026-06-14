# BB MultiLevel Focus

A Blender extension for multi-level viewport focus and object isolation.

## Features

- **View Selected** — Zooms the viewport to the current selection. If nothing is selected, fits the entire scene. Mirror modifiers are temporarily hidden so they don't skew the framing.
- **Local View (Multi-Level)** — Isolates the selected objects using Blender's Local View, but with a history stack. You can keep drilling deeper into sub-selections and step back out level by level.
- **Inverted Isolation** — Isolate everything *except* the selection.
- **Keep Lights Visible** — Isolate the selection while leaving lights visible, so the scene stays lit while you work.
- **Mirror Suppression** — Optionally hides Mirror modifiers on focused objects to reduce visual noise while working.
- **HUD** — A white border and "Focus Level: N" label appear in the viewport while you're inside an isolation level.

## Keymaps

| Shortcut | Action |
|---|---|
| `F` | View Selected |
| `Ctrl + F` | Enter / step deeper into Local View isolation |
| `Ctrl + Alt + F` | Enter isolation (inverted — hide selection, keep the rest) |
| `Ctrl + Shift + F` | Isolate the selection but keep lights visible |

Pressing `Ctrl + F` again when nothing new is selected steps back out one level.

## Installation

**Blender 4.2+ (Extension)**

1. Download the latest `.zip` from the [Releases](https://github.com/riouxr/BB-MultiLevel-Focus/releases) page.
2. In Blender: *Edit → Preferences → Add-ons → Install from Disk* and select the zip.

**Manual**

Clone or download this repository and place the `BB-MultiLevel-Focus` folder in your Blender `addons` directory, then enable it in Preferences.

## Preferences

One preference is available under *Edit → Preferences → Add-ons → BB MultiLevel Focus*:

| Setting | Default | Description |
|---|---|---|
| Viewport Tweening | On | Animate the viewport when zooming to selection |

## Compatibility

Blender **4.2 – 5.1+**

## License

GPL-2.0-or-later
