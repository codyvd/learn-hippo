#!/bin/bash
#SBATCH -t 19:55:00
#SBATCH -c 1
#SBATCH --mem-per-cpu 4G
#SBATCH --job-name=lcarnn
#SBATCH --mail-type=FAIL
#SBATCH --mail-user=codydong@princeton.edu
#SBATCH --output slurm_log/lcarnn-%j.log

module purge
module load anaconda3/2021.11
conda activate pytorch_q

DATADIR=/scratch/gpfs/cd6060/logs/learn-hippocampus-test/log

echo $(date)

srun python -u train-sl.py --exp_name ${1} --subj_id ${2} --penalty ${3}  \
    --n_epoch ${4} --sup_epoch ${5} --similarity_max ${6} --similarity_min ${7} \
    --penalty_random ${8} --def_prob ${9} --n_def_tps ${10} --cmpt ${11} --attach_cond ${12} \
    --enc_size ${13} --dict_len ${14} --noRL ${15} \
    --log_root $DATADIR

echo $(date)
