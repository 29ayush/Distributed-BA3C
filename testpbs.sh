#!/bin/bash -l
# 10 nodes, 24 MPI processes/node, 240 MPI processes total
#PBS -N="ayush@test"
#PBS -o=myjob.%j.o
#PBS -e=myjob.%j.e
#PBS -l select=1:ncpus=1:mpiprocs=1
#======START=====
echo "The current job ID is $PBS_JOBID"
#echo "Running on $SLURM_JOB_NUM_NOiDES nodes"
#echo "Using $SLURM_NTASKS_PER_NODE tasks per node"
#echo "A total of $SLURM_NTASKS tasks is used"
echo "Nodes assigned to it : $PBS_NODEFILE"
#=====END====
