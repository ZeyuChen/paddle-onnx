#  Copyright (c) 2018 PaddlePaddle Authors. All Rights Reserved.
#
#Licensed under the Apache License, Version 2.0 (the "License");
#you may not use this file except in compliance with the License.
#You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#Unless required by applicable law or agreed to in writing, software
#distributed under the License is distributed on an "AS IS" BASIS,
#WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#See the License for the specific language governing permissions and
#limitations under the License.

from __future__ import print_function
import unittest
import numpy as np
import copy
from op_test import OpTest
import paddle.fluid.core as core


def iou(box_a, box_b, norm):
    """Apply intersection-over-union overlap between box_a and box_b
    """
    xmin_a = min(box_a[0], box_a[2])
    ymin_a = min(box_a[1], box_a[3])
    xmax_a = max(box_a[0], box_a[2])
    ymax_a = max(box_a[1], box_a[3])

    xmin_b = min(box_b[0], box_b[2])
    ymin_b = min(box_b[1], box_b[3])
    xmax_b = max(box_b[0], box_b[2])
    ymax_b = max(box_b[1], box_b[3])

    area_a = (ymax_a - ymin_a + (norm == False)) * (xmax_a - xmin_a +
                                                    (norm == False))
    area_b = (ymax_b - ymin_b + (norm == False)) * (xmax_b - xmin_b +
                                                    (norm == False))
    if area_a <= 0 and area_b <= 0:
        return 0.0

    xa = max(xmin_a, xmin_b)
    ya = max(ymin_a, ymin_b)
    xb = min(xmax_a, xmax_b)
    yb = min(ymax_a, ymax_b)

    inter_area = max(xb - xa + (norm == False),
                     0.0) * max(yb - ya + (norm == False), 0.0)

    iou_ratio = inter_area / (area_a + area_b - inter_area)

    return iou_ratio


def nms(boxes,
        scores,
        score_threshold,
        nms_threshold,
        top_k=200,
        normalized=True,
        eta=1.0):
    """Apply non-maximum suppression at test time to avoid detecting too many
    overlapping bounding boxes for a given object.
    Args:
        boxes: (tensor) The location preds for the img, Shape: [num_priors,4].
        scores: (tensor) The class predscores for the img, Shape:[num_priors].
        score_threshold: (float) The confidence thresh for filtering low
            confidence boxes.
        nms_threshold: (float) The overlap thresh for suppressing unnecessary
            boxes.
        top_k: (int) The maximum number of box preds to consider.
        eta: (float) The parameter for adaptive NMS.
    Return:
        The indices of the kept boxes with respect to num_priors.
    """
    all_scores = copy.deepcopy(scores)
    all_scores = all_scores.flatten()
    selected_indices = np.argwhere(all_scores > score_threshold)
    selected_indices = selected_indices.flatten()
    all_scores = all_scores[selected_indices]

    sorted_indices = np.argsort(-all_scores, axis=0, kind='mergesort')
    sorted_scores = all_scores[sorted_indices]
    sorted_indices = selected_indices[sorted_indices]
    if top_k > -1 and top_k < sorted_indices.shape[0]:
        sorted_indices = sorted_indices[:top_k]
        sorted_scores = sorted_scores[:top_k]

    selected_indices = []
    adaptive_threshold = nms_threshold
    for i in range(sorted_scores.shape[0]):
        idx = sorted_indices[i]
        keep = True
        for k in range(len(selected_indices)):
            if keep:
                kept_idx = selected_indices[k]
                overlap = iou(boxes[idx], boxes[kept_idx], normalized)
                keep = True if overlap <= adaptive_threshold else False
            else:
                break
        if keep:
            selected_indices.append(idx)
        if keep and eta < 1 and adaptive_threshold > 0.5:
            adaptive_threshold *= eta
    return selected_indices


def multiclass_nms(boxes, scores, background, score_threshold, nms_threshold,
                   nms_top_k, keep_top_k, normalized, shared):
    if shared:
        class_num = scores.shape[0]
        priorbox_num = scores.shape[1]
    else:
        box_num = scores.shape[0]
        class_num = scores.shape[1]

    selected_indices = {}
    num_det = 0
    for c in range(class_num):
        if c == background: continue
        if shared:
            indices = nms(boxes, scores[c], score_threshold, nms_threshold,
                          nms_top_k, normalized)
        else:
            indices = nms(boxes[:, c, :], scores[:, c], score_threshold,
                          nms_threshold, nms_top_k, normalized)
        selected_indices[c] = indices
        num_det += len(indices)

    value_len = 0
    for value in selected_indices.values():
        value_len += len(value)
    if keep_top_k > -1 and num_det > keep_top_k:
        score_index = []
        for c, indices in selected_indices.items():
            for idx in indices:
                if shared:
                    score_index.append((scores[c][idx], c, idx))
                else:
                    score_index.append((scores[idx][c], c, idx))

        sorted_score_index = sorted(
            score_index, key=lambda tup: tup[0], reverse=True)
        sorted_score_index = sorted_score_index[:keep_top_k]
        selected_indices = {}

        for _, c, _ in sorted_score_index:
            selected_indices[c] = []
        for s, c, idx in sorted_score_index:
            selected_indices[c].append(idx)
        if not shared:
            for labels in selected_indices:
                selected_indices[labels].sort()
        num_det = keep_top_k

    return selected_indices, num_det


def batched_multiclass_nms(boxes,
                           scores,
                           background,
                           score_threshold,
                           nms_threshold,
                           nms_top_k,
                           keep_top_k,
                           normalized=True):
    batch_size = scores.shape[0]

    det_outs = []
    lod = []
    for n in range(batch_size):
        nmsed_outs, nmsed_num = multiclass_nms(
            boxes[n],
            scores[n],
            background,
            score_threshold,
            nms_threshold,
            nms_top_k,
            keep_top_k,
            normalized,
            shared=True)
        if nmsed_num == 0:
            continue

        lod.append(nmsed_num)
        tmp_det_out = []
        for c, indices in nmsed_outs.items():
            for idx in indices:
                xmin, ymin, xmax, ymax = boxes[n][idx][:]
                tmp_det_out.append(
                    [c, scores[n][c][idx], xmin, ymin, xmax, ymax])
        sorted_det_out = sorted(
            tmp_det_out, key=lambda tup: tup[0], reverse=False)
        det_outs.extend(sorted_det_out)
    if len(lod) == 0:
        lod += [1]
    return det_outs, lod


class TestMulticlassNMSOp(OpTest):
    def set_argument(self):
        self.score_threshold = 0.01

    def setUp(self):
        self.set_argument()
        N = 1
        M = 1200
        C = 21
        BOX_SIZE = 4
        background = 0
        nms_threshold = 0.5
        nms_top_k = 400
        keep_top_k = 200
        score_threshold = self.score_threshold

        scores = np.random.random((N * M, C)).astype('float32')

        def softmax(x):
            shiftx = x - np.max(x).clip(-64.)
            exps = np.exp(shiftx)
            return exps / np.sum(exps)

        scores = np.apply_along_axis(softmax, 1, scores)
        scores = np.reshape(scores, (N, M, C))
        scores = np.transpose(scores, (0, 2, 1))

        boxes = np.random.random((N, M, BOX_SIZE)).astype('float32')
        boxes[:, :, 0:2] = boxes[:, :, 0:2] * 0.5
        boxes[:, :, 2:4] = boxes[:, :, 2:4] * 0.5 + 0.5

        nmsed_outs, lod = batched_multiclass_nms(boxes, scores, background,
                                                 score_threshold, nms_threshold,
                                                 nms_top_k, keep_top_k)
        nmsed_outs = [-1] if not nmsed_outs else nmsed_outs
        nmsed_outs = np.array(nmsed_outs).astype('float32')

        self.op_type = 'multiclass_nms'
        self.inputs = {'BBoxes': boxes, 'Scores': scores}
        self.outputs = {'Out': (nmsed_outs, [lod])}
        self.attrs = {
            'background_label': 0,
            'nms_threshold': nms_threshold,
            'nms_top_k': nms_top_k,
            'keep_top_k': keep_top_k,
            'score_threshold': score_threshold,
            'nms_eta': 1.0,
            'normalized': True,
        }

    def test_check_output(self):
        self.check_output(return_numpy=False, is_nms=True)


if __name__ == '__main__':
    unittest.main()
