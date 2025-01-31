#
# MIT License
#
# Copyright (c) 2020-2021 NVIDIA CORPORATION.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.#
import torch
import torch.nn as nn
# import torch.nn.functional as F
import os
import numpy as np

from ...differentiable_robot_model.coordinate_transform import CoordinateTransform, quaternion_to_matrix

from ...util_file import get_assets_path, join_path
from ...geom.sdf.robot_world import RobotWorldCollisionVoxel
from .gaussian_projection import GaussianProjection

from scenecollisionnet.collision_models.collision_nets import SceneCollisionNet
from scenecollisionnet.policy.collision_checker import NNStormSceneCollisionChecker
from scenecollisionnet.policy.robot import Robot as SCNRobot

class SceneCollisionNetCost(nn.Module):
    def __init__(self, weight=None, robot_params=None,
                 gaussian_params={}, grid_resolution=0.05, distance_threshold=-0.01, 
                 batch_size=2, tensor_args={'device':torch.device('cpu'), 'dtype':torch.float32}):
        super(SceneCollisionNetCost, self).__init__()
        self.tensor_args = tensor_args
        self.device = tensor_args['device']
        self.float_dtype = tensor_args['dtype']
        self.distance_threshold = distance_threshold
        self.weight = torch.as_tensor(weight, **self.tensor_args)
        
        self.proj_gaussian = GaussianProjection(gaussian_params=gaussian_params)


        # load robot model:
        robot_collision_params = robot_params['robot_collision_params']
        robot_collision_params['urdf'] = join_path(get_assets_path(),
                                                   robot_collision_params['urdf'])


        # load nn params:
        label_map = robot_params['world_collision_params']['label_map']
        bounds = robot_params['world_collision_params']['bounds']
        model_path = robot_params['world_collision_params']['model_path']
        self.threshold = robot_params['robot_collision_params']['threshold']
        self.batch_size = batch_size
        
        self.robot = SCNRobot(robot_collision_params['urdf'], 'right_gripper', self.device)
        
        # initialize NN model:
        self.coll = NNStormSceneCollisionChecker(
            model_path=model_path, 
            robot=self.robot, 
            device=self.device, 
            use_knn=False
        )
        

        #self.coll.set_robot_objects()
        # self.coll.build_batch_features(self.batch_size, clone_pose=True, clone_points=True)
        
        self.COLL_INIT = False
        self.SCENE_INIT = False
        self.camera_data = None
        self.res = None
        self.t_mat = None

    def set_scene(self, camera_data):
        self.camera_data = camera_data

        rtm = np.eye(4)
        
        print(camera_data['pc_seg'])
        
        in_obs = {
            "pc": camera_data['pc'],
            "pc_label": camera_data['pc_seg'],
            "label_map": camera_data['label_map'],
            "camera_pose": camera_data['robot_camera_pose'],
            "robot_to_model": rtm,
            "model_to_robot": np.linalg.inv(rtm),
        }
        self.coll.set_scene(in_obs)

        self.SCENE_INIT = True


    def forward(self, link_pos_seq, link_rot_seq):
        batch_size = link_pos_seq.shape[0]
        horizon = link_pos_seq.shape[1]
        n_links = link_pos_seq.shape[2]
        link_pos = link_pos_seq.view(batch_size * horizon, n_links, 3)
        link_rot = link_rot_seq.view(batch_size * horizon, n_links, 3, 3)
        print('####', link_pos.shape, link_rot.shape)
        if(self.batch_size != batch_size):
            self.batch_size = batch_size
        
        print("@", link_rot_seq.shape)
        coll_mask = self.coll(link_pos, link_rot)
        coll_mask |= self.coll(link_pos, link_rot, threshold=0.45)

        self.res = res
        res = res.view(batch_size, horizon, n_links)
        

        # all values are positive now
        res = torch.sum(res, dim=-1)
        
        
        cost = res

        cost = self.weight * self.proj_gaussian(cost)
        
        return cost
