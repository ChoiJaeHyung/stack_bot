' run_bot_hidden.vbs - Launch bot_brain.py directly (no bat intermediary)
' Calls python.exe directly to avoid cmd.exe process chain issues
' Window style 0 = hidden, False = async (don't wait for exit)

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\mybot_ver2"

Dim pythonExe, scriptArgs
pythonExe = "C:\Users\jhchoi\AppData\Local\Python\pythoncore-3.14-64\python.exe"
scriptArgs = "-u bot_brain.py --loop"

WshShell.Run """" & pythonExe & """ " & scriptArgs, 0, False

Set WshShell = Nothing
