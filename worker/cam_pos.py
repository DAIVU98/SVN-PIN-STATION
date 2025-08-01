import numpy as np
import time
import cv2
import multiprocessing as mp
from camera.detection import BatteryLocator

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

import engine.loader as ldr

DEBUG=ldr.usr_cfg["main"]["debug"]

class CamPosition(QThread):
    change_pixmap_signal = pyqtSignal(QImage)  # live preview
    detection_signal = pyqtSignal(object)  # np.ndarray([x,y,z])
    
    def __init__(self, is_Opened: mp.Event, parent=None):
        super().__init__(parent)
        self.isRun = True
        self.restart_thread = False
        self.bl = None
        self.is_Opened = is_Opened
        self._buffer = []  # store raw xyz per frame

    # ------------------------------------------------------------------
    def run(self, FRAMES_TO_AVG = ldr.usr_cfg["main"]["frame_to_avg"]):
        self.bl = BatteryLocator()
        if self.bl.stop:
            self.isRun = False
        print("CamPos Run:", self.isRun)
        # ------------------------------------------------------------------
        while self.isRun and self.bl.cap.isOpened():
            self.is_Opened.set() 
            frame = self.bl.update()
            if frame is not None:
                # 1) Emit live preview
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                self.change_pixmap_signal.emit(
                    QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
                )

                # 2) Collect battery coordinates
                coord = self.bl.get_nearest_battery()
                if coord is not None:
                    self._buffer.append(coord)
                # Once enough frames collected → compute median & emit
                if len(self._buffer) >= FRAMES_TO_AVG:
                    buf = np.array(self._buffer[int(FRAMES_TO_AVG * 0.5):])  # shape (N,4)
                    arr = np.median(buf, axis=0)  # shape (4,)
                    arr[3] = coord[3]  # OK now

                    if DEBUG:
                        if DEBUG: print("Battery Coordinates:", arr)
                    self.detection_signal.emit(arr)
                    self._buffer.clear()
            cv2.waitKey(1)
        self.clear_status()
        if DEBUG: print("camPos released")
        self.restart_thread = True

    # ------------------------------------------------------------------
    def clear_status(self):
        self.is_Opened.clear()
        if self.bl.cap.isOpened():
            self.bl.cap.release()

    def stop(self):
        self.isRun = False