# Visual design

The look of the application is designed in Figma and implemented in `ui/theme.py`.

* **Figma file:** https://www.figma.com/design/TEnL3YXEBswCdTz1l1cKRa  ("Office Assistant - New GUI")
  * page *Design System*: colour tokens (Dark + Light), type scale, button components
  * page *Screens*: Login, Manager Dashboard, Employee Session, AI Chat -- each in Dark and Light (colours bound to variables)
* **Direction:** enterprise blue with an amber highlight, a data-dense dashboard style (chosen with the ui-ux-pro-max design
  skill for an analytics / productivity product), Inter in Figma = Segoe UI in the app, an 8 px grid, 12-16 px radii.

## Colour tokens (Figma variable -> `theme.py` key)

| token | Dark | Light | `theme.py` key |
|---|---|---|---|
| bg | #0B1220 | #F3F6FB | BACKGROUND |
| surface | #111B2E | #FFFFFF | SURFACE |
| surface-hover | #17233B | #EEF3FB | SURFACE_HOVER |
| surface-raised | #1C2A47 | #E6EDF8 | SURFACE_ELEVATED |
| border | #26354F | #DCE4F0 | BORDER |
| text / text-2 / text-muted | #E8EEF9 / #AAB6CC / #7A8AA6 | #0F1B33 / #44526B / #66758F | TEXT_PRIMARY / TEXT_SECONDARY / TEXT_MUTED |
| primary | #2563EB | #1E40AF | ACCENT |
| primary-text | #8DB4FF | #1E40AF | ACCENT_TEXT |
| amber (warning) | #F59E0B | #B45309 | WARNING |
| success | #2FBF8A | #0F7B53 | SUCCESS |
| danger | #EF5350 | #C62828 | DANGER |

Text colours keep at least 4.5:1 contrast on their surfaces in both themes.

## Icons
`ui/icons.py` draws the line icons of the design (Lucide-style SVG) in the current theme colour; the sidebar, the logo tile and
the Home cards use them. Widgets that draw icons implement `on_theme_changed()`, which `theme.apply_theme` calls on every switch.
Remaining emoji (card titles on some screens, the login role buttons) are the next candidates to convert.
