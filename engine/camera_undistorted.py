import cv2
import numpy as np

calib = np.load("camera_calib_480.npz")
K, D = calib["K"], calib["D"]

cap = cv2.VideoCapture(0,cv2.CAP_DSHOW)

ret, frame = cap.read()
if not ret:
    raise RuntimeError("Failed to capture frame from camera.")

h, w = frame.shape[:2]

new_K, roi = cv2.getOptimalNewCameraMatrix(K, D, (w, h), 1, (w, h))
map1, map2 = cv2.initUndistortRectifyMap(K, D, None, new_K, (w, h), cv2.CV_16SC2)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    undistorted = cv2.remap(frame, map1, map2, interpolation=cv2.INTER_LINEAR)

    cv2.imshow("Original", frame)
    cv2.imshow("Undistorted", undistorted)

    if cv2.waitKey(1) & 0xFF == 27:  # ESC key
        break

cap.release()
cv2.destroyAllWindows()
