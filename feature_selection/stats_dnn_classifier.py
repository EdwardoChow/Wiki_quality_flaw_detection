# coding='UTF-8'
import re
import pandas as pd
import nltk
import nltk.data
import numpy as np
import tensorflow
import keras
from keras import regularizers
from keras import backend as K
from keras.callbacks import TensorBoard
from keras.engine.topology import Layer
from keras.models import Model, Sequential
from keras.layers import Input, Dense, LSTM, Bidirectional, Flatten, Dropout, Multiply, Permute, concatenate
from keras.utils import np_utils
from keras.optimizers import Adam
from sklearn import preprocessing
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import roc_curve, auc

from keras.callbacks import ReduceLROnPlateau
import matplotlib.pyplot as plt

from evaluation_metrics import  precision, recall, fbeta_score, fmeasure, getAccuracy


def prepare_input(file_num_limit):
    # 仅统计数据部分不需要进行文件内容读取
    # sampled_para_encoded_dir = './encoded_para_sep/'  # encoded_para_sep_sampled
    sampled_para_txt_list = './labels_feature_stats_merged_cleaned20200223.csv'  # plain_txt_name_index_sampled.csv

    # text stats: 13 structure: 10 writing style: 20 readability: 7 edit history: 15

    # para_encoded_txts = os.listdir(sampled_para_encoded_dir)
    sampled_label_data = pd.read_csv(sampled_para_txt_list, encoding='utf-8-sig')
    onehotlabels = sampled_label_data.iloc[:file_num_limit,2:8].values
    stats_features = sampled_label_data.iloc[:file_num_limit,10:50].values

    return onehotlabels, stats_features


def DNN_stats(X_train_stats, y_train, X_val_stats, y_val, learning_rate, adam_decay, batch_size, epochs):
    # stats part
    stats_input = Input(shape=(X_train_stats.shape[1],), name='stats_input')
    x = Dense(128, activation='relu', name='merged_feedforward_1')(stats_input)
    x = Dense(64, activation='relu', name='merged_feedforward_2')(x)
    possibility_outputs = Dense(1, activation='sigmoid', name='label_output', kernel_regularizer=regularizers.l2(0.01))(x)  # softmax  sigmoid
    
    model = Model(inputs=stats_input, outputs=possibility_outputs)  # stats_input
    adam = Adam(lr=learning_rate, decay= adam_decay)
    model.compile(loss='binary_crossentropy', optimizer=adam, metrics=['accuracy', precision, recall, fmeasure])  # categorical_crossentropy  binary_crossentropy
    # print(model.summary())

    history = model.fit(X_train_stats, y_train, batch_size, epochs, validation_data=(X_val_stats, y_val), shuffle=True)  # callbacks=[TensorBoard(log_dir='./tmp/log')]

    return model, history


if __name__ == '__main__':
    # 输入限制，用于分类的文章数量
    file_num_limit = 45614  # total 45614
    paras_limit=20

    # params get through skopt
    params = [[0.001, 20, 100, 0.001],
        [0.004505843837998715, 28, 192, 0.008481257855640259],
        [0.006746128946801155, 28, 127, 0.007760009260829582],
        [0.006874053991760905, 16, 174, 0.00027574149368226876],
        [0.0021918575121550456, 27, 172, 0.004591513699133383],
        [0.008363588765837378, 15, 243, 0.004441114146246544]]

    onehotlabels, stats_features = prepare_input(file_num_limit)

    # stats_features 标准化
    scaler = preprocessing.StandardScaler() #实例化
    scaler = scaler.fit(stats_features)
    stats_features = scaler.transform(stats_features)
    
    # 换算成二分类
    # no_footnotes-0, primary_sources-1, refimprove-2, original_research-3, advert-4, notability-5
    flaw_evaluation = []
    for flaw_index in range(6):
        no_good_flaw_type = flaw_index # finished
        # 找出FA类的索引
        FA_indexs = [index for index in range(len(onehotlabels)) if sum([int(item) for item in onehotlabels[index]]) == 0]
        # 找出二分类另外一类的索引
        not_good_indexs = [index for index in range(len(onehotlabels)) if onehotlabels[index][no_good_flaw_type] > 0]
        binary_classification_indexs = FA_indexs + not_good_indexs
        print('FA count:', len(FA_indexs), 'no good count:', len(not_good_indexs))
        y_train = np.array([onehotlabels[index] for index in binary_classification_indexs])
        X_stats = np.array([stats_features[index] for index in binary_classification_indexs])
        
        # 变成二分类的标签
        y_train = y_train[:,no_good_flaw_type]
        y_train = np.array([[label] for label in y_train])
        ### split data into training set and label set
        # X_train, X_test, y_train, y_test = train_test_split(encoded_contents, onehotlabels, test_size=0.1, random_state=42)
        ### params set choose
        target_param = params[no_good_flaw_type]

        learning_rate = target_param[0]
        epochs = target_param[1]
        batch_size = target_param[2]
        adam_decay = target_param[3]
        ### create the deep learning models
        # 训练模型
        X_train_stats, y_train = X_stats, y_train

        # 引入十折交叉验证
        kfold = StratifiedKFold(n_splits=10, shuffle=True, random_state=7)
        kfold_precision, kfold_recall, kfold_f1_score, kfold_acc, kfold_TNR = [], [], [], [], []
        fold_counter = 0
        for train, test in kfold.split(X_train_stats, y_train):
            print('folder comes to:', fold_counter)
            _precision, _recall, _f1_score, _acc, _TNR = 0, 0, 0, 0, 0
            X_test_stats_kfold, y_test_kfold = X_train_stats[test], y_train[test]
            X_val_stats_kfold, y_val_kfold = X_train_stats[train[-1000:]], y_train[train[-1000:]]
            X_train_stats_kfold, y_train_kfold = X_train_stats[train[:-1000]], y_train[train[:-1000]]

            # 采用后1000条做验证集
            # X_val, y_val = X_train[-1000:], y_train[-1000:]
            # X_train, y_train = X_train[:-1000], y_train[:-1000]
            model, history = DNN_stats(X_train_stats_kfold, y_train_kfold, X_val_stats_kfold, y_val_kfold, learning_rate, adam_decay, batch_size, epochs)
            prediction = model.predict(X_test_stats_kfold)  # {'content_bert_input': X_test_content, 'stats_input': X_test_stats}
            fpr, tpr, thresholds = roc_curve(y_test_kfold, prediction)
            print(type(fpr))
            roc_auc = auc(fpr, tpr)  #auc为Roc曲线下的面积
            fpr = fpr.tolist()
            tpr = tpr.tolist()
            print(str(no_good_flaw_type), '  FPR, TPR: ', fpr, '\n', tpr)
            print('auc:', roc_auc)
            _precision, _recall, _f1_score, _acc, _TNR = getAccuracy(prediction, y_test_kfold)
            print('precision:', _precision, 'recall', _recall, 'f1_score', _f1_score, 'accuracy', _acc, 'TNR', _TNR)
            kfold_precision.append(_precision)
            kfold_recall.append(_recall)
            kfold_f1_score.append(_f1_score)
            kfold_acc.append(_acc)
            kfold_TNR.append(_TNR)
            fold_counter += 1
            # Delete the Keras model with these hyper-parameters from memory.
            del model
    
            # Clear the Keras session, otherwise it will keep adding new
            # models to the same TensorFlow graph each time we create
            # a model with a different set of hyper-parameters.
            K.clear_session()
            tensorflow.reset_default_graph()
        print('10 k average evaluation is:', 'precision:', np.mean(kfold_precision), 'recall', np.mean(kfold_recall), 'f1_score', np.mean(kfold_f1_score), 'accuracy', np.mean(kfold_acc), 'TNR', np.mean(kfold_TNR))

        evaluation_value = str(no_good_flaw_type) + ' 10 k average evaluation is: ' + ' precision: ' + str(np.mean(kfold_precision)) + ' recall ' + str(np.mean(kfold_recall)) + ' f1_score ' + str(np.mean(kfold_f1_score)) + ' accuracy ' + str(np.mean(kfold_acc)) + ' TNR ' + str(np.mean(kfold_TNR))
        flaw_evaluation.append(evaluation_value)

    for item in flaw_evaluation:
        print(item)

