import os
import sys
import subprocess

def create_shortcut(hotkey="CTRL+ALT+L", mode="cmd"):
    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    system_root = os.environ.get("SystemRoot", "C:\\Windows")
    cmd_exe = os.path.join(system_root, "System32", "cmd.exe")
    if not os.path.exists(cmd_exe):
        cmd_exe = "cmd.exe"

    powershell_exe = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if not os.path.exists(powershell_exe):
        powershell_exe = "powershell.exe"

    ico = os.path.join(workspace, "lion_logo.ico")
    hotkey_str = hotkey.upper().strip() if hotkey else "CTRL+ALT+L"

    # Command prompt launch arguments:
    # /k keeps the console open so the user can see live logs and server status
    cmd_args = '/k "title LionReel Studio Dashboard && if exist .venv\\Scripts\\python.exe (.venv\\Scripts\\python.exe web_server.py) else (python web_server.py)"'
    cmd_args_ps = cmd_args.replace('"', '`"')

    ps_code = f"""
    $WScriptShell = New-Object -ComObject WScript.Shell
    $paths = @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:USERPROFILE 'Desktop')) | Select-Object -Unique
    foreach ($dir in $paths) {{
        if (Test-Path $dir) {{
            $lnk = Join-Path $dir 'LionReel Studio.lnk'
            $s = $WScriptShell.CreateShortcut($lnk)
            $s.TargetPath = '{cmd_exe}'
            $s.Arguments = "{cmd_args_ps}"
            $s.WorkingDirectory = '{workspace}'
            $s.Description = 'Launch LionReel Studio Dashboard in Command Prompt'
            $s.Hotkey = '{hotkey_str}'
            if (Test-Path '{ico}') {{
                $s.IconLocation = '{ico},0'
            }}
            $s.Save()
            Write-Host "Created shortcut: $lnk"
        }}
    }}
    """

    res = subprocess.run([powershell_exe, "-NoProfile", "-Command", ps_code], capture_output=True, text=True)
    if res.returncode == 0:
        return True, f"Command Prompt shortcut created on Desktop (Hotkey: {hotkey_str})"
    else:
        return False, res.stderr.strip() or "PowerShell shortcut creation failed"

if __name__ == "__main__":
    success, msg = create_shortcut()
    print("Success:", success)
    print("Message:", msg)
