#!/usr/bin/env python
# -*- coding: utf-8 -*-
# File: concurrency.py
# Author: Yuxin Wu <ppwwyyxxc@gmail.com>

import multiprocessing, threading
import tensorflow as tf
import time
import six
from six.moves import queue, range, zip
import traceback

from ..utils.concurrency import DIE
from ..tfutils.modelutils import describe_model
from ..utils import logger
from ..utils.timer import *
from ..tfutils import *
from ..utils.stat import StatCounter

from .base import *

import time

try:
    if six.PY2:
        from tornado.concurrent import Future
    else:
        from concurrent.futures import Future
except ImportError:
    logger.warn("Cannot import Future in tornado.concurrent. MultiThreadAsyncPredictor won't be available.")
    __all__ = ['MultiProcessPredictWorker', 'MultiProcessQueuePredictWorker']
else:
    __all__ = ['MultiProcessPredictWorker', 'MultiProcessQueuePredictWorker',
                'MultiThreadAsyncPredictor']

class MultiProcessPredictWorker(multiprocessing.Process):
    """ Base class for predict worker that runs offline in multiprocess"""
    def __init__(self, idx, config):
        """
        :param idx: index of the worker. the 0th worker will print log.
        :param config: a `PredictConfig`
        """
        super(MultiProcessPredictWorker, self).__init__()
        self.idx = idx
        self.config = config

    def _init_runtime(self):
        """ Call _init_runtime under different CUDA_VISIBLE_DEVICES, you'll
            have workers that run on multiGPUs
        """
        if self.idx != 0:
            from tensorpack.models._common import disable_layer_logging
            disable_layer_logging()
        self.func = OfflinePredictor(self.config)
        if self.idx == 0:
            describe_model()

class MultiProcessQueuePredictWorker(MultiProcessPredictWorker):
    """ An offline predictor worker that takes input and produces output by queue"""
    def __init__(self, idx, inqueue, outqueue, config):
        """
        :param inqueue: input queue to get data point. elements are (task_id, dp)
        :param outqueue: output queue put result. elements are (task_id, output)
        """
        super(MultiProcessQueuePredictWorker, self).__init__(idx, config)
        self.inqueue = inqueue
        self.outqueue = outqueue
        assert isinstance(self.inqueue, multiprocessing.Queue)
        assert isinstance(self.outqueue, multiprocessing.Queue)

    def run(self):
        self._init_runtime()
        while True:
            tid, dp = self.inqueue.get()
            if tid == DIE:
                self.outqueue.put((DIE, None))
                return
            else:
                self.outqueue.put((tid, self.func(dp)))


class PredictorWorkerThread(threading.Thread):
    def __init__(self, queue, pred_func, id, batch_size=5, debug_charts=False,
            worker_id=None, neptune_client=None):
        super(PredictorWorkerThread, self).__init__()
        self.queue = queue
        self.func = pred_func
        self.daemon = True
        self.batch_size = batch_size
        self.id = id

        self.debug_charts = debug_charts
        if self.debug_charts:
            self.conv = [StatCounter() for _ in range(4)]
            self.fc = [StatCounter() for _ in range(3)]
            self.SEND_EVERY = 100
            self.worker_id = worker_id
            self.neptune_client = neptune_client

    def __handle_debug_stats(self, stats):
        conv_outs = stats[:4]
        fc_outs = stats[4:]

        for counter, out in zip(self.conv, conv_outs):
            counter.feed(out)
        for counter, out in zip(self.fc, fc_outs):
            counter.feed(out)

        if self.conv[0].count == self.SEND_EVERY:
            layers_content = ('layers',
                    float(self.conv[0].average),
                    float(self.conv[1].average),
                    float(self.conv[2].average),
                    float(self.conv[3].average),
                    float(self.fc[0].average),
                    float(self.fc[1].average),
                    float(self.fc[2].average)
                    )
            layers_message = (self.worker_id, layers_content)
            self.neptune_client.send(layers_message)

            for counter in self.conv:
                counter.reset()
            for counter in  self.fc:
                counter.reset()

    def run(self):
        while True:
            try:
                batched, futures = self.fetch_batch()
                outputs = self.func(batched)
                if outputs[-1]:
                    if self.debug_charts:
                        self.__handle_debug_stats(outputs[3:10])
                    for idx, f in enumerate(futures):
                        sublist = []
                        for i, k in enumerate(outputs[:3]):
                            if i == 2:
                                sublist.append(k)
                            else:
                                sublist.append(k[idx])
                        sublist.append(True)
                        f.set_result(sublist)
                else:
                    for f in futures:
                        f.set_result([False])

            except Exception as e:
                print "EXCEPTION IN PREDICTOR THREAD [{}] ======".format(os.environ["PBS_ARRAY_INDEX"])
                traceback.print_exc()

    def fetch_batch(self):
        """ Fetch a batch of data without waiting"""
        inp, f = self.queue.get()
        nr_input_var = len(inp)
        batched, futures = [[] for _ in range(nr_input_var)], []
        for k in range(nr_input_var):
            batched[k].append(inp[k])
        futures.append(f)
        cnt = 1
        while cnt < self.batch_size:
            try:
                inp, f = self.queue.get_nowait()
                for k in range(nr_input_var):
                    batched[k].append(inp[k])
                futures.append(f)
            except queue.Empty:
                break
            cnt += 1
        return batched, futures

class MultiThreadAsyncPredictor(AsyncPredictorBase):
    """
    An multithread online async predictor which run a list of PredictorBase.
    It would do an extra batching internally.
    """
    def __init__(self, predictors, batch_size=5, debug_charts=False, worker_id=None, neptune_client=None):
        """ :param predictors: a list of OnlinePredictor"""
        assert len(predictors)
        for k in predictors:
            #assert isinstance(k, OnlinePredictor), type(k)
            # TODO use predictors.return_input here
            assert k.return_input == False
            #queue_size=len(predictors)*100
            queue_size=len(predictors)*1
        self.input_queue = queue.Queue(maxsize=queue_size)
        self.threads = [
            PredictorWorkerThread(
                self.input_queue, f, id, batch_size=batch_size,
                debug_charts=debug_charts,
                worker_id=worker_id,
                neptune_client=neptune_client)
            for id, f in enumerate(predictors)]

        if six.PY2:
            # TODO XXX set logging here to avoid affecting TF logging
            import tornado.options as options
            options.parse_command_line(['--logging=debug'])

    def start(self):
        for t in self.threads:
            t.start()

    def run(self):      # temporarily for back-compatibility
        self.start()

    def put_task(self, dp, callback=None):
        """
        dp must be non-batched, i.e. single instance
        """
        f = Future()
        if callback is not None:
            f.add_done_callback(callback)

        #print("Q-debug: MultiThreadAsyncPredictor self.input_queue before put, size: {qsize} / {maxsize}".format(
        #            qsize=self.input_queue.qsize(), maxsize=self.input_queue.maxsize))

        self.input_queue.put((dp, f))
        return f
