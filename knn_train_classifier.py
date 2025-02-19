from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import cv2
from os.path import join as pjoin
import matplotlib.pyplot as plt
import sklearn
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn import metrics
from sklearn.externals import joblib
from scipy import misc
import tensorflow as tf
import numpy as np
import sys
import os
import copy
import argparse
import core.facenet as facenet
import core.detect_face as detect_face


def load_and_align_data(image, image_size, margin, gpu_memory_fraction):
    #print('Creating networks and loading parameters')
    with tf.Graph().as_default():
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=1.0)
        sess = tf.Session(config=tf.ConfigProto(
            gpu_options=gpu_options, log_device_placement=False))
        with sess.as_default():
            pnet, rnet, onet = detect_face.create_mtcnn(sess, './data')
    minsize = 20  # minimum size of face
    threshold = [0.6, 0.7, 0.7]  # three steps's threshold
    factor = 0.709  # scale factor
    # 读取图片
    img = image
    # 获取图片的shape
    img_size = np.asarray(img.shape)[0:2]
    # 返回边界框数组 （参数分别是输入图片 脸部最小尺寸 三个网络 阈值 factor不清楚）
    bounding_boxes, _ = detect_face.detect_face(
        img, minsize, pnet, rnet, onet, threshold, factor)

    # 如果检测出图片中不存在人脸 则直接返回，return 0（表示不存在人脸，跳过此图）
    if len(bounding_boxes) < 1:
        return 0, 0, 0
    else:
        crop = []
        det = bounding_boxes

        det[:, 0] = np.maximum(det[:, 0], 0)
        det[:, 1] = np.maximum(det[:, 1], 0)
        det[:, 2] = np.minimum(det[:, 2], img_size[1])
        det[:, 3] = np.minimum(det[:, 3], img_size[0])

        # det[:,0]=np.maximum(det[:,0]-margin/2, 0)
        # det[:,1]=np.maximum(det[:,1]-margin/2, 0)
        # det[:,2]=np.minimum(det[:,2]+margin/2, img_size[1])
        # det[:,3]=np.minimum(det[:,3]+margin/2, img_size[0])

        det = det.astype(int)

        for i in range(len(bounding_boxes)):
            temp_crop = img[det[i, 1]:det[i, 3], det[i, 0]:det[i, 2], :]
            aligned = misc.imresize(
                temp_crop, (image_size, image_size), interp='bilinear')
            prewhitened = facenet.prewhiten(aligned)
            crop.append(prewhitened)
        crop_image = np.stack(crop)

        return det, crop_image, 1

    # np.squeeze() 降维，指定第几维，如果那个维度不是1  则无法降维
    # det = np.squeeze(bounding_boxes[0,0:4])


def to_rgb(img):
    w, h = img.shape
    ret = np.empty((w, h, 3), dtype=np.uint8)
    ret[:, :, 0] = ret[:, :, 1] = ret[:, :, 2] = img
    return ret


def load_data(data_dir):
    # data为字典类型 key对应人物分类 value为读取的一个人的所有图片 类型为ndarray
    data = {}
    for guy in os.listdir(data_dir):
        person_dir = pjoin(data_dir, guy)
        curr_pics = [read_img(person_dir, f) for f in os.listdir(person_dir)]

        # 存储每一类人的文件夹内所有图片
        data[guy] = curr_pics
    return data


def read_img(person_dir, f):
    img = cv2.imread(pjoin(person_dir, f))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 判断数组维度
    if gray.ndim == 2:
        img = to_rgb(gray)
    return img


def main(args):
    # model_dir='./20170512-110547'
    model_dir = args.model_dir
    train_dir = args.train_dir
    with tf.Graph().as_default():
        with tf.Session() as sess:
            meta_file, ckpt_file = facenet.get_model_filenames(model_dir)
            #print(meta_file, ckpt_file)
            facenet.load_model(model_dir, meta_file, ckpt_file)

            # 返回给定名称的tensor
            images_placeholder = tf.get_default_graph().get_tensor_by_name("input:0")
            embeddings = tf.get_default_graph().get_tensor_by_name("embeddings:0")
            phase_train_placeholder = tf.get_default_graph().get_tensor_by_name("phase_train:0")

            # 从训练数据文件夹中加载图片并剪裁，最后embding，data为dict
            data = load_data(train_dir)

            # keys列表存储图片文件夹类别（几个人）
            keys = []
            for key in data:
                keys.append(key)
                print('folder:{},image numbers：{}'.format(key, len(data[key])))

            train_x = []
            train_y = []

            # 使用mtcnn模型获取每张图中face的数量以及位置，并将得到的embedding数据存储
            for x in data[keys[0]]:
                _, images_me, i = load_and_align_data(x, 160, 44, 1.0)
                if i:
                    feed_dict = {images_placeholder: images_me,
                                 phase_train_placeholder: False}
                    emb = sess.run(embeddings, feed_dict=feed_dict)
                    # print(type(emb))

                    for xx in range(len(emb)):
                        #print(type(emb[xx, :]), emb[xx, :].shape)
                        train_x.append(emb[xx, :])
                        train_y.append(0)
            # print(len(train_x))

            for y in data[keys[1]]:
                _, images_others, j = load_and_align_data(y, 160, 44, 1.0)
                if j:
                    feed_dict = {images_placeholder: images_others,
                                 phase_train_placeholder: False}
                    emb = sess.run(embeddings, feed_dict=feed_dict)
                    for xx in range(len(emb)):
                        #print(type(emb[xx, :]), emb[xx, :].shape)
                        train_x.append(emb[xx, :])
                        train_y.append(1)
            # print(len(train_x))

            print('搞完了，样本数为：{}'.format(len(train_x)))

    train_x = np.array(train_x)
    # print(train_x.shape)
    train_x = train_x.reshape(-1, 128)
    train_y = np.array(train_y)
    # print(train_x.shape)
    # print(train_y.shape)

    X_train, X_test, y_train, y_test = train_test_split(
        train_x, train_y, test_size=.3, random_state=42)
    #print(X_train.shape, y_train.shape, X_test.shape, y_test.shape)

    classifiers = knn_classifier

    model = classifiers(X_train, y_train)
    predict = model.predict(X_test)

    accuracy = metrics.accuracy_score(y_test, predict)
    print('accuracy: %.2f%%' % (100 * accuracy))

    # save model
    joblib.dump(model, './models/knn_classifier.model')

    model = joblib.load('./models/knn_classifier.model')
    predict = model.predict(X_test)
    accuracy = metrics.accuracy_score(y_test, predict)
    print('accuracy: %.2f%%' % (100 * accuracy))

# KNN Classifier


def knn_classifier(train_x, train_y):
    from sklearn.neighbors import KNeighborsClassifier
    model = KNeighborsClassifier()
    model.fit(train_x, train_y)
    return model


def parse_arguments(argv):
    parser = argparse.ArgumentParser()

    parser.add_argument('--model_dir', type=str,
                        help='Directory containing the meta_file and ckpt_file', default='./20170512-110547')
    # parser.add_argument('--dlib_face_predictor', type=str,
    # help='File containing the dlib face predictor.', default='../data/shape_predictor_68_face_landmarks.dat')
    parser.add_argument('--image_size', type=int,
        help='Image size (height, width) in pixels.', default=160)
    parser.add_argument('--train_dir', type=str,
                        help='Directory containing the training file.')
    parser.add_argument('--margin', type=int,
        help='Margin for the crop around the bounding box (height, width) in pixels.', default=44)
    # parser.add_argument('--gpu_memory_fraction', type=float,
    #    help='Upper bound on the amount of GPU memory that will be used by the process.', default=1.0)
    return parser.parse_args(argv)


if __name__ == '__main__':
    main(parse_arguments(sys.argv[1:]))
