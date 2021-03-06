# coding: utf-8
from __future__ import print_function
import tensorflow as tf
from nets import nets_factory
from preprocessing import preprocessing_factory
import utils
import os

slim = tf.contrib.slim


def gram(layer):
    shape = tf.shape(layer)
    num_images = shape[0]
    width = shape[1]
    height = shape[2]
    num_filters = shape[3]
    filters = tf.reshape(layer, tf.stack([num_images, -1, num_filters]))
    grams = tf.matmul(filters, filters, transpose_a=True) / tf.to_float(width * height * num_filters)

    return grams


def get_style_features(FLAGS):
    """
    For the "style_image", the preprocessing step is:
    1. Resize the shorter side to FLAGS.image_size
    2. Apply central crop
    """
    with tf.Graph().as_default():
        network_fn = nets_factory.get_network_fn(
            FLAGS.loss_model,
            num_classes=1,
            is_training=False)
        image_preprocessing_fn, image_unprocessing_fn = preprocessing_factory.get_preprocessing(
            FLAGS.loss_model,
            is_training=False)

        # Get the style image data
        size = FLAGS.image_size
        img_bytes = tf.read_file(FLAGS.style_image)
        if FLAGS.style_image.lower().endswith('png'):
            image = tf.image.decode_png(img_bytes)
        else:
            image = tf.image.decode_jpeg(img_bytes)
        # image = _aspect_preserving_resize(image, size)

        # Add the batch dimension
        images = tf.expand_dims(image_preprocessing_fn(image, size, size), 0)
        # images = tf.stack([image_preprocessing_fn(image, size, size)])

        _, endpoints_dict = network_fn(images, spatial_squeeze=False)
        features = []
        for layer in FLAGS.style_layers:
            feature = endpoints_dict[layer]
            feature = tf.squeeze(gram(feature), [0])  # remove the batch dimension
            features.append(feature)

        with tf.Session() as sess:
            # Restore variables for loss network.
            init_func = utils._get_init_fn(FLAGS)
            init_func(sess)

            # Make sure the 'generated' directory is exists.
            if os.path.exists('generated') is False:
                os.makedirs('generated')
            # Indicate cropped style image path
            save_file = 'generated/target_style_' + FLAGS.naming + '.jpg'
            # Write preprocessed style image to indicated path
            with open(save_file, 'wb') as f:
                target_image = image_unprocessing_fn(images[0, :])
                value = tf.image.encode_jpeg(tf.cast(target_image, tf.uint8))
                f.write(sess.run(value))
                tf.logging.info('Target style pattern is saved to: %s.' % save_file)

            # Return the features those layers are use for measuring style loss.
            return sess.run(features)


# 风格损失函数：endpoints_dict为损失网络各层的计算结果，content_layers是定义用哪些层的差距计算损失，style_features_t是利用原始的风格图片计算的层激活
def style_loss(endpoints_dict, style_features_t, style_layers):
    style_loss = 0
    # summary是服务TensorBoard用的
    style_loss_summary = {}
    for style_gram, layer in zip(style_features_t, style_layers):
        # 计算风格损失：需要计算生成图片和目标分风格之间层激活的损失
        generated_images, _ = tf.split(endpoints_dict[layer], 2, 0)
        size = tf.size(generated_images)
        # 调用gram函数计算Gram矩阵，风格损失定义为生成图片和目标风格图片之间Gram矩阵的L平方差距
        layer_style_loss = tf.nn.l2_loss(gram(generated_images) - style_gram) * 2 / tf.to_float(size)
        style_loss_summary[layer] = layer_style_loss
        style_loss += layer_style_loss
    return style_loss, style_loss_summary


# 内容损失函数：endpoints_dict为损失网络各层的计算结果，content_layers是定义用哪些层的差距计算损失
def content_loss(endpoints_dict, content_layers):
    content_loss = 0
    for layer in content_layers:
        # 生成图像和原始图像同时传入损失网络中进行计算
        generated_images, content_images = tf.split(endpoints_dict[layer], 2, 0)
        size = tf.size(generated_images)
        # 内容损失：生成图片激活和原始图片激活的L平方距离
        content_loss += tf.nn.l2_loss(generated_images - content_images) * 2 / tf.to_float(
            size)  # remain the same as in the paper
    return content_loss


def total_variation_loss(layer):
    shape = tf.shape(layer)
    height = shape[1]
    width = shape[2]
    y = tf.slice(layer, [0, 0, 0, 0], tf.stack([-1, height - 1, -1, -1])) - tf.slice(layer, [0, 1, 0, 0],
                                                                                     [-1, -1, -1, -1])
    x = tf.slice(layer, [0, 0, 0, 0], tf.stack([-1, -1, width - 1, -1])) - tf.slice(layer, [0, 0, 1, 0],
                                                                                    [-1, -1, -1, -1])
    loss = tf.nn.l2_loss(x) / tf.to_float(tf.size(x)) + tf.nn.l2_loss(y) / tf.to_float(tf.size(y))
    return loss
