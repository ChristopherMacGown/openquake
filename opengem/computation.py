# vim: tabstop=4 shiftwidth=4 softtabstop=4

from eventlet import event
from eventlet import queue


class Computation(object):
    def __init__(self, pool, cell, keys=None):
        self.pool = pool
        self.cell = cell
        self.result = event.Event()

        if keys is None:
            keys = []

        self._data = {}
        for k in keys:
            self._data[k] = event.Event()
    
    def receive(self, key, _data):
        self._data[key].send(_data)

    def compute(self):
        # wait on all input
        data = dict([(k, v.wait()) for k, v in self._data.iteritems()])
        
        # do the computation
        result = self._compute(**data)

        # send to finished
        self.result.send((self.cell, result))
        return (self.cell, result)

    def _compute(self, **kw):
        """Do the actual computation"""
        raise NotImplementedError


class Grid(object):
    def __init__(self, pool, cell_factory):
        self.pool = pool
        self.cell_factory = cell_factory
        self._cells = {}
        self._queue = queue.Queue()

    def cell(self, key):
        if key not in self._cells:
            self._cells[key] = self._new_cell(key)
        return self._cells[key]

    def _new_cell(self, key):
        cell = self.cell_factory(self.pool, key)
        self.pool.spawn(cell.compute)
        self._queue.put(cell.result)
        return cell
    
    def results(self, clear=False):
        while not self._queue.empty():
            cell, result = self._queue.get().wait()
            yield (cell, result)
            if clear:
                del self._cells[cell]

    def size(self):
        return len(self._cells)