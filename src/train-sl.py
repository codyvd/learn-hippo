import os
import time
import torch
import argparse
import numpy as np
import torch.nn.functional as F
import matplotlib.pyplot as plt
import seaborn as sns

from models import LCALSTM as Agent
from task import SequenceLearning
from models import get_reward, compute_returns, compute_a2c_loss
from analysis import compute_behav_metrics, compute_acc, compute_dk, entropy
from utils.params import P
from utils.utils import to_sqnp
from utils.io import build_log_path, save_ckpt, save_all_params, load_ckpt
from plt_helper import plot_tz_pred_acc
# from sklearn.decomposition.pca import PCA
plt.switch_backend('agg')

sns.set(style='white', palette='colorblind', context='talk')

'''learning to tz with a2c. e.g. cmd:
python -u train-tz.py --exp_name testing --subj_id 0 \
--penalty 4 --n_param 6 --n_hidden 64 --eta .1\
--n_epoch 300 --sup_epoch 50 --train_init_state 0 \
--log_root ../log/
'''

parser = argparse.ArgumentParser()
parser.add_argument('--exp_name', default='test', type=str)
parser.add_argument('--subj_id', default=99, type=int)
parser.add_argument('--penalty', default=4, type=int)
parser.add_argument('--p_rm_ob_enc', default=0, type=float)
parser.add_argument('--p_rm_ob_rcl', default=0, type=float)
parser.add_argument('--n_param', default=6, type=int)
parser.add_argument('--n_branch', default=2, type=int)
parser.add_argument('--n_hidden', default=64, type=int)
parser.add_argument('--lr', default=1e-3, type=float)
parser.add_argument('--eta', default=0.1, type=float)
parser.add_argument('--sup_epoch', default=100, type=int)
parser.add_argument('--n_epoch', default=300, type=int)
parser.add_argument('--n_examples', default=256, type=int)
parser.add_argument('--log_root', default='../log/', type=str)
args = parser.parse_args()
print(args)

# process args
exp_name = args.exp_name
subj_id = args.subj_id
penalty = args.penalty
p_rm_ob_enc = args.p_rm_ob_enc
p_rm_ob_rcl = args.p_rm_ob_rcl
n_param = args.n_param
n_branch = args.n_branch
n_hidden = args.n_hidden
learning_rate = args.lr
eta = args.eta
n_examples = args.n_examples
n_epoch = args.n_epoch
supervised_epoch = args.sup_epoch
log_root = args.log_root

# exp_name = 'rm-only'
# subj_id = 1
# penalty = 2
# supervised_epoch = 100
# n_epoch = 300
# n_examples = 256
# log_root = '../log/'
# n_param = 6
# n_branch = 2
# n_hidden = 64
# learning_rate = 1e-3
# eta = .1
# p_rm_ob_enc = 2/n_param
# p_rm_ob_rcl = 2/n_param
# p_rm_ob_enc = 4/n_param
# p_rm_ob_rcl = 4/n_param
n_rm_fixed = False

np.random.seed(subj_id)
torch.manual_seed(subj_id)

'''init'''
p = P(
    exp_name=exp_name, sup_epoch=supervised_epoch,
    n_param=n_param, n_branch=n_branch,
    penalty=penalty,
    p_rm_ob_enc=p_rm_ob_enc,
    p_rm_ob_rcl=p_rm_ob_rcl,
    n_hidden=n_hidden, lr=learning_rate, eta=eta,
)
# init env
task = SequenceLearning(
    p.env.n_param, p.env.n_branch,
    context_onehot=False,
    context_dim=10,
    append_context=True,
    n_rm_fixed=False,
    p_rm_ob_enc=p_rm_ob_enc,
    p_rm_ob_rcl=p_rm_ob_rcl,
)
# init agent
state_dim = task.x_dim
agent = Agent(
    state_dim, p.net.n_hidden, p.a_dim,
    init_state_trainable=False,
)
optimizer = torch.optim.Adam(agent.parameters(), lr=p.net.lr)
scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
    optimizer, factor=1/2, patience=30, threshold=1e-3, min_lr=1e-8,
    verbose=True
)

# create logging dirs
log_path, log_subpath = build_log_path(subj_id, p, log_root=log_root)
# save experiment params initial weights
save_all_params(log_subpath['data'], p)
save_ckpt(0, log_subpath['ckpts'], agent, optimizer)

# load model
epoch_load = None
# epoch_load = 300
if epoch_load is not None:
    agent, optimizer = load_ckpt(
        epoch_load, log_subpath['ckpts'], agent, optimizer)
    epoch_id = epoch_load-1
else:
    epoch_id = 0

'''task definition'''


def pick_condition(p, rm_only=True, fix_cond=None):
    all_tz_conditions = list(p.env.tz.cond_dict.values())
    p_condition = p.env.tz.p_cond
    if fix_cond is not None:
        return fix_cond
    else:
        if rm_only:
            tz_cond = 'RM'
        else:
            tz_cond = np.random.choice(all_tz_conditions, p=p_condition)
        return tz_cond


def set_encoding_flag(t, enc_times, agent):
    if t in enc_times:
        agent.encoding_on()
    else:
        agent.encoding_off()


def cond_manipulation(tz_cond, t, event_bond, hc_t, agent, n_lures=1):
    '''condition specific manipulation
    such as flushing, insert lure, etc.
    '''
    if t == event_bond:
        agent.retrieval_on()
        if tz_cond == 'DM':
            # RM: has EM, no WM
            hc_t = agent.get_init_states()
            agent.add_simple_lures(n_lures)
        elif tz_cond == 'NM':
            # RM: no WM, EM
            hc_t = agent.get_init_states()
            agent.flush_episodic_memory()
            agent.add_simple_lures(n_lures+1)
        elif tz_cond == 'RM':
            # RM: has WM, EM
            agent.add_simple_lures(n_lures)
        else:
            raise ValueError('unrecog tz condition')
    return hc_t


# def append_prev_info(x_it_, a_prev, r_prev):
#     a_prev = a_prev.type(torch.FloatTensor).view(1)
#     r_prev = r_prev.type(torch.FloatTensor).view(1)
#     # y_prev = y_prev.type(torch.FloatTensor)
#     x_it = torch.cat([x_it_, a_prev, r_prev])
#     return x_it


log_freq = 10
Log_loss_critic = np.zeros(n_epoch,)
Log_loss_actor = np.zeros(n_epoch,)
Log_loss_sup = np.zeros(n_epoch,)
Log_return = np.zeros(n_epoch,)
Log_pi_ent = np.zeros(n_epoch,)
Log_acc = np.zeros((n_epoch, task.n_parts))
Log_mis = np.zeros((n_epoch, task.n_parts))
Log_dk = np.zeros((n_epoch, task.n_parts))
Log_cond = np.zeros((n_epoch, n_examples))
Log_cache = [[None] * task.T_total for _ in range(n_examples)]

# cond = 'RM'
cond = None
learning = True
# a_t = torch.tensor(p.dk_id)
# r_t = torch.tensor(0)
# y_it = torch.tensor([0, 0, 0])

# epoch_id, i, t = 0, 0, 0
for epoch_id in np.arange(epoch_id, n_epoch):
    time0 = time.time()
    # sample data
    X, Y = task.sample(n_examples, to_torch=True)
    # training objective
    supervised = epoch_id < supervised_epoch
    # logger
    log_return, log_pi_ent = 0, 0
    log_loss_sup, log_loss_actor, log_loss_critic = 0, 0, 0
    log_dist_a = np.zeros((n_examples, task.T_total, p.a_dim))

    for i in range(n_examples):
        # pick a condition
        cond_i = pick_condition(p, rm_only=supervised, fix_cond=cond)
        # init model wm and em
        hc_t = agent.get_init_states()
        agent.init_em_config()

        # pg calculation cache
        loss_sup = 0
        probs, rewards, values, ents = [], [], [], []
        for t in range(task.T_total):
            # whether to encode
            # if not supervised:
            set_encoding_flag(t, [p.env.tz.event_ends[0]], agent)
            # agent.dnd.encoding_off
            # axgent.dnd.retrieval_off
            # forwardxw
            pi_a_t, v_t, hc_t, cache_t = agent.forward(
                X[i][t].view(1, 1, -1), hc_t)
            a_t, p_a_t = agent.pick_action(pi_a_t)
            r_t = get_reward(a_t, Y[i][t], p.env.penalty)
            # cache the results for later RL loss computation
            probs.append(p_a_t)
            rewards.append(r_t)
            values.append(v_t)
            ents.append(entropy(pi_a_t))
            # cache results for later analysis
            log_dist_a[i, t, :] = to_sqnp(pi_a_t)
            Log_cache[i][t] = cache_t
            # compute supervised loss
            yhat_t = torch.squeeze(pi_a_t)[:-1]
            loss_sup += F.mse_loss(yhat_t, Y[i][t])
            # if not supervised:
            # update WM/EM bsaed on the condition
            hc_t = cond_manipulation(
                cond_i, t, p.env.tz.event_ends[0], hc_t, agent)

        # compute RL loss
        returns = compute_returns(rewards)
        loss_actor, loss_critic = compute_a2c_loss(probs, values, returns)
        pi_ent = torch.stack(ents).sum()
        # if learning and not supervised
        if learning:
            if supervised:
                loss = loss_sup
            else:
                loss = loss_actor + loss_critic - pi_ent * eta
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        # after every event sequence, log stuff
        log_loss_sup += loss_sup / n_examples
        log_pi_ent += pi_ent.item() / n_examples
        log_return += torch.stack(rewards).sum().item()/n_examples
        log_loss_actor += loss_actor.item()/n_examples
        log_loss_critic += loss_critic.item()/n_examples
        Log_cond[epoch_id, i] = p.env.tz.cond_dict.inverse[cond_i]

    # log
    Log_pi_ent[epoch_id] = log_pi_ent
    Log_return[epoch_id] = log_return
    Log_loss_sup[epoch_id] = log_loss_sup
    Log_loss_actor[epoch_id] = log_loss_actor
    Log_loss_critic[epoch_id] = log_loss_critic

    # log message
    runtime = time.time() - time0
    # compute stats
    bm_ = compute_behav_metrics(Y, log_dist_a, p)
    Log_acc[epoch_id], Log_mis[epoch_id], Log_dk[epoch_id] = bm_
    acc_mu_pts_str = " ".join('%.2f' % i for i in Log_acc[epoch_id])
    dk_mu_pts_str = " ".join('%.2f' % i for i in Log_dk[epoch_id])
    mis_mu_pts_str = " ".join('%.2f' % i for i in Log_mis[epoch_id])
    # print
    msg = '%3d | R: %.2f, acc: %s, dk: %s, mis: %s, ent: %.2f | ' % (
        epoch_id, Log_return[epoch_id],
        acc_mu_pts_str, dk_mu_pts_str, mis_mu_pts_str, Log_pi_ent[epoch_id])
    msg += 'L: a: %.2f c: %.2f, s: %.2f | t: %.2fs' % (
        Log_loss_actor[epoch_id], Log_loss_critic[epoch_id],
        Log_loss_sup[epoch_id], runtime)
    print(msg)

    # update lr scheduler
    if not supervised:
        neg_pol_score = np.mean(Log_mis[epoch_id]) - np.mean(Log_acc[epoch_id])
        scheduler.step(neg_pol_score)

    # save weights
    if np.mod(epoch_id+1, log_freq) == 0:
        save_ckpt(epoch_id+1, log_subpath['ckpts'], agent, optimizer)


'''plot learning curves'''
f, axes = plt.subplots(3, 2, figsize=(10, 9), sharex=True)
axes[0, 0].plot(Log_return)
axes[0, 0].set_ylabel('return')
axes[0, 0].axhline(0, color='grey', linestyle='--')
axes[0, 0].set_title(Log_return[-1])

axes[0, 1].plot(Log_pi_ent)
axes[0, 1].set_ylabel('entropy')

axes[1, 0].plot(Log_loss_actor, label='actor')
axes[1, 0].plot(Log_loss_critic, label='critic')
axes[1, 0].axhline(0, color='grey', linestyle='--')
axes[1, 0].legend()
axes[1, 0].set_ylabel('loss, rl')

axes[1, 1].plot(Log_loss_sup)
axes[1, 1].set_ylabel('loss, sup')

for ip in range(2):
    axes[2, ip].set_title(f'part {ip+1}')
    axes[2, ip].plot(Log_acc[:, ip], label='acc')
    axes[2, ip].plot(Log_acc[:, ip]+Log_dk[:, ip], label='acc+dk')
    axes[2, ip].plot(
        Log_acc[:, ip]+Log_dk[:, ip] + Log_mis[:, ip],
        label='acc+dk_err', linestyle='--', color='red'
    )
axes[2, -1].legend()
axes[2, 0].set_ylabel('% behavior')

for i, ax in enumerate(f.axes):
    ax.axvline(supervised_epoch, color='grey', linestyle='--')

axes[-1, 0].set_xlabel('Epoch')
axes[-1, 1].set_xlabel('Epoch')
sns.despine()
f.tight_layout()
fig_path = os.path.join(log_subpath['figs'], 'tz-lc.png')
f.suptitle('learning curves', fontsize=15)
f.savefig(fig_path, dpi=100, bbox_to_anchor='tight')


'''plot performance'''
cond_ids = {}
for cond_name_ in list(p.env.tz.cond_dict.values()):
    cond_id_ = p.env.tz.cond_dict.inverse[cond_name_]
    cond_ids[cond_name_] = Log_cond[-1, :] == cond_id_

for cond_name_ in list(p.env.tz.cond_dict.values()):
    Y_ = to_sqnp(Y)[cond_ids[cond_name_], :]
    log_dist_a_ = log_dist_a[cond_ids[cond_name_], :]
    # compute performance for this condition
    acc_mu, acc_er = compute_acc(Y_, log_dist_a_, return_er=True)
    dk_mu = compute_dk(log_dist_a_)
    f, ax = plt.subplots(1, 1, figsize=(7, 4))
    plot_tz_pred_acc(
        acc_mu, acc_er, acc_mu+dk_mu,
        [p.env.tz.event_ends[0]+1], p,
        f, ax,
        title=f'Performance on the TZ task: {cond_name_}',
    )
    fig_path = os.path.join(log_subpath['figs'], f'tz-acc-{cond_name_}.png')
    f.savefig(fig_path, dpi=100, bbox_to_anchor='tight')


# f, ax = plt.subplots(1, 1, figsize=(7, 4))
# ax.plot(to_sqnp(returns))
# ax.plot(to_sqnp(torch.stack(values)))
# ax.legend([r'$r_t$', 'value estimate'])
# ax.set_xlabel('Time')
# ax.set_title('the critic can estimate the immediate reward')
# sns.despine()
#
# i, t = 0, 0
# inpt = torch.zeros((n_examples, task.T_total))
# leak = torch.zeros((n_examples, task.T_total))
# comp = torch.zeros((n_examples, task.T_total))
# C = np.zeros((n_examples, task.T_total, p.net.n_hidden))
# H = np.zeros((n_examples, task.T_total, p.net.n_hidden))
# M = np.zeros((n_examples, task.T_total, p.net.n_hidden))
# CM = np.zeros((n_examples, task.T_total, p.net.n_hidden))
# DA = np.zeros((n_examples, task.T_total, p.net.n_hidden))
#
# for i in range(n_examples):
#     for t in range(task.T_total):
#         [vector_signal, scalar_signal, misc] = Log_cache[i][t]
#         [inpt[i, t], leak[i, t], comp[i, t]] = scalar_signal
#         [h_t, m_t, cm_t, des_act_t] = misc
#         H[i, t, :] = to_sqnp(h_t)
#         M[i, t, :] = to_sqnp(m_t)
#         CM[i, t, :] = to_sqnp(cm_t)
#         DA[i, t, :] = to_sqnp(des_act_t)
#
# C = CM - M
# inpt = to_sqnp(inpt)
# leak = to_sqnp(leak)
# comp = to_sqnp(comp)
#
# event_bonds = [p.env.tz.event_ends[0]+1]
#
# cond_name = 'DM'
# f, ax = plt.subplots(1, 1)
# ax.plot(np.mean(inpt[cond_ids[cond_name], task.T_part:], axis=0), label='inpw')
# ax.plot(np.mean(leak[cond_ids[cond_name], task.T_part:], axis=0), label='leak')
# ax.plot(np.mean(comp[cond_ids[cond_name], task.T_part:], axis=0), label='comp')
# # ax.axvline(event_bonds, color='red', linestyle='--')
# ax.set_title(f'{cond_name}')
# ax.legend()
# sns.despine()
#
# '''t-RDM'''
#
#
# def compute_trsm(data_):
#     n_examples, n_timepoints, n_dim = np.shape(data_)
#     trsm_ = np.zeros((n_timepoints, n_timepoints))
#     for data_i_ in data_:
#         trsm_ += np.corrcoef(data_i_)
#     return trsm_ / n_examples
#
#
# data = C
# trsm = {}
# for cond_name in cond_ids.keys():
#     if np.sum(cond_ids[cond_name]) == 0:
#         continue
#     else:
#         data_cond_ = data[cond_ids[cond_name], :, :]
#         trsm[cond_name] = compute_trsm(data_cond_)
#
# cond_name = 'DM'
# f, ax = plt.subplots(1, 1)
# sns.heatmap(
#     trsm[cond_name], cmap='RdBu_r', square=True,
#     center=0,
#     ax=ax
# )
# ax.axvline(event_bonds[0], color='red', linestyle='--')
# ax.axhline(event_bonds[0], color='red', linestyle='--')
# ax.set_title(f'TR-TR, similarity, {cond_name}')
#
#
# '''memory - cell state correlation'''
#
#
# def cosine_similarity(u, v):
#     return u @ v / np.linalg.norm(u) / np.linalg.norm(v)
#
#
# h_0, _ = agent.get_init_states()
# h_0 = to_sqnp(h_0)
# h_0 = np.random.normal(size=(agent.hidden_dim,)) * .1
#
# corr_b = np.zeros(task.T_total,)
# corr_m = np.zeros(task.T_total,)
#
#
# # data = C
# # cond_name = 'RM'
# # data_cond_ = data[cond_ids[cond_name], :, :]
# #
# # for i in range(len(data_cond_)):
# #     H_i = data_cond_[i, :, :]
# #     mem = H_i[task.T_part-1, ]
# #     for t in range(task.T_total):
# #         corr_b[t] += cosine_similarity(h_0, H_i[t, :])
# #         # np.corrcoef(h_0, H_i[t, :])[0, 1]
# #         corr_m[t] += cosine_similarity(mem, H_i[t, :])
# #         # np.corrcoef(mem, H_i[t, :])[0, 1]
# # corr_b /= len(data_cond_)
# # corr_m /= len(data_cond_)
# #
# # f, ax = plt.subplots(1, 1, figsize=(7, 4))
# # ax.plot(corr_m)
# # ax.plot(corr_b)
# # ax.axhline(0, color='grey', linestyle='--')
# # ax.axvline(event_bonds[0], color='red', linestyle='--')
# # ax.set_title(f'{p.env.tz.cond_dict[cond_id_]}')
# # sns.despine()
#
# # f, ax = plt.subplots(1, 1, figsize=(6, 3))
# # ax.plot(trsm[cond_id_][5, :])
# # ax.axhline(0, color='grey', linestyle='--')
# # ax.axvline(event_bonds[0]-1, color='red', linestyle='--')
# # ax.set_xlabel('Time')
# # ax.set_ylabel('Correlation')
# # ax.set_title('similarity: cell state vs. memory, ' +
# #              f'{p.env.tz.cond_dict[cond_id_]}')
# # sns.despine()
# #
# #
# # np.shape(log_dist_a)
# # np.shape(H)
#
#
# actions = np.argmax(log_dist_a[:, :, :], axis=-1)
# targets = np.argmax(to_sqnp(Y), axis=-1)
# dks = actions == p.dk_id
# np.shape(dks)
#
# pca = PCA(10)
# data = DA
# cond_name = 'DM'
# data_cond = data[cond_ids[cond_name], :, :]
# targets_cond = targets[cond_ids[cond_name]]
#
# t = 5
# alpha = .7
# h_0 = to_sqnp(agent.get_init_states()[0]).reshape(1, -1)
# for t in range(task.T_total):
#
#     H_pca = pca.fit_transform(data_cond[:, t, :])
#     h_0_pca = pca.transform(h_0)
#
#     f, ax = plt.subplots(1, 1, figsize=(6, 5))
#     for y_val in range(p.y_dim):
#         y_sel_op = y_val == targets_cond
#         sel_op_ = np.logical_and(~dks[cond_ids[cond_name], t], y_sel_op[:, t])
#         ax.scatter(
#             H_pca[sel_op_, 0], H_pca[sel_op_, 1],
#             marker='o', alpha=alpha,
#         )
#         # f.legend(['0', '1'])
#     ax.scatter(
#         H_pca[dks[cond_ids[cond_name], t], 0],
#         H_pca[dks[cond_ids[cond_name], t], 1],
#         marker='x', color='black', alpha=alpha,
#     )
#
#     ax.scatter(
#         h_0_pca[:, 0], h_0_pca[:, 1], color='red'
#     )
#     ax.set_xlabel('PC 1')
#     ax.set_ylabel('PC 2')
#     ax.set_title(f'Pre-decision activity, time = {t}')
#     sns.despine()
#
#
# # plt.plot(np.cumsum(pca.explained_variance_ratio_))
