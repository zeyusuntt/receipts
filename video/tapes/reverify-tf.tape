# A real, unedited re-verification of the featured receipt on Nebius Token Factory Sandboxes.
# Run from the repository root: vhs video/tapes/reverify-tf.tape
Output video/public/captures/reverify-tf.mp4

Set Shell "bash"
Set FontSize 30
Set Width 2560
Set Height 1440
Set Padding 72
Set LineHeight 1.35
Set Theme "GitHub Dark"
Set TypingSpeed 45ms
Set CursorBlink false

Hide
Type "export PS1='$ ' && clear"
Enter
Show

Sleep 1s
Type "uv run receipts reverify receipts/pyfilesystem__pyfilesystem2-462.json --executor tokenfactory"
Sleep 600ms
Enter
Wait+Screen@240s /Official resolved/
Sleep 4s
