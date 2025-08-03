import os
import subprocess

project_root = os.path.dirname(os.path.abspath(__file__))
pyinstaller = os.path.join(project_root, '.venv', 'Scripts', 'pyinstaller.exe')

cmd = [
    pyinstaller,
    "main.py",
    "--noconfirm",
    "--console",
    "--onedir",
    "--clean",
    "--name", "FullBatteryApp",
    "--add-data", "camera;camera",
    "--add-data", "config;config",
    "--add-data", "jkrc;jkrc",
    "--add-data", "assets;assets",
    "--add-data", "matrix;matrix",
    "--add-data", "README.md;./",
    "--splash", "./resource/splash.png",
    "--icon", "./resource/svn.ico"
]

print(" ".join(f'"{arg}"' if ' ' in arg else arg for arg in cmd))
subprocess.call(cmd)
