import time

import cv2
import cv2.aruco as aruco
import numpy as np
import torch
from ultralytics import YOLO

import engine.loader as ldr

DEBUG = ldr.usr_cfg["main"]["debug"]
if DEBUG: print("Cuda available: ",torch.cuda.is_available())


def tag_world_corners(tag_id: int, cfg=ldr.usr_cfg["cam_pos"]) -> np.ndarray:
    if tag_id == 0:
        base = (0, 0)
    elif tag_id == 1:
        base = (cfg["tray_length"], 0)
    elif tag_id == 2:
        base = (cfg["tray_length"], cfg["tray_width"])
    elif tag_id == 3:
        base = (0, cfg["tray_width"])
    else:
        raise ValueError("tag_id must be 0-3")

    x0, y0 = base
    s = cfg["tag_size"]
    return np.array([[x0, y0 + s],  # TL
                     [x0 + s, y0 + s],  # TR
                     [x0 + s, y0],  # BR
                     [x0, y0]],  # BL
                    dtype=np.float32)


class BatteryLocator:
    def __init__(self, cfg=ldr.usr_cfg["cam_pos"]):
        cfg = ldr.usr_cfg["cam_pos"]
        self.stop = False
        # fix fisheye
        calib = np.load(ldr.camera_calib / cfg["camera_calib"])
        K, D = calib["K"], calib["D"]

        self.cap = cv2.VideoCapture(cfg["idx"], cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            # raise RuntimeError("Cannot open camera", cfg["idx"])
            self.stop = True
            print("Cannot open camera " + str(cfg["idx"]))
            return 

        ok, f0 = self.cap.read()
        if not ok:
            # raise RuntimeError("Camera read failed at start-up")
            self.stop = True
            print("Camera read failed at start-up")
            return 
        h, w = f0.shape[:2]

        newK, _ = cv2.getOptimalNewCameraMatrix(K, D, (w, h), 0)
        self.map1, self.map2 = cv2.initUndistortRectifyMap(
            K, D, None, newK, (w, h), cv2.CV_16SC2)
        self.h_img, self.w_img = h, w

        # detect aruco
        self.aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        aruco_params = aruco.DetectorParameters()
        aruco_params.cornerRefinementMethod = aruco.CORNER_REFINE_SUBPIX
        aruco_params.cornerRefinementWinSize = 5
        aruco_params.cornerRefinementMinAccuracy = 0.03
        self.aruco_detector = aruco.ArucoDetector(self.aruco_dict, aruco_params)

        # ---- YOLO model ----------------------------------------
        self.model = YOLO(ldr.detect_model / cfg["detect_model"])
        self.H = None
        self.last_detections = []  # list of (X,Y,theta)
        self._last_frame = None
        self.prev_frame_time = 0
        self.new_frame_time = 0

    def _compute_homography(self, frame, cfg=ldr.usr_cfg["cam_pos"]):
        img_pts, obj_pts = [], []
        corners, ids, _ = self.aruco_detector.detectMarkers(frame)
        if ids is not None:
            for tid, c4 in zip(ids.flatten(), corners):
                if tid in cfg["tag_ids"]:
                    pts4 = c4[0].astype(np.float32)
                    img_pts.extend(pts4)
                    obj_pts.extend(tag_world_corners(tid))
                    # draw tag border
                    cv2.polylines(frame, [pts4.astype(int)],
                                  True, (0, 255, 0), 2)
        if len(img_pts) >= 4:
            self.H, _ = cv2.findHomography(np.array(img_pts),
                                           np.array(obj_pts),
                                           cv2.RANSAC, 2.0)

    def _angle_table(self, rect):
        if self.H is None:
            return 0.0
        box = cv2.boxPoints(rect).astype(np.float32)
        edges = [np.linalg.norm(box[i] - box[(i + 1) % 4]) for i in range(4)]
        i0 = int(np.argmax(edges))
        i1 = (i0 + 1) % 4
        p_img = np.array([[box[i0], box[i1]]], np.float32)
        p_mm = cv2.perspectiveTransform(p_img, self.H)[0]
        dx, dy = p_mm[1] - p_mm[0]
        return (np.degrees(np.arctan2(dy, dx)) + 360) % 180

    def update(self, cfg=ldr.usr_cfg["cam_pos"]):
        if self.cap.isOpened():
            ok, raw = self.cap.read()
            self.new_frame_time = time.time()
            if (self.new_frame_time - self.prev_frame_time) > 0:
                fps = 1 / (self.new_frame_time - self.prev_frame_time)
            else:
                fps = 0.0

            if not ok:
                self.last_detections = []
                return None

            frame = cv2.remap(raw, self.map1, self.map2, cv2.INTER_LINEAR)
            self._last_frame = frame.copy()  # ensure something to show
            self._compute_homography(frame)

            det = []
            result = self.model.predict(frame, conf=cfg["conf"], verbose=False)[0]

            # -------- choose masks if present, else boxes -----------
            if result.masks is not None:
                polys = [p.astype(np.int32) for p in result.masks.xy]
                for idx, cnt in enumerate(polys):
                    if (cnt[:, 0] < cfg["guard_px"]).any() or \
                            (cnt[:, 0] > self.w_img - cfg["guard_px"]).any() or \
                            (cnt[:, 1] < cfg["guard_px"]).any() or \
                            (cnt[:, 1] > self.h_img - cfg["guard_px"]).any():
                        continue
                    mask = np.zeros((self.h_img, self.w_img), np.uint8)
                    cv2.fillPoly(mask, [cnt], 255)
                    mask = cv2.morphologyEx(
                        mask, cv2.MORPH_CLOSE,
                        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
                    cnt2, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                               cv2.CHAIN_APPROX_SIMPLE)
                    rect = cv2.minAreaRect(cnt2[0])
                    (xc, yc), (wr, hr), _ = rect
                    if self.H is None: continue
                    p_img = np.array([[[xc, yc]]], np.float32)
                    X_mm, Y_mm = cv2.perspectiveTransform(p_img, self.H)[0, 0]
                    theta = self._angle_table(rect)
                    label = result.names[int(result.boxes.cls[idx])]
                    det.append((X_mm, Y_mm, theta,int(result.boxes.cls[idx])))
                    # fps


                    # draw
                    if cfg["show_masks"]:
                        overlay = frame.copy()
                        overlay[mask.astype(bool)] = (0, 0, 200)
                        cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)
                        cv2.drawContours(frame, [cv2.boxPoints(rect).astype(int)],
                                         -1, (0, 100, 255), 1)
                    cv2.circle(frame, (int(xc), int(yc)), 2, (0, 255, 255), -1)
                    cv2.putText(frame, label, (int(xc) -20, int(yc) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (100, 255, 100), 1,cv2.LINE_AA)
                    cv2.putText(frame, f"X:{X_mm:.0f}",
                                (int(xc) -20, int(yc)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 0), 1,cv2.LINE_AA)
                    cv2.putText(frame, f"Y:{Y_mm:.0f}",
                                (int(xc) -20, int(yc)+10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 0), 1,cv2.LINE_AA)
                    cv2.putText(frame, f"{theta:.0f}'",
                                (int(xc) -20, int(yc) + 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1,cv2.LINE_AA)

        else:  # ---------- fallback to boxes --------------------
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                if self.H is None: continue
                p_img = np.array([[[cx, cy]]], np.float32)
                X_mm, Y_mm = cv2.perspectiveTransform(p_img, self.H)[0, 0]
                theta = 0.0
                cv2.rectangle(frame, (int(x1), int(y1)),
                              (int(x2), int(y2)), (0, 100, 255), 2)
                cv2.circle(frame, (int(cx), int(cy)), 3, (0, 255, 255), -1)
                cv2.putText(frame, f"{X_mm:.1f},{Y_mm:.1f}",
                            (int(cx) + 6, int(cy)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                det.append((X_mm, Y_mm, theta))

        self.last_detections = det
        self._last_frame = frame  # annotated copy
        cv2.putText(frame, f"FPS: {int(fps + 0)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2,
                    cv2.LINE_AA)
        self.prev_frame_time = self.new_frame_time
        return frame

    def get_nearest_battery(self, ref=(0, 0)):
        if not self.last_detections:
            return None
        closest_detection = min(self.last_detections,
                                key=lambda t_val: (t_val[0] - ref[0]) ** 2 + (t_val[1] - ref[1]) ** 2)

        # Convert all elements in the returned detection to standard Python floats
        return tuple(int(val) for val in closest_detection)

    def show(self, win="Battery Cam"):
        if self._last_frame is not None:
            cv2.imshow(win, self._last_frame)
            cv2.waitKey(1)

    def release(self):
        self.cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    bl = BatteryLocator()
    print("▶  ESC to quit")
    try:
        while True:
            bl.update()
            bl.show()
            if cv2.waitKey(1) & 0xFF == 27:  # ESC
                break
    finally:
        bl.release()
