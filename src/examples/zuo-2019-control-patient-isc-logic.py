import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
sns.set(style='white', context='talk', palette='colorblind')


def sample(n_time_steps, mu=0, sigma=1, x0=0):
    x = np.zeros(n_time_steps,)
    x[0] = x0
    for t in np.arange(1, n_time_steps):
        x[t] = x[t-1] + np.random.normal(loc=mu, scale=sigma)
    return x


'''logic, compare control-patient isc'''
seed_val = 0
np.random.seed(seed_val)
n_time_steps = 200
noise_scale = 3

# gen data
x = sample(n_time_steps)
noise1 = np.random.normal(size=np.shape(x), scale=noise_scale)
noise2 = np.random.normal(size=np.shape(x), scale=noise_scale)

# plot control only
f, ax = plt.subplots(1, 1, figsize=(10, 3.5))
ax.plot(x + noise1)
# ax.plot(x + noise)
# ax.legend(['control', 'patient'])
ax.set_xlabel('Time')
ax.set_ylabel('BOLD')
ax.set_ylim([-10, 25])
ax.set_xticks([])
ax.set_yticks([])
sns.despine()
f.tight_layout()
f.savefig('examples/figs/isc-c.png', dpi=120)

# plot control and patient
f, ax = plt.subplots(1, 1, figsize=(10, 3.5))
ax.plot(x + noise1)
ax.plot(x + noise2)
# ax.legend(['control', 'patient'])
ax.set_xlabel('Time')
ax.set_ylabel('BOLD')
ax.set_ylim([-10, 25])
ax.set_xticks([])
ax.set_yticks([])
sns.despine()
f.tight_layout()
f.savefig('examples/figs/isc-cp.png', dpi=120)
# f.savefig('examples/figs/isc-2.png', dpi=120)


'''logic, time scrabling'''
seed_val = 15
np.random.seed(seed_val)
y = sample(n_time_steps)

# y1 = sample(n_time_steps, x0=x[-1])
# y2 = sample(n_time_steps, x0=x[-1])

f, ax = plt.subplots(1, 1, figsize=(10, 3.5))
ax.plot(x+noise1)
ax.plot(y+noise2)
ax.set_xticks([])
ax.set_yticks([])
sns.despine()
f.tight_layout()
ax.set_xlabel('Time')
ax.set_ylabel('BOLD')
