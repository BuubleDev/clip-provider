Option Explicit
Dim shell, fso, pythonw, app
Set fso = CreateObject("Scripting.FileSystemObject")
pythonw = "pythonw.exe"
app = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "app\app.py")
Set shell = CreateObject("WScript.Shell")
shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & app & Chr(34), 0, False
