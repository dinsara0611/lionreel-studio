import os
import sys
import json
import subprocess
import threading
import socketserver
from http.server import SimpleHTTPRequestHandler

PORT = 8000
RUNNING_PROCESS = None
LOG_FILE = "gui_run.log"
CONFIG_FILE = "config.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FINISHED_DIR = os.path.join(BASE_DIR, "finished")
RAW_DIR = os.path.join(BASE_DIR, "raw")

DEFAULT_CONFIG = {
    "VIDEO_MODE": "mix",
    "SOURCE_MODE": "classic",
    "BYPASS_QUALITY_GATE": True,
    "BYPASS_FUNNY_CHECK": True,
    "TARGET_CLIPS": "6",
    "SHORT_CLIP_SEC": "9.0"
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except:
            pass
    return DEFAULT_CONFIG

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=4)
        return True
    except:
        return False

def ensure_icon():
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(workspace_dir, "lion_logo.png")
    ico_path = os.path.join(workspace_dir, "lion_logo.ico")
    
    if os.path.exists(png_path) and not os.path.exists(ico_path):
        try:
            from PIL import Image
            img = Image.open(png_path)
            icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
            img.save(ico_path, format="ICO", sizes=icon_sizes)
            return True
        except Exception as e:
            print(f"Error creating ico from png: {e}")
    return os.path.exists(ico_path)


class DashboardHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        global RUNNING_PROCESS
        
        # Route API Calls
        if self.path.startswith("/api/status"):
            is_running = False
            if RUNNING_PROCESS is not None:
                if RUNNING_PROCESS.poll() is None:
                    is_running = True
                else:
                    RUNNING_PROCESS = None
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "running" if is_running else "idle"}).encode())
            return

        elif self.path.startswith("/api/config"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(load_config()).encode())
            return

        elif self.path.startswith("/api/logs"):
            # Parse offset query parameter
            offset = 0
            if "offset=" in self.path:
                try:
                    offset = int(self.path.split("offset=")[1].split("&")[0])
                except:
                    pass
            
            logs = ""
            new_offset = offset
            if os.path.exists(LOG_FILE):
                try:
                    with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(0, 2)
                        file_len = f.tell()
                        if offset < file_len:
                            f.seek(offset)
                            logs = f.read()
                        new_offset = file_len
                except Exception as e:
                    logs = f"Error reading logs: {e}"
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"logs": logs, "offset": new_offset}).encode())
            return

        elif self.path.startswith("/api/finished"):
            finished_dir = FINISHED_DIR
            files = []
            if os.path.exists(finished_dir):
                for f in sorted(os.listdir(finished_dir), key=lambda x: os.path.getmtime(os.path.join(finished_dir, x)) if os.path.exists(os.path.join(finished_dir, x)) else 0, reverse=True):
                    if f.endswith(".mp4") or f.endswith(".txt"):
                        path = os.path.join(finished_dir, f)
                        size = os.path.getsize(path)
                        files.append({"name": f, "sizeBytes": size, "type": "video" if f.endswith(".mp4") else "metadata"})
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"files": files}).encode())
            return

        elif self.path == "/lion_logo.png":
            filepath = os.path.join(BASE_DIR, "lion_logo.png")
            if os.path.exists(filepath):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(os.path.getsize(filepath)))
                self.end_headers()
                try:
                    with open(filepath, "rb") as f:
                        self.wfile.write(f.read())
                except:
                    pass
                return
            else:
                self.send_error(404, "Logo file not found")
                return

        elif self.path.startswith("/finished/"):
            # Serve files from finished directory directly
            filename = self.path.replace("/finished/", "")
            filepath = os.path.join(FINISHED_DIR, filename)
            if os.path.exists(filepath):
                self.send_response(200)
                if filename.endswith(".mp4"):
                    self.send_header("Content-Type", "video/mp4")
                else:
                    self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(os.path.getsize(filepath)))
                self.end_headers()
                try:
                    with open(filepath, "rb") as f:
                        self.wfile.write(f.read())
                except:
                    pass
                return
            else:
                self.send_error(404, "File not found")
                return

        # Default static file routing
        if self.path == "/" or self.path == "":
            self.path = "/gui/index.html"
        elif not self.path.startswith("/gui/"):
            self.path = f"/gui{self.path}"

        # Clean double slashes
        self.path = self.path.replace("//", "/")
        
        # Call super method to serve standard files
        return super().do_GET()

    def do_POST(self):
        global RUNNING_PROCESS
        
        content_length = int(self.headers['Content-Length'] or 0)
        post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
        
        if self.path.startswith("/api/config"):
            try:
                cfg = json.loads(post_data)
                success = save_config(cfg)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode())
            return

        elif self.path.startswith("/api/delete-file"):
            try:
                params = json.loads(post_data)
                filename = params.get("filename")
                if filename:
                    filename = os.path.basename(filename)
                    filepath = os.path.join(FINISHED_DIR, filename)
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception as e:
                            print(f"Error removing {filepath}: {e}")
                        # Also delete corresponding metadata file if it exists
                        if filename.endswith(".mp4"):
                            meta_name = filename.replace("lion_dog_", "lion_metadata_dog_").replace("lion_cat_", "lion_metadata_cat_").replace("lion_mix_", "lion_metadata_mix_").replace(".mp4", ".txt")
                            meta_path = os.path.join(FINISHED_DIR, meta_name)
                            if os.path.exists(meta_path):
                                try: os.remove(meta_path)
                                except: pass
                        elif filename.endswith(".txt"):
                            vid_name = filename.replace("lion_metadata_dog_", "lion_dog_").replace("lion_metadata_cat_", "lion_cat_").replace("lion_metadata_mix_", "lion_mix_").replace(".txt", ".mp4")
                            vid_path = os.path.join(FINISHED_DIR, vid_name)
                            if os.path.exists(vid_path):
                                try: os.remove(vid_path)
                                except: pass
                                
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": True}).encode())
                        return
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "Invalid filename"}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/clear-finished"):
            try:
                finished_dir = FINISHED_DIR
                if os.path.exists(finished_dir):
                    for f in os.listdir(finished_dir):
                        path = os.path.join(finished_dir, f)
                        if os.path.isfile(path) and (f.endswith(".mp4") or f.endswith(".txt")):
                            try: os.remove(path)
                            except: pass
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/clear-raw"):
            try:
                raw_dir = RAW_DIR
                if os.path.exists(raw_dir):
                    for f in os.listdir(raw_dir):
                        path = os.path.join(raw_dir, f)
                        if os.path.isfile(path) and (f.endswith(".mp4") or f.endswith(".part")):
                            try: os.remove(path)
                            except: pass
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/start"):
            is_running = RUNNING_PROCESS is not None and RUNNING_PROCESS.poll() is None
            if is_running:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "Already running"}).encode())
                return
            
            # Clear log file
            try:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.write("=== Launching LionReel Automation Script ===\n")
            except:
                pass

            # Spawn Python script
            try:
                python_exe = os.path.join(".venv", "Scripts", "python.exe")
                if not os.path.exists(python_exe):
                    python_exe = "python"
                
                # Run script in background and redirect output to log file
                log_fd = open(LOG_FILE, "a", encoding="utf-8", errors="ignore")
                RUNNING_PROCESS = subprocess.Popen(
                    [python_exe, "-u", "lion_automate.py"],
                    stdout=log_fd,
                    stderr=log_fd,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/stop"):
            if RUNNING_PROCESS is not None:
                try:
                    if os.name == 'nt':
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(RUNNING_PROCESS.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        RUNNING_PROCESS.terminate()
                    RUNNING_PROCESS = None
                    # Append message to log
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write("\n=== Generation Stopped by User ===\n")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True}).encode())
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": "Not running"}).encode())
            return

        elif self.path.startswith("/api/create-shortcut"):
            try:
                params = json.loads(post_data)
                hotkey = params.get("hotkey", "CTRL+ALT+L").upper()
                
                # 1. Determine pythonw.exe path to run silently
                workspace_dir = os.path.dirname(os.path.abspath(__file__))
                current_exe = sys.executable
                if current_exe.endswith("python.exe"):
                    pythonw_exe = current_exe.replace("python.exe", "pythonw.exe")
                elif current_exe.endswith("python"):
                    pythonw_exe = current_exe + "w"
                else:
                    pythonw_exe = "pythonw.exe"
                
                # 2. Ensure ICO file exists
                ico_exists = ensure_icon()
                ico_path = os.path.join(workspace_dir, "lion_logo.ico") if ico_exists else ""
                
                # 3. Create Windows Shortcut using PowerShell targeting pythonw.exe
                ps_command = f"""
                $DesktopPath = [Environment]::GetFolderPath('Desktop')
                $ShortcutPath = Join-Path $DesktopPath "LionReel Studio.lnk"
                $WScriptShell = New-Object -ComObject WScript.Shell
                $Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
                $Shortcut.TargetPath = "{pythonw_exe}"
                $Shortcut.Arguments = "web_server.py"
                $Shortcut.WorkingDirectory = "{workspace_dir}"
                """
                if ico_exists:
                    # Windows paths in PowerShell need backslash escaping or quote wrapping
                    ico_path_esc = ico_path.replace('"', '`"')
                    ps_command += f'\n$Shortcut.IconLocation = "{ico_path_esc}"'
                
                if hotkey:
                    ps_command += f'\n$Shortcut.Hotkey = "{hotkey}"'
                
                ps_command += '\n$Shortcut.Description = "Launch LionReel Dashboard Server"\n$Shortcut.Save()'
                
                res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_command], capture_output=True, text=True)
                
                if res.returncode == 0:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "message": f"Shortcut created on Desktop (Hotkey: {hotkey})"}).encode())
                else:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": res.stderr}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    # Ensure raw and finished folders exist
    os.makedirs(FINISHED_DIR, exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)
    
    server = ThreadedTCPServer(("", PORT), DashboardHandler)
    print(f"============================================================")
    print(f"  LionReel GUI Dashboard Server launched successfully! 🦁")
    print(f"  --> Open: http://localhost:{PORT} in your web browser")
    print(f"============================================================")
    
    def open_browser_delayed(port):
        import time
        import webbrowser
        time.sleep(0.5)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=open_browser_delayed, args=(PORT,), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()
        server.server_close()
