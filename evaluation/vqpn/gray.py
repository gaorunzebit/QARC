import os
import numpy as np
import tensorflow as tf
import tflearn
import h5py
from PIL import Image
from tflearn.data_utils import shuffle, to_categorical
from tflearn.layers.conv import max_pool_2d
import matplotlib.pyplot as plt
from matplotlib.pyplot import plot, savefig
import sys
from tqdm import tqdm
# implmenation of vmaf neural network
# in 640x360
# out vmaf future score
INPUT_W = 64
INPUT_H = 36
INPUT_D = 3
# long seq
INPUT_SEQ = 25
OUTPUT_DIM = 5

KERNEL = int(sys.argv[1])

EPOCH = 1500
BATCH_SIZE = 50
LR_RATE = float(sys.argv[2])
EARLYSTOP = 50
HIDDEN_UNIT = KERNEL
#
# long term 1,5,10
#


def load_model(sess, scope_name='cnn_core'):
    with tf.variable_scope(scope_name, reuse=True):
        v = tf.get_variable('vqn/full-lstm/FullyConnected/W')
        fc = sess.run(v)
        return np.reshape(fc, (-1, OUTPUT_DIM)).T


def attention(inputs, attention_size):
    _inputs = tflearn.merge(inputs, 'concat')
    #print _inputs.get_shape().as_list()
    inputs = tf.reshape(_inputs, (-1, INPUT_SEQ, HIDDEN_UNIT))
    # the length of sequences processed in the antecedent RNN layer
    sequence_length = inputs.get_shape()[1].value
    hidden_size = inputs.get_shape()[2].value  # hidden size of the RNN layer

    # Attention mechanism
    W_omega = tf.Variable(tf.random_normal(
        [hidden_size, attention_size], stddev=0.1))
    b_omega = tf.Variable(tf.random_normal([attention_size], stddev=0.1))
    u_omega = tf.Variable(tf.random_normal([attention_size], stddev=0.1))

    v = tf.tanh(tf.matmul(tf.reshape(
        inputs, [-1, hidden_size]), W_omega) + tf.reshape(b_omega, [1, -1]))
    vu = tf.matmul(v, tf.reshape(u_omega, [-1, 1]))
    #alphas = tf.nn.softmax(vu)
    exps = tf.reshape(tf.exp(vu), [-1, sequence_length])
    alphas = exps / tf.reshape(tf.reduce_sum(exps, 1), [-1, 1])

    # Output of Bi-RNN is reduced with attention vector
    output = tf.reduce_sum(
        inputs * tf.reshape(alphas, [-1, sequence_length, 1]), 1)

    return output, alphas


def load_h5(filename):
    h5f = h5py.File(filename, 'r')
    X = h5f['X']
    Y = h5f['Y']
    X, Y = shuffle(X, Y)
    return X, Y


def CNN_Core(x, reuse=False):
    with tf.variable_scope('cnn_core', reuse=reuse):
        network = tflearn.conv_2d(
            x, KERNEL, 3, activation='relu', regularizer="L2", weight_decay=0.0001)
        network = tflearn.max_pool_2d(network, 2)
        cnn_network = tflearn.conv_2d(
            network, KERNEL * 2, 3, activation='relu', regularizer="L2", weight_decay=0.0001)
        #network = tflearn.max_pool_2d(network, 2)
        # network = tflearn.conv_2d(
        #    network, KERNEL * 4, 3, activation='relu', regularizer="L2", weight_decay=0.0001)
        #network = tflearn.max_pool_2d(network, 2)
        network = tflearn.global_avg_pool(cnn_network)
        split_flat = tflearn.flatten(network)
        #print split_flat.get_shape().as_list()
        return split_flat, cnn_network


def vqn_model(x):
    with tf.variable_scope('vqn'):
        inputs = tflearn.input_data(placeholder=x)
        _split_array = []
        _cnn_array = []

        for i in range(INPUT_SEQ):
            tmp_network = tf.reshape(
                inputs[:, i:i+1, :, :, :], [-1, INPUT_H, INPUT_W, INPUT_D])
            if i == 0:
                _tmp_split, _tmp_cnn = CNN_Core(tmp_network)
            else:
                _tmp_split, _tmp_cnn = CNN_Core(tmp_network, True)
            _split_array.append(_tmp_split)
            _cnn_array.append(_tmp_cnn)

        merge_net = tflearn.merge(_split_array, 'concat')
        merge_net = tflearn.flatten(merge_net)
        _count = merge_net.get_shape().as_list()[1]

        with tf.variable_scope('full-lstm'):
            net = tf.reshape(merge_net, [-1, INPUT_SEQ, _count / INPUT_SEQ])
            net = tflearn.gru(net, HIDDEN_UNIT, return_seq=True)
            net = tflearn.gru(net, HIDDEN_UNIT, return_seq=True)
            net, alphas = attention(net, HIDDEN_UNIT)
            out = tflearn.fully_connected(
                net, OUTPUT_DIM, activation='sigmoid')

        return out, tf.stack(_cnn_array, axis=0), alphas


def save_plot(y_pred, y, j):
    plt.switch_backend('agg')
    plt.figure()
    fig, ax = plt.subplots(
        y.shape[1], 1, sharex=True, figsize=(10, 16), dpi=100)
    x = np.linspace(0, y.shape[0] - 1, y.shape[0])
    # ax.set_ylim(0,1)
    for i in range(y.shape[1]):
        ax[i].grid(True)
        ax[i].plot(x, y[:, i])
        ax[i].plot(x, y_pred[:, i])

    savefig('save/' + str(KERNEL) + '_' + str(KERNEL) +
            '_' + str(LR_RATE) + '/' + str(j) + '.png')


def load_data(dirs):
    _files = os.listdir(dirs)
    _array = []
    for _file in _files:
        _img = load_image(dirs + _file)
        _array.append(np.array(_img).shape)
    return np.array(_array)


def load_image(filename):
    img = Image.open(filename)
    return img


def event_loop():
    X, Y = load_h5('../train.h5')
    testX, testY = load_h5('../test.h5')
    gpu_options = tf.GPUOptions(allow_growth=True)
    with tf.Session(config=tf.ConfigProto(gpu_options=gpu_options)) as sess:
        x = tf.placeholder(
            shape=[None,  INPUT_SEQ, INPUT_H, INPUT_W, INPUT_D], dtype=tf.float32)
        y_ = tf.placeholder(shape=[None, OUTPUT_DIM], dtype=tf.float32)
        core_net, cnn_array, alphas = vqn_model(x)

        vars = tf.trainable_variables()
        lossL2 = tf.add_n([tf.nn.l2_loss(v) for v in vars]) * 1e-3

        core_net_loss = tflearn.objectives.mean_square(core_net, y_)
        #tf.sqrt(tf.reduce_mean(tf.square(tf.subtract(core_net, y_))))
        # tflearn.objectives.mean_square
        # + lossL2
        core_train_op = tf.train.AdamOptimizer(
            learning_rate=LR_RATE).minimize(core_net_loss)
        core_net_acc = tf.sqrt(tflearn.objectives.mean_square(core_net, y_))
        core_net_mape = tf.subtract(1.0, tf.reduce_mean(
            tf.abs(core_net - y_) / tf.abs(y_)))
        train_len = X.shape[0]
        sess.run(tf.global_variables_initializer())
        saver = tf.train.Saver()
        best_saver = tf.train.Saver()
        _writer = open('log/' + str(KERNEL) + '_' +
                       str(KERNEL) + '_' + str(LR_RATE) + '.csv', 'w')
        _min_mape, _min_step = 100.0, 0
        for j in range(1, EPOCH + 1):
            i = 0
            while i < train_len - BATCH_SIZE:
                batch_xs, batch_ys = X[i:i+BATCH_SIZE], Y[i:i+BATCH_SIZE]
                sess.run(core_train_op, feed_dict={
                    x: batch_xs, y_: batch_ys})
                i += BATCH_SIZE

            #_test_acc = sess.run(core_net_acc, feed_dict={x: testX,y_:testY})
            _test_mape = sess.run(core_net_acc, feed_dict={
                                  x: testX, y_: testY})
            print 'epoch', j, 'rmse', _test_mape
            if j % 5 == 0:
                _w = load_model(sess)
                inference_y, feature_maps, alpha = sess.run(
                    [core_net, cnn_array, alphas], feed_dict={x: testX})
                print alpha
                for p in tqdm(range(testX.shape[0])):
                    infernce_arg_max = np.argmax(inference_y[p])
                    for q in range(INPUT_SEQ):
                        _heat_map = np.dot(
                            feature_maps[p, q], 
                            alpha[q] * _w[infernce_arg_max].reshape(-1, 1)).reshape((INPUT_W // 2, INPUT_H // 2))
                    show_heat(_heat_map)

            if _min_mape > _test_mape:
                _min_mape = _test_mape
                _min_step = j
                best_saver.save(sess, 'best/' + str(KERNEL) + '_' +
                                str(KERNEL) + '_' + str(LR_RATE) + '/nn_model_ep_best.ckpt')
                _test_y = sess.run(core_net, feed_dict={x: testX})
                save_plot(_test_y, testY, j)
                _best = open('best/' + str(KERNEL) + '_' +
                             str(KERNEL) + '_' + str(LR_RATE) + '.txt', 'w')
                _best.write(str(_test_mape))
                _best.close()
                print 'new record'
            else:
                if j - _min_step > EARLYSTOP:
                    print 'early stop'
                    return

            _writer.write(str(j) + ',' + str(_test_mape) + '\n')


def show_heat(heatmap):
    global heat_index
    plt.figure()
    plt.imshow(heatmap)
#    cb=plt.colorbar(mappable=map,cax=None,ax=None,shrink=0.5)
    plt.savefig('save_figs/' + str(heat_index) + '.png')
    heat_index += 1


def main():
    if os.path.exists('best/' + str(KERNEL) + '_' + str(KERNEL) + '_' + str(LR_RATE) + '.txt'):
        print 'this params has been previously operated.'
        return
    os.environ['CUDA_VISIBLE_DEVICES'] = '1'
    os.system('mkdir save')
    os.system('mkdir model')
    os.system('mkdir best')
    os.system('mkdir log')
    os.system('mkdir save_figs')

    os.system('mkdir save/' + str(KERNEL) + '_' +
              str(KERNEL) + '_' + str(LR_RATE))
    os.system('mkdir model/' + str(KERNEL) + '_' +
              str(KERNEL) + '_' + str(LR_RATE))
    os.system('mkdir best/' + str(KERNEL) + '_' +
              str(KERNEL) + '_' + str(LR_RATE))
    event_loop()


if __name__ == '__main__':
    main()
