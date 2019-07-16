import time
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt

from task import SequenceLearning
from analysis import compute_event_similarity_matrix, compute_stats
from matplotlib.ticker import FormatStrFormatter
sns.set(style='white', palette='colorblind', context='poster')

'''study inter-event similarity as a function of n_branch, n_param'''
n_param = 15
n_branch = 4
n_samples = 101
# expected_similarity = 1 / n_branch
# similarity_cap = expected_similarity * 2
similarity_cap = .35
similarity_cap_lag = 4

# init

task = SequenceLearning(
    n_param, n_branch, n_parts=2,
    similarity_cap=similarity_cap, similarity_cap_lag=similarity_cap_lag
)
# sample
_, _, Misc = task.sample(n_samples, to_torch=False, return_misc=True)
# unpack
Y = np.array([Misc[i][1] for i in range(n_samples)])


'''analysis'''

# compute similarity
normalize = True
if not normalize:
    similarity_cap = task.similarity_cap * n_param
else:
    similarity_cap = task.similarity_cap

similarity_matrix = compute_event_similarity_matrix(Y, normalize=normalize)
# plot the similarity matrix
f, ax = plt.subplots(1, 1, figsize=(6, 5))
sns.heatmap(
    similarity_matrix,
    xticklabels=n_samples//2, yticklabels=n_samples//2,
    cmap='viridis', ax=ax
)
ax.set_xlabel('event i')
ax.set_ylabel('event j')
ax.set_title('inter-event similarity')


similarity_matrix
one_matrix = np.ones((n_samples, n_samples))
tril_mask = np.tril(one_matrix, k=-1).astype(bool)
tril_k_mask = np.tril(one_matrix, k=-task.similarity_cap_lag).astype(bool)
similarity_mask_recent = np.logical_and(tril_mask, ~tril_k_mask)
similarity_mask_distant = tril_k_mask


mu_rc, er_rc = compute_stats(similarity_matrix[similarity_mask_recent])
mu_dt, er_dt = compute_stats(similarity_matrix[similarity_mask_distant])
bar_height = [mu_rc, mu_dt]
bar_yerr = [er_rc, er_dt]
xticks = range(len(bar_height))
xlabs = ['recent', 'distant']

f, ax = plt.subplots(1, 1, figsize=(5, 4))

ax.bar(x=xticks, height=bar_height, yerr=bar_yerr)
ax.set_title('Event similarity')
ax.set_ylabel('Param overlap')
ax.set_xticks(xticks)
ax.set_xticklabels(xlabs)
sns.despine()
f.tight_layout()


# '''plot the distribution (for the lower triangular part)'''
# similarity_matrix_tril = similarity_matrix[np.tril_indices(n_samples, k=-1)]
# bins = len(np.unique(similarity_matrix_tril))
# linewidth = 10
# max_bond = 1 if normalize else n_param
# title = 'Inter-event similarity (mu = %.2f, sd= %.2f)' % (
#     np.mean(similarity_matrix_tril), np.std(similarity_matrix_tril))
# xlabel = '% Param value shared' if normalize else '# Param value shared'
# # plot the distribution
# f, ax = plt.subplots(1, 1, figsize=(6, 5))
# sns.distplot(
#     similarity_matrix_tril,
#     kde=False, bins=bins, norm_hist=True,
#     ax=ax
# )
# ax.axvline(max_bond, linestyle='--', color='grey', linewidth=linewidth)
# ax.axvline(similarity_cap, linestyle='--',
#            color='grey', alpha=.5, linewidth=linewidth//2)
# ax.set_xlabel(xlabel)
# ax.set_ylabel('Freq.')
# ax.set_title(title)
# ax.set_xlim([0, max_bond])
# if normalize:
#     ax.xaxis.set_major_formatter(FormatStrFormatter('%.1f'))
# else:
#     ax.xaxis.set_major_formatter(FormatStrFormatter('%d'))
# sns.despine()


similarity_caps = np.linspace(.3, .5, 5)
n_iter = 5
times = np.zeros((len(similarity_caps), n_iter))

n_param = 15
n_branch = 4
n_samples = 256

for i, similarity_cap in enumerate(similarity_caps):
    for j in range(n_iter):
        t0 = time.time()
        task = SequenceLearning(
            n_param, n_branch, n_parts=2,
            similarity_cap=similarity_cap, similarity_cap_lag=similarity_cap_lag
        )
        _, _, Misc = task.sample(n_samples, to_torch=False, return_misc=True)
        # record run time
        times[i, j] = time.time() - t0


mu_t, er_t = compute_stats(times.T)
f, ax = plt.subplots(1, 1, figsize=(10, 5))
xticks = range(len(similarity_caps))
xlabs = ['%.2f' % s for s in similarity_caps]

ax.errorbar(x=xticks, y=mu_t, yerr=er_t)
ax.set_title('Run time, sampling w/ different similarity cap')
ax.set_ylabel('Run time (sec)')
ax.set_xticks(xticks)
ax.set_xticklabels(xlabs)
sns.despine()
f.tight_layout()