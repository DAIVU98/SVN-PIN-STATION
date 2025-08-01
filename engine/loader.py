from pathlib import Path
import os, sys
import re
import numpy as np
from ruamel.yaml import YAML, CommentedMap
from PyQt5.QtWidgets import QApplication, QMessageBox, QTextEdit, QPushButton
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtCore import QUrl
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineSettings
import webbrowser

from io import StringIO
from copy import deepcopy

# ------------------------------------------------------------------
#  Markdown loader
# ------------------------------------------------------------------    
class ExternalLinkPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if _type == QWebEnginePage.NavigationTypeLinkClicked:
            webbrowser.open(url.toString())  # External browser
            return False
        return super().acceptNavigationRequest(url, _type, isMainFrame)

def load_markdown(readMe):
    with open(markdown_path, "r", encoding="utf-8") as f:
        md_content = f.read()
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Markdown Viewer</title>
        <script src="https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js"></script>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 2em;
                background-color: #fefefe;
            }}
            #content img {{
                max-width: 100%;
            }}
            textarea {{
                display: none;
            }}
        </style>
    </head>
    <body>
        <textarea id="md">{md_content}</textarea>
        <div id="content">Loading...</div>
        <script>
            const rawMarkdown = document.getElementById("md").value;
            document.getElementById("content").innerHTML = marked.parse(rawMarkdown);
        </script>
    </body>
    </html>
    """

    with open(f"{markdown_path.stem}.html", "w", encoding="utf-8") as f:
        f.write(html)

    # base_path = QUrl.fromLocalFile(str(PROJECT_ROOT) + "/")
    readMe.settings().setAttribute(QWebEngineSettings.PluginsEnabled, True)
    readMe.settings().setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
    readMe.page().setAudioMuted(False)
    readMe.setPage(ExternalLinkPage(readMe))
    readMe.setUrl(QUrl.fromLocalFile(os.path.abspath(f"{markdown_path.stem}.html")))
    # readMe.setUrl(QUrl("https://html5test.com/"))
    
# ------------------------------------------------------------------
#  Ruamel format, delete blank lines
# ------------------------------------------------------------------
def yaml_remove_blanks(data) -> str:
    stream = StringIO()
    yaml.dump(data, stream)
    lines = stream.getvalue().splitlines()
    i = 0
    while i < len(lines) - 1:
        if '#' in lines[i] and lines[i + 1] == '':
            lines.pop(i + 1)
        else:
            i += 1
    return '\n'.join(lines)

# ------------------------------------------------------------------
#  Global Loader
# ------------------------------------------------------------------        
def show_error(title, msg, lib_import=False):
    app = None
    if QApplication.instance() is None:
        # Create a temporary QApplication
        app = QApplication(sys.argv)

    # Show modal error dialog
    if not lib_import:
        QMessageBox.critical(None, title, msg, QMessageBox.Ok)
    else:
        box = QMessageBox(None)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(title)
        box.setText(msg)

        # Create custom button
        btn_download = QPushButton("Download")
        box.addButton(btn_download, QMessageBox.AcceptRole)
        btn_retry = QPushButton("Retry")
        box.addButton(btn_retry, QMessageBox.RejectRole)
        btn_exit = QPushButton("Exit")
        box.addButton(btn_exit, QMessageBox.RejectRole)

        # Show message box
        result = box.exec_()
        clicked = box.clickedButton()
        # Handle button clicks
        if clicked == btn_download:
            QDesktopServices.openUrl(QUrl("https://aka.ms/highdpimfc2013x64enu"))
        elif clicked == btn_exit:
            sys.exit(1)
        

    # If we created a temporary app, we manually close it
    if app:
        app.quit()  # gracefully shuts it down
        
def reload_cfg(parent=None):
    global usr_cfg, cfg, camera_calib_files, detect_model_files, batt_matrix_files
    camera_calib_files = [f for f in os.listdir(camera_calib) if os.path.isfile(os.path.join(camera_calib, f))]
    detect_model_files = [f for f in os.listdir(detect_model) if os.path.isfile(os.path.join(detect_model, f))]
    batt_matrix_files = [f for f in os.listdir(batt_matrix_path) if os.path.isfile(os.path.join(batt_matrix_path, f))]

    usr_cfg = None
    cfg = None
    error_shown = False

    def try_load(path):
        try:
            data = yaml.load(path)
            stream = StringIO()
            yaml.dump(data, stream)
            if stream.getvalue().strip() == "":
                raise ValueError("YAML is empty")
            return data
        except Exception:
            return None

    fallback_chain = [
        (usr_cfg_path, "User Config Error", "Your user config YAML file has not loaded properly, overriding with default config YAML file"),
        (cfg_path, "Default Config Error", "Your default config YAML file has not loaded properly, overriding with factory config YAML file"),
        (factory_cfg_path, "Factory Config Error", "You messed with something you shouldn't have, the system is cooked, congrats :). Contact Nguyen Phuoc Khang or Tran Cao Cap to resolve this problem.")
    ]

    for idx, (path, title, msg) in enumerate(fallback_chain):
        data = try_load(path)
        if data:
            if usr_cfg is None:
                usr_cfg = deepcopy(data)
                if path != usr_cfg_path:
                    with open(usr_cfg_path, 'w', encoding='utf-8') as f:
                        f.write(yaml_remove_blanks(data))
            if cfg is None and idx > 0:
                cfg = data
                if path != cfg_path:
                    with open(cfg_path, 'w', encoding='utf-8') as f:
                        f.write(yaml_remove_blanks(data))

            if usr_cfg and cfg:
                break  # ✅ Both resolved
        else:
            show_error(title, msg)

    # Final fail-safe
    if usr_cfg is None or cfg is None:
        raise RuntimeError("The system is cooked")
        sys.exit(1)
    
yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 0  # disables auto line-wrapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
factory_cfg_path = PROJECT_ROOT / "config" / "factoryConfig.yaml"
cfg_path = PROJECT_ROOT / "config" / "config.yaml"
usr_cfg_path = PROJECT_ROOT / "config" / "userConfig.yaml"
folder_cam = PROJECT_ROOT / "ImagesCaptured"
markdown_path = PROJECT_ROOT / "README.md"

if not folder_cam.exists():
    os.makedirs(folder_cam)

for path in [factory_cfg_path, cfg_path, usr_cfg_path, markdown_path]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")


detect_model = PROJECT_ROOT / "camera" / "model"
camera_calib = PROJECT_ROOT / "camera" / "calib"
batt_matrix_path = PROJECT_ROOT / "matrix"

reload_cfg()

batt_matrix = batt_matrix_path / usr_cfg["batt_matrix"]

for path in [camera_calib, detect_model, batt_matrix]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")

batt_matrix = np.load(batt_matrix, allow_pickle=True)

# ------------------------------------------------------------------
#  Check if calib file name is valid
# ------------------------------------------------------------------
def is_valid_filename(name: str, parent=None, directory=".") -> bool:
    # Disallowed characters (Windows standard)
    invalid_chars = r'[\\/:\*\?"<>\|]'
    try:
        if not name.strip():
            raise ValueError("File name cannot be empty or whitespace only")
        if re.search(invalid_chars, name):
            raise ValueError(f"File name contains invalid characters: {name}")
        if os.path.exists(os.path.join(directory, name+".npz")):
            raise ValueError(f"File already exists: {name}")
        return True
    except Exception as e:
        QMessageBox.critical(parent, "Invalid File Name:", str(e))
        return False

# ------------------------------------------------------------------
#  Ruamel check if file is valid
# ------------------------------------------------------------------
def is_number(x):
    return isinstance(x, (int, float))

def is_list_of_6_numbers(x):
    return isinstance(x, list) and len(x) == 6 and all(is_number(i) for i in x)

def file_exists(path_base, name):
    return (path_base / name.strip()).resolve().exists()

value_constraints = {
    # IP address
    "ip": lambda v: isinstance(v, str) and re.fullmatch(
        r'^(25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)){3}$', v),

    # Int or float
    "tool": lambda v: is_number(v) and v >= 0,
    "speed": lambda v: is_number(v) and v >= 0,
    "speed_rad": lambda v: is_number(v) and v >= 0,
    "accel": lambda v: is_number(v) and v >= 0,
    "accel_rad": lambda v: is_number(v) and v >= 0,
    "short_edge": lambda v: is_number(v) and v >= 0,
    "conf": lambda v: is_number(v) and 0 <= v <= 1,
    "tag_size": lambda v: is_number(v) and v >= 0,
    "tray_width": lambda v: is_number(v) and v >= 0,
    "tray_length": lambda v: is_number(v) and v >= 0,

    # Bool (0/1 or bool)
    "show_masks": lambda v: isinstance(v, (bool, int)),
    "debug": lambda v: isinstance(v, (bool, int)),

    # Int only
    "guard_px": lambda v: isinstance(v, int) and v >= 0,
    "frame_to_avg": lambda v: isinstance(v, int) and v >= 0,

    # List of ints
    "tag_ids": lambda v: isinstance(v, list) and all(isinstance(i, int) and i >= 0 for i in v),

    # Lists of 6 numbers
    "arm_default_pos": is_list_of_6_numbers,
    "tcp_default_pos": is_list_of_6_numbers,
    "tcp_end_pos": is_list_of_6_numbers,
    "tcp_transfer_pos": is_list_of_6_numbers,
    "tcp_offset": is_list_of_6_numbers,
    "user_coord": is_list_of_6_numbers,

    # File checks
    "camera_calib": lambda v: file_exists(camera_calib, v),
    "detect_model": lambda v: file_exists(detect_model, v),
    "batt_matrix": lambda v: file_exists(PROJECT_ROOT / "matrix", v),
}

def validate_yaml(data: str, reference_data=None, parent=None) -> bool:
    def apply_constraints(path, key, val):
        key = str(key)
        rule = value_constraints.get(key)

        try:
            # Check for empty/null values
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"{path} → ❌ Missing or empty value")
                return

            # Check for disallowed characters (example: ! @ # $ % ^ & *)
            if isinstance(val, str) and re.search(r'[!@#$%^&*]', val):
                errors.append(f"{path} → ❌ Invalid characters in string: {val}")
                return

            if rule and not rule(val):
                if key in {"camera_calib", "detect_model", "batt_matrix"}:
                    errors.append(f"{path} → ❌ File does not exist: {val}")
                elif key in {"arm_default_pos", "tcp_default_pos", "tcp_end_pos",
                            "tcp_transfer_pos", "tcp_offset", "user_coord"}:
                    if not isinstance(val, list):
                        errors.append(f"{path} → ❌ Expected a list of 6 numbers, got: {type(val).__name__}")
                    else:
                        errors.append(f"{path} → ❌ Expected 6 numeric elements, got: {val}")
                elif key == "tag_ids":
                    if not isinstance(val, list):
                        errors.append(f"{path} → ❌ Expected a list of ints, got: {type(val).__name__}")
                    else:
                        errors.append(f"{path} → ❌ List must contain only non-negative ints, got: {val}")
                elif key in {"show_masks", "debug"}:
                    errors.append(f"{path} → ❌ Expected bool (or 0/1), got: {val} ({type(val).__name__})")
                elif key in {"guard_px", "frame_to_avg"}:
                    errors.append(f"{path} → ❌ Expected non-negative int, got: {val} ({type(val).__name__})")
                elif key == "conf":
                    errors.append(f"{path} → ❌ Expected number between 0 and 1, got: {val}")
                else:
                    errors.append(f"{path} → ❌ Invalid value: {val} ({type(val).__name__})")
        except Exception as e:
            errors.append(f"{path} → ❌ Rule error: {e}")
            
    def walk(val, ref, path=""):
        if isinstance(ref, dict) and isinstance(val, dict):
            ref_keys = set(ref)
            val_keys = set(val)

            for k in val_keys - ref_keys:
                errors.append(f"{path or '.'} → ❌ Unexpected key: {k}")
            for k in ref_keys - val_keys:
                errors.append(f"{path or '.'} → ❌ Missing key: {k}")
            for k in ref_keys & val_keys:
                subpath = f"{path}.{k}" if path else str(k)
                apply_constraints(subpath, k, val[k])
                walk(val[k], ref[k], subpath)

        elif isinstance(ref, list) and isinstance(val, list):
            for i, (v_item, r_item) in enumerate(zip(val, ref)):
                walk(v_item, r_item, f"{path}[{i}]")

    def walk_constraints_only(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                subpath = f"{path}.{k}" if path else str(k)
                apply_constraints(subpath, k, v)
                walk_constraints_only(v, subpath)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk_constraints_only(item, f"{path}[{i}]")

    try:
        parsed = yaml.load(StringIO(data))
        if parsed is None or not isinstance(parsed, CommentedMap):
            raise ValueError("Invalid or empty YAML")

        errors = []
        if reference_data:
            walk(parsed, reference_data)
        else:
            walk_constraints_only(parsed)

        if errors:
            raise ValueError("Validation failed:\n" + "\n".join(errors))

        return True

    except Exception as e:
        print("[YAML Validation Error]", str(e))
        if parent:
            QMessageBox.critical(parent, "YAML Format Error", str(e))
        return False
