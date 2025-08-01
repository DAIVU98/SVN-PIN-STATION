import numpy as np
from loader import usr_cfg

batt_matrix = np.zeros((2,5,2), dtype=np.int16)

matrix = usr_cfg["matrix"]
start = matrix["start"]
offset = matrix["start_offset"]
batt_size = matrix["batt_size"]
batt_spacing = matrix["batt_spacing"]

for i in range (2):
    for j in range (5):
        x = start.x+offset.x+(batt_size.x/2+batt_spacing.x)*i
        y = start.y + offset.y + (batt_size.y / 2 + batt_spacing.y) * j
        batt_matrix[i][j]=[x,y]
np.save('../matrix/batt_matrix.npy', batt_matrix)
loaded_matrix = np.load('../matrix/batt_matrix.npy')

print(loaded_matrix.dtype)
print(loaded_matrix)
