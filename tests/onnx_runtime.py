#   Copyright (c) 2019 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import onnx
import onnxruntime
import numpy as np
from onnxruntime.backend import prepare
from onnx import shape_inference
import pickle
import time

sess = onnxruntime.InferenceSession("tests/nms_test.onnx")
with open("tests/inputs_test.pkl", "rb") as f:
    np_images = pickle.load(f)
f.close()
result = sess.run([], np_images)
value_len = 0
with open("tests/outputs_test.pkl", "wb") as f:
    pickle.dump(result, f)
f.close()
