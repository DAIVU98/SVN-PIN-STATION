import cv2
import multiprocessing as mp
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

import engine.loader as ldr

DEBUG=ldr.usr_cfg["main"]["debug"]

class CamShot(QThread):
    change_pixmap_signal = pyqtSignal(QImage)
    flagShot = pyqtSignal(str)

    def __init__(self, capture: mp.Event, is_Opened: mp.Event, parent=None):
        super(CamShot, self).__init__(parent)
        self.isRun = True
        self.restart_thread = False
        self.frame_shot = None
        self.cap = None
        self.capture = capture
        self.is_Opened = is_Opened
        self.done_shot = False

    def run(self):
        INDEX_CAM_2 = ldr.usr_cfg["cam_shot"]["idx"]
        if DEBUG: print(f"Cam Shot connecting to {INDEX_CAM_2}")
        self.cap = cv2.VideoCapture(INDEX_CAM_2, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            # raise RuntimeError("Cannot open camera", cfg["idx"])
            print("Cannot open camera " + str(INDEX_CAM_2))
            self.isRun = False 
        
        while self.isRun and self.cap.isOpened():
            self.is_Opened.set()
            # print(f"before saving{self.capture.value}")
            if self.capture.is_set():
                # Save frame here
                if DEBUG: print("Saving frame")
                self.flagShot.emit("shot")
                self.capture.clear()
                if DEBUG: print(self.capture.is_set())
                # Capture done
                pass

            if self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    self.frame_shot = frame
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_frame.shape
                    bytes_per_line = ch * w
                    qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    if self.isRun:
                        self.change_pixmap_signal.emit(qt_image)
                    cv2.waitKey(1)
        self.clear_status()
        if DEBUG: print("Cam Shot released")
        self.restart_thread = True
        
    def getFrame(self):
        return self.frame_shot

    def clear_status(self):
        self.is_Opened.clear()
        if self.cap.isOpened():
            self.cap.release()
            
    def stop(self):
        self.isRun = False