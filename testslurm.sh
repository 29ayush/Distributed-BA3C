#!/bin/bash -l
# 10 nodes, 24 MPI processes/node, 240 MPI processes total
#SBATCH --job-name="myjob"
#SBATCH --time=02:00:00
#SBATCH --ntasks=1
#SBATCH --ntasks-per-node=1
#SBATCH --output=myjob.%j.o
#SBATCH --error=myjob.%j.e
#SBATCH --account=slurm
#SBATCH --export=NONE
#======START=====
echo "The current job ID is $SLURM_JOB_ID"
echo "Running on $SLURM_JOB_NUM_NODES nodes"
echo "Using $SLURM_NTASKS_PER_NODE tasks per node"
echo "A total of $SLURM_NTASKS tasks is used"
echo "Nodes assigned to it : $SLURM_JOB_NODELIST"
#=====END====
