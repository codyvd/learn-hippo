'''parameter config class'''

from task.utils import sample_rand_path
from utils.constants import ALL_ENC_MODE, TZ_COND_DICT, RNR_COND_DICT, \
    P_TZ_CONDS, P_RNR_CONDS


class P():
    def __init__(
        self,
        exp_name='rnr',
        n_param=10,
        n_branch=3,
        pad_len=0,
        def_path=None,
        def_prob=None,
        penalty=1,
        rm_ob_probabilistic=False,
        p_rm_ob_rcl=0,
        p_rm_ob_enc=0,
        mode_rm_ob_enc='partial',
        mode_rm_ob_rcl='all',
        n_mvs_tz=2,
        n_mvs_rnr=3,
        enc_size=None,
        enc_mode='cum',
        n_event_remember=4,
        recall_func='LCA',
        kernel='cosine',
        n_hidden=128,
        n_hidden_dec=64,
        lr=1e-3,
        gamma=0,
        eta=.1,
        sup_epoch=None,
        n_epoch=None,
        n_example=None,
    ):
        # set encoding size to be maximal
        # T_part = n_param + pad_len
        if enc_size is None:
            enc_size = n_param
        assert 0 < enc_size <= n_param
        assert n_param % enc_size == 0
        self.n_event_remember = n_event_remember
        self.n_segments = n_param // enc_size
        dict_len = self.n_event_remember * self.n_segments

        if def_path is None:
            def_path = sample_rand_path(n_branch, n_param)
        if def_prob is None:
            def_prob = 1/n_branch
        self.x_dim, self.y_dim, self.a_dim = _infer_data_dims(n_param, n_branch)
        self.dk_id = self.a_dim-1

        # init param classes
        self.env = env(
            exp_name, n_param, n_branch, pad_len,
            def_path, def_prob, penalty,
            rm_ob_probabilistic,
            p_rm_ob_rcl, p_rm_ob_enc,
            mode_rm_ob_rcl, mode_rm_ob_enc,
            n_mvs_tz,
            n_mvs_rnr
        )
        self.net = net(
            recall_func, kernel, enc_mode, enc_size, dict_len,
            n_hidden, n_hidden_dec, lr, gamma, eta,
            n_param, n_branch
        )
        self.misc = misc(sup_epoch, n_epoch, n_example)

    def __repr__(self):
        repr_ = str(self.env.__repr__) + '\n' + str(self.net.__repr__)
        return repr_


class env():

    def __init__(
            self,
            exp_name,
            n_param, n_branch, pad_len,
            def_path, def_prob,
            penalty,
            rm_ob_probabilistic,
            p_rm_ob_rcl, p_rm_ob_enc,
            mode_rm_ob_rcl, mode_rm_ob_enc,
            n_mvs_tz,
            n_mvs_rnr
    ):
        self.exp_name = exp_name
        self.n_param = n_param
        self.n_branch = n_branch
        self.pad_len = 'random' if pad_len == -1 else pad_len
        # self.T_part = n_param + pad_len
        self.rm_ob_probabilistic = rm_ob_probabilistic
        self.p_rm_ob_rcl = p_rm_ob_rcl
        self.p_rm_ob_enc = p_rm_ob_enc
        self.mode_rm_ob_rcl = mode_rm_ob_rcl
        self.mode_rm_ob_enc = mode_rm_ob_enc
        self.def_path = def_path
        self.def_prob = def_prob
        self.penalty = penalty
        #
        self.chance = 1 / n_branch

        self.validate_args()

    def validate_args(self):
        assert self.penalty >= 0

    def __repr__(self):
        repr_ = f'''
        exp_name = {self.exp_name}
        n_param = {self.n_param}, n_branch = {self.n_branch},
        p_remove_observation = {self.p_rm_ob_rcl}
        def_prob = {self.def_prob}
        penalty = {self.penalty}
        def_path = {self.def_path}
        '''
        return repr_


class net():
    def __init__(
        self,
        recall_func, kernel,
        enc_mode, enc_size, dict_len,
        n_hidden, n_hidden_dec, lr, gamma, eta,
        n_param, n_branch
    ):
        self.recall_func = recall_func
        self.kernel = kernel
        self.enc_mode = enc_mode
        self.enc_size = enc_size
        self.n_hidden = n_hidden
        self.n_hidden_dec = n_hidden_dec
        self.lr = lr
        self.gamma = gamma
        self.eta = eta
        self.dict_len = dict_len
        # inferred params
        self.x_dim, self.y_dim, self.a_dim = _infer_data_dims(n_param, n_branch)
        self.dk_id = self.a_dim-1
        self.validate_args()

    def validate_args(self):
        assert 0 <= self.gamma <= 1
        assert self.enc_mode in ALL_ENC_MODE

    def __repr__(self):
        repr_ = f'''
        recall_func = {self.recall_func}, kernel = {self.kernel}
        enc_mode = {self.enc_mode}, enc_size = {self.enc_size}
        n_hidden = {self.n_hidden}
        lr = {self.lr}
        gamma = {self.gamma}
        '''
        return repr_


class misc():

    def __init__(self, sup_epoch, n_epoch=None, n_example=None):
        self.sup_epoch = sup_epoch
        self.n_epoch = n_epoch
        self.n_example = n_example


"""helper functions"""


def get_event_ends(T_part, n_repeats):
    """get the end points for a event sequence, with lenth T, and k repeats
    - event ends need to be removed for prediction accuracy calculation, since
    there is nothing to predict there
    - event boundaries are defined by these values

    Parameters
    ----------
    T_part : int
        the length of an event sequence (one repeat)
    n_repeats : int
        number of repeats

    Returns
    -------
    1d np.array
        the end points of event seqs

    """
    return [T_part * (k+1)-1 for k in range(n_repeats)]


def _infer_data_dims(n_param, n_branch):
    # infer params
    x_dim = (n_param * n_branch) * 2 + n_branch
    y_dim = n_branch
    a_dim = n_branch+1
    return x_dim, y_dim, a_dim
