# A real, unedited `receipts fix` run on another repository (PyFlakes issue 335) on Nebius Token Factory Sandboxes.
# Run from the repository root: vhs video/tapes/fix-tf.tape
Output video/public/captures/fix-tf.mp4

Set Shell "bash"
Set FontSize 30
Set Width 2560
Set Height 1440
Set Padding 72
Set LineHeight 1.35
Set Theme "GitHub Dark"
Set TypingSpeed 35ms
Set CursorBlink false

Hide
Type "export PS1='$ ' PYTHONUNBUFFERED=1 FORCE_COLOR=1 && rm -rf runs/pyflakes-335 runs/fix-session.log && mkdir -p runs && exec > >(tee -a runs/fix-session.log) 2>&1 && clear"
Enter
Show

Sleep 1s
Type `uv run receipts fix --executor tokenfactory \`
Enter
Type `  --image docker.io/swerebenchv2/pycqa-pyflakes:335-4b2d720 --workdir /pyflakes \`
Enter
Type `  --test pyflakes/test/test_other.py::TestUnusedAssignment::test_unusedUnderscoreVariable \`
Enter
Type `  --test-patch demo/pyflakes-335/test.patch --issue-file demo/pyflakes-335/issue.md \`
Enter
Type `  --suite pyflakes/test --out runs/pyflakes-335`
Sleep 600ms
Enter
# VHS stops reading the screen once this output passes about 28 rows, so a Wait never fires;
# the run takes about two minutes, and a fixed sleep records all of it plus the summary.
Sleep 200s
