import sys
if getattr(sys, 'frozen', False): import pyi_splash
def text(str):
    if getattr(sys, 'frozen', False):
        pyi_splash.update_text(str)
def close():
    if getattr(sys, 'frozen', False):
         pyi_splash.close()
