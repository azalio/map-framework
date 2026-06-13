# VHS tape for the MAP golden-path demo. Render with: vhs docs/demo.tape
# Produces docs/demo.gif. Source script: docs/demo.sh (honest, stylized — not a
# live agent capture). Edit demo.sh for content, then re-run this tape.

Output docs/demo.gif

Require bash

Set Shell bash
Set FontSize 19
Set Width 1100
Set Height 720
Set Padding 26
Set PlaybackSpeed 1.0

Hide
Type "bash docs/demo.sh"
Enter
Sleep 500ms
Show
Sleep 19s
