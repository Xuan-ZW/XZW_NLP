import os
import sys
import numpy as np
import tensorflow as tf
from tensorflow.contrib.legacy_seq2seq.python.ops import seq2seq
import jieba
import random
from tensorflow.python import debug as tfdbg
from pre_data import WordToken
# 输入序列长度
input_seq_len = 5
# 输出序列长度
output_seq_len = 5
# 空值填充0
PAD_ID= 0
# 输出序列起始标记
GO_ID = 1
# 结尾标记
EOS_ID = 2
# LSTM神经元size
size = 8
# 初始化学习率
init_learning_rate = 0.001
# 在样本中出现频率超过这个词才会进入词表
min_freq = 10

wordToken = WordToken()
output_dir = './model/chatbot/demo'
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# 放在全局的位置， 为了动态算出num_encoder_symbols 和 num_decoder_symbols
max_token_id = wordToken.load_file_list(['./chatbot/question.txt', './chatbot/answer.txt'], min_freq)
num_encoder_symbols = max_token_id + 5
num_decoder_symbols = max_token_id + 5


def get_id_list_from(sentence):
    sentence_id_list = []
    seg_list = jieba.cut(sentence)
    for str in seg_list:
        id = wordToken.word2id(str)
        if id:
            sentence_id_list.append(wordToken.word2id(str))
    return sentence_id_list


def get_train_set():
    global num_encoder_symbols, num_decoder_symbols
    train_set = []
    with open('./chatbot/question.txt', 'r', encoding='utf-8') as question_file:
        with open('./chatbot/answer.txt', 'r', encoding='utf-8') as answer_file:
            while True:
                question = question_file.readline()
                answer = answer_file.readline()
                if question and answer:
                    question = question.strip()
                    answer = answer.strip()

                    question_id_list = get_id_list_from(question)
                    answer_id_list = get_id_list_from(answer)
                    answer_id_list.append(EOS_ID)
                    train_set.append([question_id_list, answer_id_list])
                else:
                    break
    return train_set


def get_samples(train_set, batch_num):
    """
    构造样本数据
    :param train_set:
    :param batch_num:
    :return:
    """
    raw_encoder_input = []
    raw_decoder_input = []
    if batch_num >= len(train_set):
        batch_train_set = train_set
    else:
        random_start = random.randint(0,len(train_set) - batch_num)
        batch_train_set = train_set[random_start:random_start + batch_num]
    for sample in batch_train_set:
        raw_encoder_input.append([PAD_ID] * (input_seq_len - len(sample[0])) + sample[0])
        raw_decoder_input.append([GO_ID] + sample[1] + [PAD_ID] * (output_seq_len - len(sample[1]) - 1))

    encoder_inputs = []
    decoder_inputs = []
    target_weights = []

    for length_idx in range(input_seq_len):
        encoder_inputs.append(np.array([encoder_input[length_idx] for encoder_input in raw_encoder_input], dtype=np.int32))
    for length_idx in range(output_seq_len):
        decoder_inputs.append(np.array([decoder_input[length_idx]
                                        for decoder_input in raw_decoder_input],dtype=np.int32))
        target_weights.append(np.array([
            0.0 if length_idx == output_seq_len - 1
            or decoder_input[length_idx] ==PAD_ID else 1.0 for decoder_input in raw_decoder_input
        ], dtype=np.float32))
    return encoder_inputs, decoder_inputs, target_weights


def seq_to_encoder(input_seq):
    """
    从输入空格分隔的数字id串， 转成预测用的encoder, decoder, target_weight等
    :param input_seq:
    :return:
    """
    input_seq_array = [int(v) for v in input_seq.split()]
    encoder_input = [PAD_ID] * (input_seq_len - len(input_seq_array)) + input_seq_array
    decoder_input = [GO_ID] + [PAD_ID] * (output_seq_len - 1)
    encoder_inputs = [np.array([v], dtype=np.int32) for v in encoder_input]
    decoder_inputs = [np.array([v], dtype=np.int32) for v in decoder_input]
    target_weights = [np.array([1.0], dtype=np.float32)] * output_seq_len
    return encoder_inputs, decoder_inputs, target_weights


def get_model(feed_previous=False):
    """
    构造模型
    :param feed_previous:
    :return:
    """
    learning_rate = tf.Variable(float(init_learning_rate), trainable=False, dtype=tf.float32)
    learning_rate_decay_op = learning_rate.assign(learning_rate * 0.9)
    encoder_inputs = []
    decoder_inputs = []
    target_weights = []
    for i in range(input_seq_len):
        encoder_inputs.append(tf.compat.v1.placeholder(tf.int32, shape=[None], name="encoder{0}".format(i)))
    for i in range(output_seq_len + 1):
        decoder_inputs.append(tf.compat.v1.placeholder(tf.int32, shape=[None], name="decoder{0}".format(i)))
    for i in range(input_seq_len):
        target_weights.append(tf.compat.v1.placeholder(tf.float32, shape=[None], name="weight{0}".format(i)))

    # decoder_inputs 左移一个时序作为targets
    targets = [decoder_inputs[i + 1] for i in range(output_seq_len)]
    cell = tf.contrib.rnn.BasicLSTMCell(size)

    # 这里输出的状态我们不需要
    outputs, _ = seq2seq.embedding_attention_seq2seq(
        encoder_inputs,
        decoder_inputs[:output_seq_len],
        cell,
        num_encoder_symbols=num_encoder_symbols,
        num_decoder_symbols=num_decoder_symbols,
        embedding_size=size,
        output_projection=None,
        feed_previous=feed_previous,
        dtype=tf.float32
    )
    # 计算交叉熵损失
    loss = seq2seq.sequence_loss(outputs, targets, target_weights)
    # 使用自适应优化器
    opt = tf.train.AdamOptimizer(learning_rate=learning_rate)
    # 优化目标， 让loss最小化
    update = opt.apply_gradients(opt.compute_gradients(loss))
    # 模型持久化
    saver = tf.train.Saver(tf.global_variables())
    return encoder_inputs, decoder_inputs, target_weights,outputs, loss, update, saver, learning_rate_decay_op, learning_rate


def train():
    """
    训练过程
    :return:
    """
    train_set = get_train_set()

    with tf.Session() as sess:
        # ckpt = tf.train.get_checkpoint_state('./model/chatbot/')
        # saver = tf.train.import_meta_graph(ckpt.model_checkpoint_path + '.meta')
        # saver.restore(sess, ckpt.model_checkpoint_path)
        encoder_inputs, decoder_inputs, target_weights, outputs, loss, update, saver, learning_rate_decay_op, learning_rate = get_model()
        # 全部变量初始化
        sess.run(tf.compat.v1.global_variables_initializer())
        # 训练多次迭代， 每隔100次打印一次loss, 可以看情况直接ctrl + c 停止
        previous_losses = []
        with tf.device('/gpu:1'):
            for step in range(500):
                sample_encoder_inputs, sample_decoder_inputs, sample_target_weights = get_samples(train_set, 1000)
                input_feed = {}
                for l in range(input_seq_len):
                    input_feed[encoder_inputs[l].name] = sample_encoder_inputs[l]
                for l in range(output_seq_len):
                    input_feed[decoder_inputs[l].name] = sample_decoder_inputs[l]
                    input_feed[target_weights[l].name] = sample_target_weights[l]
                input_feed[decoder_inputs[output_seq_len].name] = np.zeros([len(sample_decoder_inputs[0])], dtype=np.int32)
                [loss_ret, _] = sess.run([loss, update], input_feed)
                if step % 100 == 0:
                    print('step=', step, 'loss=', loss_ret, 'learning_rate=', learning_rate.eval())
                    if len(previous_losses) > 5 and loss_ret > max(previous_losses[-5:]):
                        sess.run(learning_rate_decay_op)
                    previous_losses.append(loss_ret)
                    # 模型持久化
                    saver.save(sess, output_dir)


def train1():
    """
    训练过程
    :return:
    """
    train_set = get_train_set()

    with tf.Session() as sess:
        encoder_inputs, decoder_inputs, target_weights, outputs, loss, update, saver, learning_rate_decay_op, learning_rate = get_model()
        saver = tf.train.import_meta_graph('./model/chatbot/demo.meta')
        saver.restore(sess, tf.train.latest_checkpoint(r'./model/chatbot/'))
        # graph = tf.get_default_graph()


        # 全部变量初始化
        # sess.run(tf.compat.v1.global_variables_initializer())
        # 训练多次迭代， 每隔100次打印一次loss, 可以看情况直接ctrl + c 停止
        previous_losses = []
        with tf.device('/gpu:1'):
            for step in range(20000):
                sample_encoder_inputs, sample_decoder_inputs, sample_target_weights = get_samples(train_set, 1000)
                input_feed = {}
                for l in range(input_seq_len):
                    input_feed[encoder_inputs[l].name] = sample_encoder_inputs[l]
                for l in range(output_seq_len):
                    input_feed[decoder_inputs[l].name] = sample_decoder_inputs[l]
                    input_feed[target_weights[l].name] = sample_target_weights[l]
                input_feed[decoder_inputs[output_seq_len].name] = np.zeros([len(sample_decoder_inputs[0])], dtype=np.int32)
                [loss_ret, _] = sess.run([loss, update], input_feed)
                if step % 100 == 0:
                    print('step=', step, 'loss=', loss_ret, 'learning_rate=', learning_rate.eval())
                    if len(previous_losses) > 5 and loss_ret > max(previous_losses[-5:]):
                        sess.run(learning_rate_decay_op)
                    previous_losses.append(loss_ret)
                    # 模型持久化
                    saver.save(sess, output_dir)

def predict():
    """
    预测过程
    :return:
    """
    with tf.Session() as sess:
        # sess = tfdbg.LocalCLIDebugWrapperSession(sess)
        # sess.add_tensor_filter("other_debug", tfdbg.has_inf_or_nan)
        encoder_inputs, decoder_inputs, target_weights, outputs, loss, update,saver, learning_rate_decay_op, learning_rate = get_model(feed_previous=True)
        saver.restore(sess, output_dir)
        sys.stdout.write(">")
        sys.stdout.flush()
        input_seq = input()
        while input_seq:
            input_seq = input_seq.strip()
            input_id_list = get_id_list_from(input_seq)
            if len(input_id_list):
                sample_encoder_inputs, sample_decoder_inputs, sample_target_weights = seq_to_encoder(" ".join([str(v) for v in input_id_list]))
                input_feed = {}
                for l in range(input_seq_len):
                    input_feed[encoder_inputs[l].name] = sample_encoder_inputs[l]
                for l in range(output_seq_len):
                    input_feed[decoder_inputs[l].name] = sample_decoder_inputs[l]
                    input_feed[target_weights[l].name] = sample_target_weights[l]
                input_feed[decoder_inputs[output_seq_len].name] = np.zeros([2], dtype=np.int32)

                # 预测输出
                outputs_seq = sess.run(outputs, input_feed)
                # 因为输出数据每一个是num_decoder_symbols维的， 因此，找到最大的那个就是预测的id,就是这里的argmax函数的功能
                outputs_seq = [int(np.argmax(logit[0], axis=0)) for logit in outputs_seq]
                # 如果是结尾符， 那么后面的语句就不输出了
                if EOS_ID in outputs_seq:
                    outputs_seq = outputs_seq[:outputs_seq.index(EOS_ID)]
                outputs_seq = [wordToken.id2word(v) for v in outputs_seq]
                print("/".join(outputs_seq))
            else:
                print("WARN: 词汇不在服务区")
            sys.stdout.write(">")
            sys.stdout.flush()
            input_seq = input()



if __name__ == '__main__':
    tf.reset_default_graph()
    train1()
    # tf.reset_default_graph()
    # predict()




