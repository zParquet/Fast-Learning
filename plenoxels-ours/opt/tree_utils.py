import math
import os

from tqdm import tqdm
import torch
import numpy as np
from cv2 import cv2
import pickle

from image_process import ImageProcessor
from tree import QuadTreeNode, get_children


class SimpleQuadTree:
    """四叉树"""
    def __init__(self, h, w, max_depth: int):
        """
        :param image: [h, w, 3]
        :param stdThres:
        """
        self.H, self.W = h, w
        self.root = QuadTreeNode(0, 0, self.H, self.W)
        recursive_subdivide(self.root, 1, max_depth)


class RaySampler():
    def __init__(self, dataset, max_level):
        super(RaySampler, self).__init__()

        self.n_images, self.h, self.w = dataset.n_images, dataset.h_full, dataset.w_full
        rays = dataset.rays
        self.dataset = dataset
        self.init_epoch_size = dataset.epoch_size
        self.images = rays.gt.reshape(self.n_images, self.h, self.w, -1)
        self.dirs = rays.dirs.reshape(self.n_images, self.h, self.w, -1)
        self.origins = rays.origins.reshape(self.n_images, self.h, self.w, -1)

        self.max_level = max_level  # level=1时是不分割，level=2时是切成四块
        self.processor = ImageProcessor(dataset)

    def hw2coor(self, x0, y0, level):
        # reso: 四叉树层级
        n_block_side = self.h / (2 ** level)

    def pre_gen_rays_v3(self, down_scale=1, rand_samp_prec=0.2, dset_name='lego'):
        """
        在构造数据集时提前把光线采样好，这是为了节省训练过程中采样的时间。
        输入：self.images, self.dirs, self.origins
        :return: 四叉树所有层级的采样的origin, dir, rgb，[n_images, n_level, [n_block_x, n_block_y], x, n_ray]
        """
        ray_num_per_image = self.dataset.epoch_size / self.n_images / down_scale
        ray_num_per_pixel = ray_num_per_image / self.h / self.w

        # 这个树的划分是给所有图片用的
        multilevel_trees = [SimpleQuadTree(self.h, self.w, max_level) for max_level in range(0, self.max_level+1)]

        all_ret = []
        pkl_filename = 'process/{}_maxlevel{}_rand{}.pkl'.format(dset_name, str(self.max_level), str(rand_samp_prec))
        if not os.path.exists('process'):
            os.mkdir('process')
        if os.path.exists(pkl_filename):
            with open(pkl_filename, 'rb') as f:
                all_ret = pickle.load(f)
                print("load '"+pkl_filename+"'")
        else:
            for img_i in tqdm(range(self.n_images)):
                one_img_ret = []
                one_img_ret.append([])      # 第0个没用
                for level in range(1, self.max_level+1):
                    one_level_ret = []
                    n_block_side = 2 ** (level-1)   # 每个边上有多少段
                    block_h_length = self.h / n_block_side
                    block_w_length = self.w / n_block_side
                    ray_num_per_block = int(ray_num_per_image / n_block_side / n_block_side)

                    all_selected_rgb = torch.zeros(n_block_side, n_block_side, ray_num_per_block, 3)
                    all_selected_dir = torch.zeros(n_block_side, n_block_side, ray_num_per_block, 3)
                    all_selected_origin = torch.zeros(n_block_side, n_block_side, ray_num_per_block, 3)
                    all_selected_pixel = torch.LongTensor(n_block_side, n_block_side, ray_num_per_block, 2)
                    children = get_children(multilevel_trees[level].root)
                    for child in children:
                        ray_num1 = int(ray_num_per_block * (1-rand_samp_prec))
                        ray_num2 = ray_num_per_block - ray_num1
                        sharp_images = self.processor.sharp_imgs[img_i]
                        image_block = sharp_images[int(child.x0): int(child.x1), int(child.y0): int(child.y1)]
                        seleted_pixel = self.processor.sample_pixels(image_block, ray_num1)
                        child_selected_pixel = []
                        child_selected_pixel.append(seleted_pixel + torch.LongTensor([int(child.x0), int(child.y0)]))

                        selected_pixel_x = torch.randint(math.ceil(child.x0), math.ceil(child.x1), (ray_num2,))
                        selected_pixel_y = torch.randint(math.ceil(child.y0), math.ceil(child.y1 - 0.01), (ray_num2,))
                        seleted_pixel = torch.stack([selected_pixel_x, selected_pixel_y], 1)
                        child_selected_pixel.append(seleted_pixel)
                        child_selected_pixel = torch.cat(child_selected_pixel, 0)

                        # interpolated_rgb = self.images[img_i][child_selected_pixel[:, 0], child_selected_pixel[:, 1], :]
                        # interpolated_dir = self.dirs[img_i][child_selected_pixel[:, 0], child_selected_pixel[:, 1], :]
                        # interpolated_origin = self.origins[img_i][child_selected_pixel[:, 0], child_selected_pixel[:, 1], :]

                        coorh = int(child.x0 // block_h_length)
                        coorw = int(child.y0 // block_w_length)
                        # all_selected_rgb[coorh, coorw] = interpolated_rgb
                        # all_selected_dir[coorh, coorw] = interpolated_dir
                        # all_selected_origin[coorh, coorw] = interpolated_origin
                        all_selected_pixel[coorh, coorw] = child_selected_pixel
                    # 顺序是：rgb，光线方向，光线原点，采样像素点
                    # one_level_ret += [all_selected_rgb, all_selected_dir, all_selected_origin, torch.cat(all_selected_pixel, 0)]
                    # one_level_ret += [all_selected_rgb, all_selected_dir, all_selected_origin]
                    one_img_ret.append(all_selected_pixel)
                    # break   # TODO
                all_ret.append(one_img_ret)
                # break   # TODO

            with open(pkl_filename, 'wb') as f:
                pickle.dump(all_ret, f)

        if False:
            test_img_id = 0
            test_level = 0
            imgc = np.ones_like(self.images[test_img_id].numpy().copy()) * 255.0
            c = get_children(multilevel_trees[test_level].root)
            for x, y in all_ret[test_img_id][test_level][3].numpy():
                imgc = cv2.circle(imgc, (int(y), int(x)), 0, (255, 0, 0), -1)
            for n in c:
                # Draw a rectangle
                imgc = cv2.rectangle(imgc, (int(n.y0), int(n.x0)), (int(n.y1), int(n.x1)), (0, 0, 0), 1)

            if not os.path.exists('debug'):
                os.makedirs('debug')
            cv2.imwrite('debug/split_and_sample_points_{}.jpg'.format(str(test_img_id)), imgc[:, :, [2, 1, 0]])

        return all_ret

    # def visualize_split_and_sample_points(self, img_id, selected_pixel):
    #     # 同时可视化四叉树划分和在树上的采样点，图片不显示，防止挡住采样点
    #     imgc = np.ones_like(self.images[img_id].numpy().copy()) * 255.0
    #     c = get_children(self.quadTrees[img_id].root)
    #     for x, y in selected_pixel.numpy():
    #         imgc = cv2.circle(imgc, (int(y), int(x)), 1, (255, 0, 0), -1)
    #     for n in c:
    #         # Draw a rectangle
    #         imgc = cv2.rectangle(imgc, (int(n.y0), int(n.x0)), (int(n.y1), int(n.x1)), (0, 0, 0), 1)
    #
    #     if not os.path.exists('debug/train'):
    #         os.makedirs('debug/train')
    #     cv2.imwrite('debug/train/split_and_sample_points_{}.jpg'.format(str(img_id)), imgc[:, :, [2, 1, 0]])


def recursive_subdivide(node: QuadTreeNode, cur_depth, max_depth):
    if cur_depth >= max_depth:
        return

    midx = (node.x0+node.x1)/2
    midy = (node.y0+node.y1)/2
    # 左上
    node1 = QuadTreeNode(node.x0, node.y0, midx, midy)
    recursive_subdivide(node1, cur_depth+1, max_depth)
    # 左下
    node2 = QuadTreeNode(midx, node.y0, node.x1, midy)
    recursive_subdivide(node2, cur_depth+1, max_depth)
    # 右上
    node3 = QuadTreeNode(node.x0, midy, midx, node.y1)
    recursive_subdivide(node3, cur_depth+1, max_depth)
    # 右下
    node4 = QuadTreeNode(midx, midy, node.x1, node.y1)
    recursive_subdivide(node4, cur_depth+1, max_depth)

    node.children = [node1, node2, node3, node4]
