'''Train CIFAR100 with PyTorch.'''
from __future__ import print_function

import argparse
import csv
import os

import numpy as np
import torch.backends.cudnn as cudnn
import torchvision
import torchvision.transforms as transforms

import mix_aug
# import Gau_noise
import mixup as mp
import mixup_v2 as mp_v2
import models
from models import *
from utils import progress_bar, top_accuracy, calib_err

parser = argparse.ArgumentParser(description='PyTorch CIFAR10 Training')
parser.add_argument('--lr', default=0.1, type=float, help='learning rate')
parser.add_argument('--resume', '-r', action='store_true',
                    help='resume from checkpoint')
parser.add_argument('--name', default='0', type=str, help='name of run')
parser.add_argument('--seed', default=0, type=int, help='random seed')
parser.add_argument('--model', default="ResNet18", type=str,
                    help='model type (default: ResNet18)')  # WideResNet
parser.add_argument('--alpha', default=1., type=float,
                    help='mixup interpolation coefficient (default: 1)')
parser.add_argument('--mixup', type=str, default='ori', help='mixup method')
parser.add_argument('--epoch', default=200, type=int,
                    help='total epochs to run')
parser.add_argument('--beta', default=0, type=float,
                    help='hyperparameter beta')
parser.add_argument('--cutmix_prob', default=0, type=float,
                    help='cutmix probability')
parser.add_argument('--momentum', default=0.9, type=float, metavar='M',
                    help='momentum')

parser.add_argument('--weight-decay', '--wd', default=1e-4, type=float,
                    metavar='W', help='weight decay (default: 1e-4)')
parser.add_argument('--severity', type=int, default=3)
parser.add_argument('--num_classes', type=int, default=100)
args = parser.parse_args()

device = 'cuda' if torch.cuda.is_available() else 'cpu'
best_acc = 0  # best test accuracy
start_epoch = 0  # start from epoch 0 or last checkpoint epoch,


def rand_bbox(size, lam):
    W = size[2]
    H = size[3]
    cut_rat = np.sqrt(1. - lam)
    cut_w = np.int(W * cut_rat)
    cut_h = np.int(H * cut_rat)

    # uniform
    cx = np.random.randint(W)
    cy = np.random.randint(H)

    bbx1 = np.clip(cx - cut_w // 2, 0, W)
    bby1 = np.clip(cy - cut_h // 2, 0, H)
    bbx2 = np.clip(cx + cut_w // 2, 0, W)
    bby2 = np.clip(cy + cut_h // 2, 0, H)

    return bbx1, bby1, bbx2, bby2

# Data
print('==> Preparing data..')
transform_train = transforms.Compose([
    transforms.RandomCrop(32, padding=4),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
])

if args.mixup=="AugMix":
    transform_train = transforms.Compose([
        transforms.RandomCrop(32, padding=4),
        transforms.RandomHorizontalFlip(),
    ])

transform_test = transforms.Compose([
    # Gau_noise.AddGaussianNoise(0.0, 8.0, 1.0),
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
])
preprocess = transform_test


trainset = torchvision.datasets.CIFAR100(
    root='./data', train=True, download=True, transform=transform_train)
if args.mixup == 'AugMix':
    trainset = mix_aug.AugMixDataset(trainset, preprocess)
trainloader = torch.utils.data.DataLoader(
    trainset, batch_size=128, shuffle=True, num_workers=2)

testset = torchvision.datasets.CIFAR100(
    root='./data', train=False, download=True, transform=transform_test)
testloader = torch.utils.data.DataLoader(
    testset, batch_size=100, shuffle=False, num_workers=2)
# classes = ('plane', 'car', 'bird', 'cat', 'deer',
#            'dog', 'frog', 'horse', 'ship', 'truck')

# Model
print('==> Building model..')
# net = VGG('VGG19')
# net = ResNet18()
# net = WideResNet(28, 10, 0.3)
# net = PreActResNet18()
# net = GoogLeNet()
# net = DenseNet121()
# net = ResNeXt29_2x64d()
# net = MobileNet()
# net = MobileNetV2()
# net = DPN92()
# net = ShuffleNetG2()
# net = SENet18()
# net = ShuffleNetV2(1)
# net = EfficientNetB0()
# net = RegNetX_200MF()
# net = SimpleDLA()
# net = net.to(device)
# if device == 'cuda':
#     net = torch.nn.DataParallel(net)
#     cudnn.benchmark = True

if args.resume:
    # Load checkpoint.
    print('==> Resuming from checkpoint..')
    assert os.path.isdir('checkpoint'), 'Error: no checkpoint directory found!'
    checkpoint = torch.load('./checkpoint/ckpt.pth' + args.name + '_'
                            + str(args.seed))
    # net.load_state_dict(checkpoint['net'])
    net = checkpoint['net']
    best_acc = checkpoint['acc']
    start_epoch = checkpoint['epoch'] + 1
    rng_state = checkpoint['rng_state']
    torch.set_rng_state(rng_state)
else:
    print('==> Building model..')
    net = models.__dict__[args.model](num_classes=args.num_classes)

net = net.to(device)
if device == 'cuda':
    net = torch.nn.DataParallel(net)
    cudnn.benchmark = True

if not os.path.isdir('results'):
    os.mkdir('results')
logname = ('results/log' +  '_' + args.model + '_epoch200_' + args.mixup + '_'
           + str(args.seed) + '.csv')


criterion = nn.CrossEntropyLoss()
# optimizer = optim.SGD(net.parameters(), lr=args.lr,
#                       momentum=0.9, weight_decay=5e-4)
optimizer = torch.optim.SGD(net.parameters(), args.lr,
                                momentum=args.momentum,
                                weight_decay=args.weight_decay, nesterov=True)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=200)

# Training
def train(epoch):
    print('\nEpoch: %d' % epoch)
    net.train()
    train_loss = 0
    reg_loss = 0
    correct = 0
    total = 0
    top1_acc, top5_acc = 0., 0.
    rms_confidence, rms_correct = [], []
    for batch_idx, (inputs, targets) in enumerate(trainloader):
        inputs, targets = inputs.to(device), targets.to(device)
        if args.mixup == 'ori':
            inputs, targets_a, targets_b, lam = mp.mixup_data(inputs, targets,
                                                              args.alpha)
            inputs = inputs.float()
            outputs = net(inputs)
            loss = mp.mixup_criterion(criterion, outputs, targets_a, targets_b, lam)
            train_loss += loss.item()
            _, predicted = outputs.max(1)
        elif args.mixup == 'AugMix':
            outputs = net(inputs)
            loss = F.cross_entropy(outputs, targets)
            train_loss += loss.item()
            _, predicted = outputs.max(1)

        elif args.mixup == 'cutmix':
            # inputs, lam = cx.mixup_data(inputs, targets, args.alpha)
            # inputs = inputs.float()
            # outputs = net(inputs)
            # loss = cx.mixup_criterion(criterion, outputs, targets, lam)
            # train_loss += loss.item()
            # _, predicted = outputs.max(1)
            r = np.random.rand(1)
            if args.beta > 0 and r < args.cutmix_prob:
                # generate mixed sample
                lam = np.random.beta(args.beta, args.beta)
                rand_index = torch.randperm(inputs.size()[0]).cuda()
                target_a = targets
                target_b = targets[rand_index]
                bbx1, bby1, bbx2, bby2 = rand_bbox(inputs.size(), lam)

                inputs[:, :, bbx1:bbx2, bby1:bby2] = inputs[rand_index, :, bbx1:bbx2, bby1:bby2]
                lam = 1 - ((bbx2 - bbx1) * (bby2 - bby1) / (inputs.size()[-1] * inputs.size()[-2]))

                outputs = net(inputs)
                loss = criterion(outputs, target_a) * lam + criterion(outputs, target_b) * (1. - lam)
            else:
                outputs = net(inputs)
                loss = criterion(outputs, targets)


            train_loss += loss.item()
            _, predicted = outputs.max(1)

        elif args.mixup == 'matrix':
            batch_size = inputs.size()[0]
            one_third = int(batch_size / 3)
            inputs_v2, targets_a_v2, targets_b_v2, lam_v2 = mp_v2.mixup_data(inputs, targets, args.alpha)
            inputs_v1, targets_a_v1, targets_b_v1, lam_v1 = mp.mixup_data(inputs, targets, args.alpha)

            inputs_mix = torch.cat((inputs[:one_third], inputs_v1[one_third:2 * one_third], inputs_v2[2 * one_third:]), 0)
            inputs_mix = inputs_mix.float()
            inputs_v2 = inputs_v2.float()
            inputs_v1 = inputs_v1.float()
            inputs_or = inputs.float()

            outputs_mix = net(inputs_mix)
            outputs_or = outputs_mix[:one_third]

            outputs_v1 = outputs_mix[one_third:2 * one_third]
            outputs_v2 = outputs_mix[2 * one_third:]

            loss_or = criterion(outputs_or, targets[:one_third])
            loss_v1 = mp.mixup_criterion(criterion, outputs_v1, targets_a_v1[one_third:2 * one_third], targets_b_v1[one_third:2 * one_third], lam_v1)
            loss_v2 = mp.mixup_criterion(criterion, outputs_v2, targets_a_v2[2 * one_third:], targets_b_v2[2 * one_third:], lam_v2)

            loss = (loss_v2 + loss_or + loss_v1) / 3
            train_loss += loss.item()
            _, predicted = torch.max(outputs_v2.data, 1)
        else:
            outputs = net(inputs)
            loss = criterion(outputs, targets)
            train_loss += loss.item()
            _, predicted = outputs.max(1)

        # train_loss += loss.item()
        # _, predicted = outputs.max(1)
        total += targets.size(0)
        correct = 0.0
        # correct += predicted.eq(targets).sum().item()
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()




        # progress_bar(batch_idx, len(trainloader), 'Loss: %.3f | Acc: %.3f%% (%d/%d)'
        #              % (train_loss/(batch_idx+1), 100.*correct/total, correct, total))
        top1_acc_item, top5_acc_item = top_accuracy(outputs.detach().cpu(), targets.detach().cpu(), topk=(1, 5))
        top1_acc += top1_acc_item
        top5_acc += top5_acc_item
        rms_confidence.extend(F.softmax(outputs.detach().cpu(), dim=-1).squeeze().tolist())
        rms_correct.extend(predicted.eq(targets).cpu().squeeze().tolist())
        progress_bar(batch_idx, len(trainloader),
                     'Loss: %.3f | Reg: %.5f | Acc: %.3f%% (%d/%d) | Top1 Acc: %.3f | Top5 Acc: %.3f'
                     % (train_loss / (batch_idx + 1), reg_loss / (batch_idx + 1),
                        100. * correct / total, correct, total, 100. * top1_acc_item, 100. * top5_acc_item))
    train_rms = 100 * calib_err(rms_confidence, rms_correct, p='2')
    return (train_loss / batch_idx, reg_loss / batch_idx, 100. * correct / total, 100. * top1_acc / len(trainloader), 100. * top5_acc / len(trainloader), train_rms)

def test(epoch):
    global best_acc
    net.eval()
    test_loss = 0
    correct = 0
    total = 0
    top1_acc, top5_acc = 0., 0.
    rms_confidence, rms_correct = [], []
    with torch.no_grad():
        for batch_idx, (inputs, targets) in enumerate(testloader):
            inputs, targets = inputs.to(device), targets.to(device)
            outputs = net(inputs)
            loss = criterion(outputs, targets)

            test_loss += loss.item()
            _, predicted = outputs.max(1)
            total += targets.size(0)
            correct += predicted.eq(targets).sum().item()

            top1_acc_item, top5_acc_item = top_accuracy(outputs.detach().cpu(), targets.detach().cpu(), topk=(1, 5))
            top1_acc += top1_acc_item
            top5_acc += top5_acc_item
            rms_confidence.extend(F.softmax(outputs.detach().cpu(), dim=-1).squeeze().tolist())
            rms_correct.extend(predicted.eq(targets).cpu().squeeze().tolist())
            # progress_bar(batch_idx, len(testloader), 'Loss: %.3f | Acc: %.3f%% (%d/%d)'
            #              % (test_loss/(batch_idx+1), 100.*correct/total, correct, total))
            progress_bar(batch_idx, len(testloader),
                         'Loss: %.3f | Acc: %.3f%% (%d/%d) | Top1 Acc: %.3f | Top5 Acc: %.3f'
                         % (test_loss / (batch_idx + 1), 100. * correct / total,
                            correct, total, 100. * top1_acc_item, 100. * top5_acc_item))

    # Save checkpoint.
    acc = 100.*correct/total
    if acc > best_acc:
        print('Saving..')
        state = {
            # 'net': net.state_dict(),
            'net': net,
            'acc': acc,
            'epoch': epoch,
        }
        if not os.path.isdir('checkpoint/ResNet18/'):
            os.mkdir('checkpoint/ResNet18/')

        torch.save(state, './checkpoint/ResNet18/ckpt.pth_' + args.model + '_epoch200_' +  args.mixup + '_'
                   + str(args.seed))
        best_acc = acc
    test_rms = 100 * calib_err(rms_confidence, rms_correct, p='2')
    return (test_loss / batch_idx, 100. * correct / total, 100. * top1_acc / len(testloader), 100. * top5_acc / len(testloader), test_rms)

if not os.path.exists(logname):
    with open(logname, 'w') as logfile:
        logwriter = csv.writer(logfile, delimiter=',')
        logwriter.writerow(['epoch', 'train loss', 'reg loss', 'train acc', 'train top1 acc', 'train top5 acc', 'train_rms'
                            'test loss', 'test acc', 'test top1 acc', 'test top5 acc', 'test_rms'])

for epoch in range(start_epoch, args.epoch):
    train_loss, reg_loss, train_acc, train_top1_acc, train_top5_acc, train_rms = train(epoch)
    test_loss, test_acc, test_top1_acc, test_top5_acc, test_rms  = test(epoch)
    with open(logname, 'a') as logfile:
        logwriter = csv.writer(logfile, delimiter=',')
        logwriter.writerow([epoch, train_loss, reg_loss, train_acc, train_top1_acc, train_top5_acc, train_rms, test_loss,
                            test_acc, test_top1_acc, test_top5_acc, test_rms])
        scheduler.step()


