import sys
import os
import torch
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

from models import LCALSTM as Agent
from task import SequenceLearning
from exp_tz import run_tz
from utils.params import P
from utils.constants import TZ_COND_DICT
from utils.io import build_log_path, load_ckpt, load_env_metadata, pickle_load_dict
from analysis import compute_acc, compute_dk, compute_mistake, trim_data, \
    compute_cell_memory_similarity, create_sim_dict,  process_cache,\
    batch_compute_true_dk,  get_trial_cond_ids, compute_n_trials_to_skip,\
    compute_cell_memory_similarity_stats, sep_by_qsource, get_qsource
from analysis.task import get_oq_keys
from analysis.neural import build_yob, build_cv_ids
from vis import plot_pred_acc_rcl, get_ylim_bonds, imshow_decoding_heatmap
from matplotlib.ticker import FormatStrFormatter
# import matplotlib.patches as patches
sns.set(style='white', palette='colorblind', context='poster')
all_conds = TZ_COND_DICT.values()
seed = 0
log_root = '../demo-log/'
fig_log_dir = '../figs'
# fig_log_dir = '../../results'

'''change parameters here'''
simulation_id = 1

if simulation_id == 1:
    exp_name = 'vary-training-penalty'
    attach_cond = 0
    enc_size_test = 16
    penalty_train = penalty_test = 4
    # penalty_train = penalty_test = 0
elif simulation_id == 2:
    exp_name = 'vary-test-penalty'
    attach_cond = 0
    enc_size_test = 16
    penalty_train = 4
    penalty_test = 4
    # penalty_test = 2
    # penalty_test = 0
elif simulation_id == 4:
    exp_name = 'familiarity-signal'
    attach_cond = 1
    enc_size_test = 16
    penalty_train = 4
    penalty_test = 4
elif simulation_id == 5:
    exp_name = 'vary-test-penalty'
    attach_cond = 0
    enc_size_test = 8
    penalty_train = 4
    penalty_test = 4
else:
    raise ValueError(
        'This demo only support simulation 1, 2, 4, and 5. Simulation {simulation_id} is not available.'
    )

# default params
supervised_epoch = 600
epoch_load = 1000
n_branch = 4
n_param = 16
enc_size = 16
pad_len_load = -1
p_rm_ob_enc_load = .3
p_rm_ob_rcl_load = 0
def_prob = .25
n_def_tps = 0
comp_val = .8
p_test = 0
p_rm_ob_enc_test = p_test
p_rm_ob_rcl_test = p_test
similarity_max_test = .9
similarity_min_test = 0
fix_cond = None
n_examples_test = 256
subj_id = 0

p = P(
    exp_name=exp_name, sup_epoch=supervised_epoch,
    n_param=n_param, n_branch=n_branch, pad_len=pad_len_load,
    def_prob=def_prob, n_def_tps=n_def_tps,
    enc_size=enc_size, attach_cond=attach_cond,
    penalty=penalty_train,
    p_rm_ob_enc=p_rm_ob_enc_load, p_rm_ob_rcl=p_rm_ob_rcl_load,
)
# create logging dirs
log_path, log_subpath = build_log_path(
    subj_id, p, log_root=log_root, mkdir=False, verbose=True
)

# init env
env_data = load_env_metadata(log_subpath)
def_path = env_data['def_path']
p.env.def_path = def_path
p.update_enc_size(enc_size_test)

task = SequenceLearning(
    n_param=p.env.n_param, n_branch=p.env.n_branch,
    p_rm_ob_enc=p_test, p_rm_ob_rcl=p_test, similarity_cap_lag=p.n_event_remember,
    similarity_max=similarity_max_test, similarity_min=similarity_min_test,
)
x_dim = task.x_dim
if attach_cond != 0:
    x_dim += 1
# load the agent back
agent = Agent(
    input_dim=x_dim, output_dim=p.a_dim,
    rnn_hidden_dim=p.net.n_hidden, dec_hidden_dim=p.net.n_hidden_dec,
    dict_len=p.net.dict_len
)
agent, optimizer = load_ckpt(epoch_load, log_subpath['ckpts'], agent)

# test the model
np.random.seed(seed)
torch.manual_seed(seed)
[results, metrics, XY] = run_tz(
    agent, optimizer, task, p, n_examples_test,
    supervised=False, learning=False, get_data=True,
    fix_cond=fix_cond, fix_penalty=penalty_test
)

[dist_a_, Y_, log_cache_, log_cond_] = results
[X_raw, Y_raw] = XY


'''precompute some constants'''

def_path_int = np.argmax(def_path, axis=1)
# figure out max n-time-steps across for all trials
T_part = n_param
T_total = T_part * task.n_parts

'''organize results to analyzable form'''
# skip examples untill EM is full
n_examples_skip = compute_n_trials_to_skip(log_cond_, p)
n_trials = n_examples_test - n_examples_skip
trial_id = np.arange(n_trials)

data_to_trim = [dist_a_, Y_, log_cond_, log_cache_, X_raw]
[dist_a, Y, log_cond, log_cache, X_raw] = trim_data(
    n_examples_skip, data_to_trim)
X_raw = np.array(X_raw)

# process the data
cond_ids = get_trial_cond_ids(log_cond)
[C, H, M, CM, DA, V], [inpt] = process_cache(
    log_cache, T_total, p)
# compute ground truth / objective uncertainty, delay phase removed
true_dk_wm, true_dk_em = batch_compute_true_dk(X_raw, task)
q_source = get_qsource(true_dk_em, true_dk_wm, cond_ids, p)

# load lca params
comp = np.full(np.shape(inpt), comp_val)
leak = np.full(np.shape(inpt), 0)

# compute performance
actions = np.argmax(dist_a, axis=-1)
targets = np.argmax(Y, axis=-1)
corrects = targets == actions
dks = actions == p.dk_id
mistakes = np.logical_and(targets != actions, ~dks)

# compute performance stats
for i, cn in enumerate(all_conds):
    Y_ = Y[cond_ids[cn], :]
    dist_a_ = dist_a[cond_ids[cn], :]
    # compute performance for this condition
    acc_mu, acc_er = compute_acc(Y_, dist_a_, return_er=True)
    dk_mu = compute_dk(dist_a_)
    mis_mu, mis_er = compute_mistake(
        Y_, dist_a_, return_er=True)

'''plot behavioral performance'''
f, axes = plt.subplots(1, 3, figsize=(12, 4))
for i, cn in enumerate(['RM', 'DM', 'NM']):
    Y_ = Y[cond_ids[cn], :]
    dist_a_ = dist_a[cond_ids[cn], :]
    # compute performance for this condition
    acc_mu, acc_er = compute_acc(Y_, dist_a_, return_er=True)
    dk_mu = compute_dk(dist_a_)
    if i == 0:
        add_legend = True
        show_ylabel = True
        legend_loc = (.33, .7)
    else:
        add_legend = False
        show_ylabel = False
    # plot
    plot_pred_acc_rcl(
        acc_mu[T_part:], acc_er[T_part:],
        acc_mu[T_part:] + dk_mu[T_part:],
        p, f, axes[i],
        title=f'{cn}',
        add_legend=add_legend, legend_loc=legend_loc,
        show_ylabel=show_ylabel
    )
    axes[i].set_ylim([-.05, 1.05])

fname = os.path.join(fig_log_dir, 'event-prediction-performance.png')
f.savefig(fname, dpi=120, bbox_to_anchor='tight')


lca_param_names = ['input gate', 'competition']
lca_param_records = [inpt, comp]

# compute similarity between cell state vs. memories
sim_cos, sim_lca = compute_cell_memory_similarity(
    C, V, inpt, leak, comp)
sim_lca_dict = create_sim_dict(
    sim_lca, cond_ids, n_targ=p.n_segments)
sim_lca_stats = compute_cell_memory_similarity_stats(
    sim_lca_dict, cond_ids)

memory_types = ['targ', 'lure']
avg_ma = {cond: {m_type: None for m_type in memory_types}
          for cond in all_conds}
for cond in all_conds:
    for m_type in memory_types:
        if sim_lca_dict[cond][m_type] is not None:
            avg_ma[cond][m_type] = np.mean(
                sim_lca_dict[cond][m_type], axis=-1)

'''plot target/lure activation for all conditions - horizontal'''
gr_pal = sns.color_palette('colorblind')[2:4]
ylim_bonds = {'LCA': None, 'cosine': None}
ker_name, sim_stats_plt_ = 'LCA', sim_lca_stats

f, axes = plt.subplots(1, 3, figsize=(12, 4))
for i, c_name in enumerate(cond_ids.keys()):
    for m_type in memory_types:
        if m_type == 'targ' and c_name == 'NM':
            continue
        color_ = gr_pal[0] if m_type == 'targ' else gr_pal[1]
        axes[i].errorbar(
            x=range(T_part),
            y=sim_stats_plt_[c_name][m_type]['mu'][T_part:],
            yerr=sim_stats_plt_[c_name][m_type]['er'][T_part:],
            label=f'{m_type}', color=color_
        )
        axes[i].set_title(c_name)
        axes[i].set_xlabel('Time')
axes[0].set_ylabel('Memory activation')
axes[0].legend()

# make all ylims the same
ylim_bonds[ker_name] = get_ylim_bonds(axes)
ylim_bonds[ker_name] = (
    np.max((ylim_bonds[ker_name][0], -.05)
           ), np.round((ylim_bonds[ker_name][1] + .1), decimals=1)
)
for i, ax in enumerate(axes):
    ax.set_ylim(ylim_bonds[ker_name])
    ax.set_xticks([0, p.env.n_param - 1])
    ax.xaxis.set_major_formatter(FormatStrFormatter('%d'))
    ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
f.tight_layout()
sns.despine()
fname = os.path.join(fig_log_dir, 'memory-activation.png')
f.savefig(fname, dpi=120, bbox_to_anchor='tight')


'''use CURRENT uncertainty to predict memory activation'''
DM_qsources = ['EM only', 'both']
n_se = 1
cond_name = 'DM'
targ_act_cond_p2_stats = sep_by_qsource(
    avg_ma[cond_name]['targ'][:, T_part:],
    q_source[cond_name], n_se=n_se
)
ig_cond_p2_stats = sep_by_qsource(
    lca_param_records[0][cond_ids[cond_name]][:, T_part:],
    q_source[cond_name], n_se=n_se
)


f, ax = plt.subplots(1, 1, figsize=(7, 5))
for key, [mu_, er_] in targ_act_cond_p2_stats.items():
    if not np.all(np.isnan(mu_)):
        ax.errorbar(x=range(n_param), y=mu_,
                    yerr=er_, label=key)
ax.set_title(f'Target memory activation, {cond_name}')
ax.set_xlabel('Time (part 2)')
ax.set_ylabel('Activation')
ax.set_ylim([-.05, None])
ax.set_xticks([0, p.env.n_param - 1])
ax.legend(['not already observed',
           'already observed'], fancybox=True)
ax.xaxis.set_major_formatter(FormatStrFormatter('%d'))
f.tight_layout()
sns.despine()
fname = os.path.join(fig_log_dir, 'dm-memory-activation-uncertainty.png')
f.savefig(fname, dpi=120, bbox_to_anchor='tight')


f, ax = plt.subplots(1, 1, figsize=(7, 5))
for key, [mu_, er_] in ig_cond_p2_stats.items():
    if not np.all(np.isnan(mu_)):
        ax.errorbar(x=range(n_param), y=mu_,
                    yerr=er_, label=key)
ax.set_title(f'Input gate, {cond_name}')
ax.set_xlabel('Time (part 2)')
ax.set_ylabel('Activation')
ax.set_ylim([-.05, None])
ax.set_xticks([0, p.env.n_param - 1])
ax.legend(['not already observed',
           'already observed'], fancybox=True)
ax.xaxis.set_major_formatter(FormatStrFormatter('%d'))
f.tight_layout()
sns.despine()
fname = os.path.join(fig_log_dir, 'dm-input-gate-uncertainty.png')
f.savefig(fname, dpi=120, bbox_to_anchor='tight')


'''load back pretrained MVPA classifier'''
mvpa_data_dict_fname = f'mvpa-{exp_name}-p{penalty_train}-{penalty_test}-%.2f.pkl' % def_prob
if not os.path.isfile(os.path.join('data/', mvpa_data_dict_fname)):
    sys.exit('No pre-trained classifier for this config')
mvpa_results = pickle_load_dict(os.path.join('data/', mvpa_data_dict_fname))
clfs = mvpa_results['classifier_g'][subj_id]

'''organize the data for MVPA analysis'''
corrects_p2 = corrects[:, T_part:]
mistakes_p1 = mistakes[:, :T_part]
mistakes_p2 = mistakes[:, T_part:]
targets_p1, targets_p2 = targets[:, :T_part], targets[:, T_part:]
actions_p1, actions_p2 = actions[:, :T_part], actions[:, T_part:]

# pre-extract p2 data for the DM condition
corrects_dmp2 = corrects_p2[cond_ids['DM']]
mistakes_dmp2 = mistakes_p2[cond_ids['DM']]
mistakes_dmp1 = mistakes_p1[cond_ids['DM']]

targets_dmp2 = targets_p2[cond_ids['DM'], :]
actions_dmp2 = actions_p2[cond_ids['DM']]
targets_dmp1 = targets_p1[cond_ids['DM'], :]
actions_dmp1 = actions_p1[cond_ids['DM']]

# get observation key and values for p1 p2
o_keys = np.zeros((n_trials, T_total))
for i in trial_id:
    o_keys[i], _, _ = get_oq_keys(X_raw[i], task)
o_keys_p1, o_keys_p2 = o_keys[:, :T_part], o_keys[:, T_part:]
o_keys_dmp1 = o_keys_p1[cond_ids['DM']]
o_keys_dmp2 = o_keys_p2[cond_ids['DM']]

# precompute mistakes-related variables
has_mistake = np.sum(mistakes_dmp2, axis=1) > 0
# split trials w/ vs. w/o mistakes
actions_dmp1hm = actions_dmp1[has_mistake, :]
targets_dmp1hm = targets_dmp1[has_mistake, :]
actions_dmp2hm = actions_dmp2[has_mistake, :]
targets_dmp2hm = targets_dmp2[has_mistake, :]
mistakes_dmp2hm = mistakes_dmp2[has_mistake, :]
o_keys_dmp1hm = o_keys_dmp1[has_mistake, :]
o_keys_dmp2hm = o_keys_dmp2[has_mistake, :]
actions_dmp1nm = actions_dmp1[~has_mistake, :]
targets_dmp1nm = targets_dmp1[~has_mistake, :]
actions_dmp2nm = actions_dmp2[~has_mistake, :]
targets_dmp2nm = targets_dmp2[~has_mistake, :]
corrects_dmp2nm = corrects_dmp2[~has_mistake, :]
o_keys_dmp1nm = o_keys_dmp1[~has_mistake, :]
o_keys_dmp2nm = o_keys_dmp2[~has_mistake, :]

o_keys_dmhm = np.hstack([o_keys_dmp1hm, o_keys_dmp2hm])
actions_dmhm = np.hstack([actions_dmp1hm, actions_dmp2hm])
targets_dmhm = np.hstack([targets_dmp1hm, targets_dmp2hm])
o_keys_dmnm = np.hstack([o_keys_dmp1nm, o_keys_dmp2nm])
actions_dmnm = np.hstack([actions_dmp1nm, actions_dmp2nm])
targets_dmnm = np.hstack([targets_dmp1nm, targets_dmp2nm])

actions_dmnm[actions_dmnm == n_branch] = -1
actions_dmhm[actions_dmhm == n_branch] = -1
actions_dmhm += 1
actions_dmnm += 1
targets_dmhm += 1
targets_dmnm += 1

'''apply the classifier and plot the decoding result for 2 trials'''
Yob_proba = np.zeros((n_trials, T_part, T_total, n_branch + 1))
for t in range(n_param):
    for i in range(n_trials):
        Yob_proba[i, t] = clfs[t].predict_proba(CM[i])

# get decoding heatmaps
Yob_proba_dm = Yob_proba[cond_ids['DM']]
Yob_proba_hm = Yob_proba_dm[has_mistake, :]
Yob_proba_nm = Yob_proba_dm[~has_mistake, :]

# show mistakes
i, j = 1, 0
# for the i-th mistakes trial, plot the j-th mistake
# for i in range(np.shape(mistakes_dmp2hm)[0]):
# when/what feature were mistaken
mistake_feature_i = np.where(mistakes_dmp2hm[i, :])[0]
# for j in range(len(mistake_feature_i)):
decoded_feat_mat = Yob_proba_hm[i, mistake_feature_i[j]]
feat_otimes = np.where(
    o_keys_dmhm[i] == mistake_feature_i[j])[0]
feat_qtimes = mistake_feature_i[j] + np.array([0, T_part])
targets_dmnm_i = targets_dmhm[i, :]
actions_dmnm_i = actions_dmhm[i, :]
f, axes = imshow_decoding_heatmap(
    decoded_feat_mat, feat_otimes, feat_qtimes,
    targets_dmnm_i, actions_dmnm_i, n_param, n_branch
)
fname = os.path.join(fig_log_dir, f'mistake-{i}-{j}.png')
f.savefig(fname, dpi=100, bbox_to_anchor='tight')

# show correct trials
i, j = 1, 2
# for i in range(np.shape(corrects_dmp2nm)[0]):
# when/what feature were mistaken
correct_feature_i = np.where(corrects_dmp2nm[i, :])[0]
# for j in range(len(correct_feature_i)):
decoded_feat_mat = Yob_proba_nm[i, correct_feature_i[j]]
feat_otimes = np.where(
    o_keys_dmnm[i] == correct_feature_i[j])[0]
feat_qtimes = correct_feature_i[j] + np.array([0, T_part])
targets_dmnm_i = targets_dmnm[i, :]
actions_dmnm_i = actions_dmnm[i, :]
f, axes = imshow_decoding_heatmap(
    decoded_feat_mat, feat_otimes, feat_qtimes,
    targets_dmnm_i, actions_dmnm_i, n_param, n_branch
)
fname = os.path.join(fig_log_dir, f'correct-{i}-{j}.png')
f.savefig(fname, dpi=100, bbox_to_anchor='tight')
