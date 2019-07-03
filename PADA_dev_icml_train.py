import argparse
import os
import os.path as osp

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import network
import loss
import pre_process as prep
import torch.utils.data as util_data
import lr_schedule
import data_list
from data_list import ImageList
from torch.autograd import Variable
import random

import dev_icml
import seperate_data as sep


optim_dict = {"SGD": optim.SGD}

def image_classification_predict(loader, model, test_10crop=True, gpu=True, softmax_param=1.0):
    start_test = True
    if test_10crop:
        iter_test = [iter(loader['test'+str(i)]) for i in range(10)]
        for i in range(len(loader['test0'])):
            data = [iter_test[j].next() for j in range(10)]
            inputs = [data[j][0] for j in range(10)]
            labels = data[0][1]
            if gpu:
                for j in range(10):
                    inputs[j] = Variable(inputs[j].cuda())
                labels = Variable(labels.cuda())
            else:
                for j in range(10):
                    inputs[j] = Variable(inputs[j])
                labels = Variable(labels)
            outputs = []
            for j in range(10):
                _, predict_out = model(inputs[j])
                outputs.append(nn.Softmax(dim=1)(softmax_param * predict_out))
            softmax_outputs = sum(outputs)
            if start_test:
                all_softmax_output = softmax_outputs.data.cpu().float()
                start_test = False
            else:
                all_softmax_output = torch.cat((all_softmax_output, softmax_outputs.data.cpu().float()), 0)
    else:
        iter_val = iter(loader["test"])
        for i in range(len(loader['test'])):
            data = iter_val.next()
            inputs = data[0]
            if gpu:
                inputs = Variable(inputs.cuda())
            else:
                inputs = Variable(inputs)
            _, outputs = model(inputs)
            softmax_outputs = nn.Softmax(dim=1)(softmax_param * outputs)
            if start_test:
                all_softmax_output = softmax_outputs.data.cpu().float()
                start_test = False
            else:
                all_softmax_output = torch.cat((all_softmax_output, softmax_outputs.data.cpu().float()), 0)
    return all_softmax_output

def image_classification_test(loader, model, test_10crop=True, gpu=True, iter_num=-1):
    # 与之前的区别 在于 这里在前面的基础上 又见上了对label的predict 然后通过label计算了 accuracy
    start_test = True
    if test_10crop:
        iter_test = [iter(loader['test'+str(i)]) for i in range(10)]
        for i in range(len(loader['test0'])):
            data = [iter_test[j].next() for j in range(10)]
            inputs = [data[j][0] for j in range(10)]
            labels = data[0][1]
            if gpu:
                for j in range(10):
                    inputs[j] = Variable(inputs[j].cuda())
                labels = Variable(labels.cuda())
            else:
                for j in range(10):
                    inputs[j] = Variable(inputs[j])
                labels = Variable(labels)
            outputs = []
            for j in range(10):
                _, predict_out = model(inputs[j])
                outputs.append(nn.Softmax(dim=1)(predict_out))
            outputs = sum(outputs)
            if start_test:
                all_output = outputs.data.float()
                all_label = labels.data.float()
                start_test = False
            else:
                all_output = torch.cat((all_output, outputs.data.float()), 0)
                all_label = torch.cat((all_label, labels.data.float()), 0)
    else:
        iter_test = iter(loader["test"])
        for i in range(len(loader['test'])):
            data = iter_test.next()
            inputs = data[0]
            labels = data[1]
            if gpu:
                inputs = Variable(inputs.cuda())
                labels = Variable(labels.cuda())
            else:
                inputs = Variable(inputs)
                labels = Variable(labels)
            _, outputs = model(inputs)
            if start_test:
                all_output = outputs.data.float()
                all_label = labels.data.float()
                start_test = False
            else:
                all_output = torch.cat((all_output, outputs.data.float()), 0)
                all_label = torch.cat((all_label, labels.data.float()), 0)
    _, predict = torch.max(all_output, 1)
    accuracy = torch.sum(torch.squeeze(predict).float() == all_label).item() / float(all_label.size()[0])
    return accuracy


def train(config):
    ## set pre-process
    prep_dict = {}
    prep_config = config["prep"]
    prep_dict["source"] = prep.image_train( \
                            resize_size=prep_config["resize_size"], \
                            crop_size=prep_config["crop_size"])
    prep_dict["target"] = prep.image_train( \
                            resize_size=prep_config["resize_size"], \
                            crop_size=prep_config["crop_size"])
    if prep_config["test_10crop"]:
        prep_dict["test"] = prep.image_test_10crop( \
                            resize_size=prep_config["resize_size"], \
                            crop_size=prep_config["crop_size"])
    else:
        prep_dict["test"] = prep.image_test( \
                            resize_size=prep_config["resize_size"], \
                            crop_size=prep_config["crop_size"])

    ## set loss
    class_criterion = nn.CrossEntropyLoss()
    transfer_criterion = loss.PADA
    loss_params = config["loss"]

    ## prepare data
    dsets = {}
    dset_loaders = {}
    data_config = config["data"]

    # seperate the source and validation set
    cls_source_list, cls_validation_list = sep.split_set(data_config["source"]["list_path"],
                                                         config["network"]["params"]["class_num"])
    source_list = sep.dimension_rd(cls_source_list)

    dsets["source"] = ImageList(source_list, \
                                transform=prep_dict["source"])
    dset_loaders["source"] = util_data.DataLoader(dsets["source"], \
            batch_size=data_config["source"]["batch_size"], \
            shuffle=True, num_workers=4)
    dsets["target"] = ImageList(open(data_config["target"]["list_path"]).readlines(), \
                                transform=prep_dict["target"])
    dset_loaders["target"] = util_data.DataLoader(dsets["target"], \
            batch_size=data_config["target"]["batch_size"], \
            shuffle=True, num_workers=4)

    if prep_config["test_10crop"]:
        for i in range(10):
            dsets["test"+str(i)] = ImageList(open(data_config["test"]["list_path"]).readlines(), \
                                transform=prep_dict["test"]["val"+str(i)])
            dset_loaders["test"+str(i)] = util_data.DataLoader(dsets["test"+str(i)], \
                                batch_size=data_config["test"]["batch_size"], \
                                shuffle=False, num_workers=4)

            dsets["target"+str(i)] = ImageList(open(data_config["target"]["list_path"]).readlines(), \
                                transform=prep_dict["test"]["val"+str(i)])
            dset_loaders["target"+str(i)] = util_data.DataLoader(dsets["target"+str(i)], \
                                batch_size=data_config["test"]["batch_size"], \
                                shuffle=False, num_workers=4)
    else:
        dsets["test"] = ImageList(open(data_config["test"]["list_path"]).readlines(), \
                                transform=prep_dict["test"])
        dset_loaders["test"] = util_data.DataLoader(dsets["test"], \
                                batch_size=data_config["test"]["batch_size"], \
                                shuffle=False, num_workers=4)

        dsets["target_test"] = ImageList(open(data_config["target"]["list_path"]).readlines(), \
                                transform=prep_dict["test"])
        dset_loaders["target_test"] = MyDataLoader(dsets["target_test"], \
                                batch_size=data_config["test"]["batch_size"], \
                                shuffle=False, num_workers=4)

    class_num = config["network"]["params"]["class_num"]

    ## set base network
    net_config = config["network"]
    base_network = net_config["name"](**net_config["params"])


    use_gpu = torch.cuda.is_available()
    if use_gpu:
        base_network = base_network.cuda()

    ## collect parameters
    if net_config["params"]["new_cls"]:
        if net_config["params"]["use_bottleneck"]:
            parameter_list = [{"params":base_network.feature_layers.parameters(), "lr":1}, \
                            {"params":base_network.bottleneck.parameters(), "lr":10}, \
                            {"params":base_network.fc.parameters(), "lr":10}]
        else:
            parameter_list = [{"params":base_network.feature_layers.parameters(), "lr":1}, \
                            {"params":base_network.fc.parameters(), "lr":10}]
    else:
        parameter_list = [{"params":base_network.parameters(), "lr":1}]

    ## add additional network for some methods
    class_weight = torch.from_numpy(np.array([1.0] * class_num))
    if use_gpu:
        class_weight = class_weight.cuda()
    ad_net = network.AdversarialNetwork(base_network.output_num())
    gradient_reverse_layer = network.AdversarialLayer(high_value=config["high"])
    if use_gpu:
        ad_net = ad_net.cuda()
    parameter_list.append({"params":ad_net.parameters(), "lr":10})

    ## set optimizer
    optimizer_config = config["optimizer"]
    optimizer = optim_dict[optimizer_config["type"]](parameter_list, \
                    **(optimizer_config["optim_params"]))
    param_lr = []
    for param_group in optimizer.param_groups:
        param_lr.append(param_group["lr"])
    schedule_param = optimizer_config["lr_param"]
    lr_scheduler = lr_schedule.schedule_dict[optimizer_config["lr_type"]]


    ## train
    len_train_source = len(dset_loaders["source"]) - 1
    len_train_target = len(dset_loaders["target"]) - 1
    transfer_loss_value = classifier_loss_value = total_loss_value = 0.0
    best_acc = 0.0
    best_model = 0
    for i in range(config["num_iterations"]):
        if i % config["test_interval"] == 0:
            base_network.train(False)
            temp_acc = image_classification_test(dset_loaders, \
                base_network, test_10crop=prep_config["test_10crop"], \
                gpu=use_gpu)
            temp_model = nn.Sequential(base_network)
            if temp_acc > best_acc:
                best_acc = temp_acc
                best_model = temp_model
            log_str = "iter: {:05d}, precision: {:.5f}".format(i, temp_acc)
            config["out_file"].write(log_str)
            config["out_file"].flush()
            print(log_str)
        if i % config["snapshot_interval"] == 0:
            torch.save(nn.Sequential(base_network), osp.join(config["output_path"], \
                "iter_{:05d}_model.pth.tar".format(i)))


        # if i % loss_params["update_iter"] == loss_params["update_iter"] - 1:
        #     base_network.train(False)
        #     target_fc8_out = image_classification_predict(dset_loaders, base_network, softmax_param=config["softmax_param"])
        #     class_weight = torch.mean(target_fc8_out, 0)
        #     class_weight = (class_weight / torch.mean(class_weight)).cuda().view(-1)
        #     class_criterion = nn.CrossEntropyLoss(weight = class_weight)


        ## train one iter
        base_network.train(True)
        optimizer = lr_scheduler(param_lr, optimizer, i, **schedule_param)
        optimizer.zero_grad()
        if i % len_train_source == 0:
            iter_source = iter(dset_loaders["source"])
        if i % len_train_target == 0:
            iter_target = iter(dset_loaders["target"])
        inputs_source, labels_source = iter_source.next()
        inputs_target, labels_target = iter_target.next()
        if use_gpu:
            inputs_source, inputs_target, labels_source = \
                Variable(inputs_source).cuda(), Variable(inputs_target).cuda(), \
                Variable(labels_source).cuda()
        else:
            inputs_source, inputs_target, labels_source = Variable(inputs_source), \
                Variable(inputs_target), Variable(labels_source)

        inputs = torch.cat((inputs_source, inputs_target), dim=0)
        features, outputs = base_network(inputs)

        #
        # if i % 100 == 0:
        #     check = dev.get_label_list(open(data_config["source"]["list_path"]).readlines(),
        #                                base_network,
        #                                prep_config["resize_size"],
        #                                prep_config["crop_size"],
        #                                data_config["target"]["batch_size"],
        #                                use_gpu)
        #     f = open("Class_result.txt", "a+")
        #     f.close()
        #     for cls in range(class_num):
        #         count = 0
        #         for j in check:
        #             if int(j.split(" ")[1].replace("\n", "")) == cls:
        #                 count = count + 1
        #         f = open("Source_result.txt", "a+")
        #         f.write("Source_Class: " + str(cls) + "\n" + "Number of images: " + str(count) + "\n")
        #         f.close()
        #
        #     check = dev.get_label_list(open(data_config["target"]["list_path"]).readlines(),
        #                                base_network,
        #                                prep_config["resize_size"],
        #                                prep_config["crop_size"],
        #                                data_config["target"]["batch_size"],
        #                                use_gpu)
        #     f = open("Class_result.txt", "a+")
        #     f.write("Iteration: " + str(i) + "\n")
        #     f.close()
        #     for cls in range(class_num):
        #         count = 0
        #         for j in check:
        #             if int(j.split(" ")[1].replace("\n", "")) == cls:
        #                 count = count + 1
        #         f = open("Class_result.txt", "a+")
        #         f.write("Target_Class: " + str(cls) + "\n" + "Number of images: " + str(count) + "\n")
        #         f.close()


        #
        # print("Training test:")
        # print(features)
        # print(features.shape)
        # print(outputs)
        # print(outputs.shape)

        softmax_out = nn.Softmax(dim=1)(outputs).detach()
        ad_net.train(True)
        weight_ad = torch.ones(inputs.size(0))
        # label_numpy = labels_source.data.cpu().numpy()
        # for j in range(int(inputs.size(0) / 2)):
        #     weight_ad[j] = class_weight[int(label_numpy[j])]
        # weight_ad = weight_ad / torch.max(weight_ad[0:int(inputs.size(0)/2)])
        # for j in range(int(inputs.size(0) / 2), inputs.size(0)):
        #     weight_ad[j] = 1.0
        transfer_loss = transfer_criterion(features, ad_net, gradient_reverse_layer, \
                                           weight_ad, use_gpu)

        classifier_loss = class_criterion(outputs.narrow(0, 0, int(inputs.size(0) / 2)), labels_source)

        total_loss = loss_params["trade_off"] * transfer_loss + classifier_loss
        total_loss.backward()
        optimizer.step()


    # # 试着直接从function中那feature，不使用 loader再load一遍
    #
    #
    #
    #
    #
    # # del dset_loaders
    # # def cross_validation_loss(feature_network_name, predict_network_name, src_list, target_path, val_list, class_num,
    # #                           resize_size, crop_size, batch_size, use_gpu):
    #
    cv_loss = dev_icml.cross_validation_loss(base_network, base_network, source_list,
                                             data_config["target"]["list_path"], cls_validation_list,
                                             class_num, prep_config["resize_size"],
                                             prep_config["crop_size"], data_config["target"]["batch_size"],
                                             use_gpu)
    print(cv_loss)
    # src_list = source_list
    # target_path = data_config["target"]["list_path"]
    # val_list = cls_validation_list
    # resize_size = prep_config["resize_size"]
    # crop_size = prep_config["crop_size"]
    # batch_size = data_config["target"]["batch_size"]
    # val_list = sep.dimension_rd(val_list)
    #
    # tar_list = open(target_path).readlines()
    # cross_val_loss = 0
    #
    # prep_dict = prep.image_train(resize_size=resize_size, crop_size=crop_size)
    # # load different class's image
    #
    # dsets_src = ImageList(src_list, transform=prep_dict)
    # dset_loaders_src = util_data.DataLoader(dsets_src, batch_size=batch_size, shuffle=True, num_workers=4)
    #
    # dsets_val = ImageList(val_list, transform=prep_dict)
    # dset_loaders_val = util_data.DataLoader(dsets_val, batch_size=batch_size, shuffle=True, num_workers=4)
    #
    # dsets_tar = ImageList(tar_list, transform=prep_dict)
    # dset_loaders_tar = util_data.DataLoader(dsets_tar, batch_size=batch_size, shuffle=True, num_workers=4)
    #
    # # prepare source feature
    # iter_src = iter(dset_loaders_src)
    # src_input, src_labels = iter_src.next()
    # if use_gpu:
    #     src_input, src_labels = Variable(src_input).cuda(), Variable(src_labels).cuda()
    # else:
    #     src_input, src_labels = Variable(src_input), Variable(src_labels)
    # src_feature, _ = base_network(src_input)
    # for _ in range(len(src_list) - 1):
    #     src_input, src_labels = iter_src.next()
    #     if use_gpu:
    #         src_input, src_labels = Variable(src_input).cuda(), Variable(src_labels).cuda()
    #     else:
    #         src_input, src_labels = Variable(src_input), Variable(src_labels)
    #     src_feature_new, _ = base_network(src_input)
    #     src_feature = torch.cat((src_feature, src_feature_new), 0)
    #
    # # prepare target feature
    # iter_tar = iter(dset_loaders_tar)
    # tar_input, _ = iter_tar.next()
    # if use_gpu:
    #     tar_input, _ = Variable(tar_input).cuda(), Variable(_).cuda()
    # else:
    #     src_input, _ = Variable(tar_input), Variable(_)
    # tar_feature, _ = base_network(tar_input)
    # for _ in range(len(tar_list) - 1):
    #     tar_input, _ = iter_tar.next()
    #     if use_gpu:
    #         tar_input, _ = Variable(tar_input).cuda(), Variable(_).cuda()
    #     else:
    #         src_input, _ = Variable(tar_input), Variable(_)
    #     tar_feature_new, _ = base_network(tar_input)
    #     tar_feature = torch.cat((tar_feature, tar_feature_new), 0)
    #
    # # prepare validation feature and predicted label for validation
    # iter_val = iter(dset_loaders_val)
    # val_input, val_labels = iter_val.next()
    # if use_gpu:
    #     val_input, val_labels = Variable(val_input).cuda(), Variable(val_labels).cuda()
    # else:
    #     val_input, val_labels = Variable(val_input), Variable(val_labels)
    # val_feature, _ = base_network(val_input)
    # pred_label = base_network(val_input)[1]
    # w = pred_label[0].shape[0]
    # error = np.zeros(1)
    #
    # print(val_labels)
    # print(len(val_labels))
    #
    # error[0] = dev_icml.predict_loss(val_labels[0].item(), pred_label[0].reshape(1, w)).item()
    # error = error.reshape(1, 1)
    #
    # for num_image in range(1, len(pred_label)):
    #     single_pred_label = pred_label[num_image]
    #     w = single_pred_label.shape[0]
    #     single_val_label = val_labels[num_image]
    #     error = np.append(error, [[dev_icml.predict_loss(single_val_label.item(), single_pred_label.reshape(1, w)).item()]],
    #                       axis=0)
    #
    # for _ in range(len(iter_val) - 1):
    #     val_input, val_labels = iter_val.next()
    #     if use_gpu:
    #         val_input, val_labels = Variable(val_input).cuda(), Variable(val_labels).cuda()
    #     else:
    #         val_input, val_labels = Variable(val_input), Variable(val_labels)
    #     val_feature_new, _ = base_network(val_input)
    #     val_feature = torch.cat((val_feature, val_feature_new), 0)
    #     _, pred_label = base_network(val_input)
    #     for num_image in range(len(pred_label)):
    #         single_pred_label = pred_label[num_image]
    #         w = single_pred_label.shape[0]
    #         single_val_label = val_labels[num_image]
    #         error = np.append(error, [[dev_icml.predict_loss(single_val_label.item(), single_pred_label.reshape(1, w)).item()]],
    #                           axis=0)
    #
    # # print('The class is {}\n'.format(val_input))
    # weight = dev_icml.get_weight(src_feature, tar_feature, val_feature)
    # cross_val_loss = cross_val_loss + dev_icml.get_dev_risk(weight, error)
    #
    # # added cross validation code
    # cv_loss = cross_val_loss
    # print(cv_loss)
    # #
    #
    # return best_acc

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Transfer Learning')
    parser.add_argument('--gpu_id', type=str, nargs='?', default='0', help="device id to run")
    parser.add_argument('--net', type=str, default='ResNet50', help="Options: ResNet18,34,50,101,152; AlexNet")
    parser.add_argument('--dset', type=str, default='office', help="The dataset or source dataset used")
    parser.add_argument('--s_dset_path', type=str, default='../data/office-home/chn_Art.txt', help="The source dataset path list")
    parser.add_argument('--t_dset_path', type=str, default='../data/office-home/chn_Art_shared.txt', help="The target dataset path list")
    parser.add_argument('--test_interval', type=int, default=500, help="interval of two continuous test phase")
    parser.add_argument('--num_iterations', type=int, default=500, help="number of iterations")
    parser.add_argument('--snapshot_interval', type=int, default=5000, help="interval of two continuous output model")
    parser.add_argument('--output_dir', type=str, default='san', help="output directory of our model (in ../snapshot directory)")
    args = parser.parse_args()
    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu_id

    # train config
    config = {}
    config["softmax_param"] = 1.0
    config["high"] = 1.0
    config["num_iterations"] = args.num_iterations
    config["test_interval"] = args.test_interval
    config["snapshot_interval"] = args.snapshot_interval
    config["output_for_test"] = True
    config["output_path"] = "../snapshot/" + args.output_dir
    if not osp.exists(config["output_path"]):
        os.mkdir(config["output_path"])
    config["out_file"] = open(osp.join(config["output_path"], "log.txt"), "w")
    if not osp.exists(config["output_path"]):
        os.mkdir(config["output_path"])

    config["prep"] = {"test_10crop":True, "resize_size":256, "crop_size":224}
    config["loss"] = {"trade_off":1.0, "update_iter":500}
    if "AlexNet" in args.net:
        config["network"] = {"name":network.AlexNetFc, \
            "params":{"use_bottleneck":True, "bottleneck_dim":256, "new_cls":True} }
    elif "ResNet" in args.net:
        config["network"] = {"name":network.ResNetFc, \
            "params":{"resnet_name":args.net, "use_bottleneck":True, "bottleneck_dim":256, "new_cls":True} }
    elif "VGG" in args.net:
        config["network"] = {"name":network.VGGFc, \
            "params":{"vgg_name":args.net, "use_bottleneck":True, "bottleneck_dim":256, "new_cls":True} }
    config["optimizer"] = {"type":"SGD", "optim_params":{"lr":1.0, "momentum":0.9, \
                           "weight_decay":0.0005, "nesterov":True}, "lr_type":"inv", \
                           "lr_param":{"init_lr":0.001, "gamma":0.001, "power":0.75} }

    config["dataset"] = args.dset
    if config["dataset"] == "office":
        # config["data"] = {"source":{"list_path":args.s_dset_path, "batch_size":36}, \
        #                   "target":{"list_path":args.t_dset_path, "batch_size":36}, \
        #                   "test":{"list_path":args.t_dset_path, "batch_size":4}}
        config["data"] = {"source": {"list_path": args.s_dset_path, "batch_size": 13}, \
                          "target": {"list_path": args.t_dset_path, "batch_size": 13}, \
                          "test": {"list_path": args.t_dset_path, "batch_size": 4}}
        if "amazon" in config["data"]["test"]["list_path"]:
            config["optimizer"]["lr_param"]["init_lr"] = 0.0003
        else:
            config["optimizer"]["lr_param"]["init_lr"] = 0.001
        config["loss"]["update_iter"] = 500
        config["network"]["params"]["class_num"] = 31
    elif config["dataset"] == "office-home":
        config["data"] = {"source":{"list_path":args.s_dset_path, "batch_size":36}, \
                          "target":{"list_path":args.t_dset_path, "batch_size":36}, \
                          "test":{"list_path":args.t_dset_path, "batch_size":4}}
        if "Real_World" in args.s_dset_path and "Art" in args.t_dset_path:
            config["softmax_param"] = 1.0
            config["optimizer"]["lr_param"]["init_lr"] = 0.0003
        elif "Real_World" in args.s_dset_path:
            config["softmax_param"] = 10.0
            config["optimizer"]["lr_param"]["init_lr"] = 0.001
        elif "Art" in args.s_dset_path:
            config["optimizer"]["lr_param"]["init_lr"] = 0.0003
            config["high"] = 0.5
            config["softmax_param"] = 10.0
            if "Real_World" in args.t_dset_path:
                config["high"] = 0.25
        elif "Product" in args.s_dset_path:
            config["optimizer"]["lr_param"]["init_lr"] = 0.0003
            config["high"] = 0.5
            config["softmax_param"] = 10.0
            if "Real_World" in args.t_dset_path:
                config["high"] = 0.3
        else:
            config["optimizer"]["lr_param"]["init_lr"] = 0.0003
            if "Real_World" in args.t_dset_path:
                config["high"] = 0.5
                config["softmax_param"] = 10.0
                config["loss"]["update_iter"] = 1000
            else:
                config["high"] = 0.5
                config["softmax_param"] = 10.0
                config["loss"]["update_iter"] = 500
        config["network"]["params"]["class_num"] = 65
    elif config["dataset"] == "imagenet":
        config["data"] = {"source":{"list_path":args.s_dset_path, "batch_size":36}, \
                          "target":{"list_path":args.t_dset_path, "batch_size":36}, \
                          "test":{"list_path":args.t_dset_path, "batch_size":4}}
        config["optimizer"]["lr_param"]["init_lr"] = 0.0003
        config["loss"]["update_iter"] = 2000
        config["network"]["params"]["use_bottleneck"] = False
        config["network"]["params"]["new_cls"] = False
        config["network"]["params"]["class_num"] = 1000
    elif config["dataset"] == "caltech":
        config["data"] = {"source":{"list_path":args.s_dset_path, "batch_size":36}, \
                          "target":{"list_path":args.t_dset_path, "batch_size":36}, \
                          "test":{"list_path":args.t_dset_path, "batch_size":4}}
        config["optimizer"]["lr_param"]["init_lr"] = 0.001
        config["loss"]["update_iter"] = 500
        config["network"]["params"]["class_num"] = 256
    elif config["dataset"] == "visda":
        config["data"] = {"source":{"list_path":args.s_dset_path, "batch_size": 36},\
                          "target":{"list_path":args.t_dset_path, "batch_size":36},\
                          "test":{"list_path":args.t_dset_path, "batch_size":4}}
        config["optimizer"]["lr_param"]["init_lr"] = 0.001
        config["loss"]["update_iter"] = 500
        config["network"]["params"]["class_num"] = 12
    train(config)
