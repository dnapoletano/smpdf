# -*- coding: utf-8 -*-
from __future__ import division

"""
Created on Tue Apr 28 12:13:00 2015

@author: zah
"""
""" SMPDF """

__author__ = 'Stefano Carrazza'
__license__ = 'GPL'
__version__ = '1.0.0'
__email__ = 'stefano.carrazza@mi.infn.it'

import os
import os.path as osp
import sys
import functools
import glob
from collections import defaultdict, OrderedDict

import yaml
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.cbook import violin_stats
import matplotlib.patches
import scipy

from lhaindex import parse_info
from plotutils import ax_or_gca, violin_stats_from_dist, get_accent_colors
try:
    sys.path.append('applwrap')
    from applwrap import loadpdf, convolute
except ImportError:
    os.system("make -C applwrap")
    from applwrap import loadpdf, convolute

#TODO: Do we really want a subclass of dict?
class Config(dict):
    @classmethod
    def from_params(cls, **params):
        if 'pdfsets' not in params or not params['pdfsets']:
            raise ValueError("'pdfsets' not found in configuration.")
        #TODO make pdf a class
        for pdf in params['pdfsets']:
            #TODO: Do we allow incomplete sets at all? Seems like asking for
            #bugs.
            if not 'reps' in pdf or pdf['reps']=='all':
                pdf['reps'] = range(parse_info(pdf['name'])['NumMembers'])
            elif isinstance(pdf['reps'], int):
                pdf['reps'] = [pdf['reps']]
            elif isinstance(pdf['reps'], dict):
                pdf['reps'] = range(pdf['reps']['min'], pdf['reps']['max'])


        observables = []
        for obs in params['observables']:
             names = glob.glob(obs['name'])
             for name in names:
                 observables.append(Observable(name, obs['order']))
        params['observables'] = observables
        return cls(**params)

    @classmethod
    def from_yaml(cls, stream):
        return cls.from_params(**yaml.load(stream))

class Observable():
    def __init__(self, name, order):
        self.filename = name
        self.order = order

    @property
    def name(self):
        return osp.splitext(osp.basename(self.filename))[0]

    def __str__(self):
        return self.name

    def __repr__(self):
        return "<%s:%s>" % (self.__class__.__name__, self.__str__())

    def get_key(self):
        return (self.name, self.order)

    def __hash__(self):
        return hash(self.get_key())

    def __eq__(self, other):
        return (isinstance(other, self.__class__)
                and self.get_key() == other.get_key())


#TODO: Decide if we really want this
def _check_central(f):
    @functools.wraps(f)
    def _f(self, *args, **kwargs):
        if not 0 in self._data:
            raise ValueError("No results for central value (Member 0) "
                             "provided")
        return f(self, *args, **kwargs)
    return _f

class Result():
    def __init__(self, obs, pdf, data):
        self.obs = obs
        self.pdf = pdf
        self._data = pd.DataFrame(data)

    @property
    @_check_central
    def central_value(self):
        return self._cv

    @property
    def _cv(self):
        return self._data[0]

    @property
    def _all_vals(self):
        return self._data.iloc[:,1:]

    @property
    def nrep(self):
        return self._all_vals.shape[1]

    def std_error(self, nsigma=1):
        raise NotImplementedError("No error computation implemented for this"
                                  "type of set")

    def sample_values(self, n):
        raise NotImplementedError("No sampling implemented for this"
                                  "type of set")

    @_check_central
    def std_interval(self, nsigma=1):
        std = self.std_error(nsigma)
        return pd.DataFrame({'min':self._cv - std,
                             'max':self._cv + std})

    def __getitem__(self, item):
        return self._data[item]

    #TODO: Should this be the default iterator?
    def iterall(self):
        return iter(self._data)

    def _violin_data(self):
        absdata = pd.concat(self.sample_values(1000),axis=1)
        reldata = absdata.as_matrix().T
        return reldata
    #TODO: Move to plotutils
    @ax_or_gca
    def violin_plot(self, data = None, ax=None, **kwargs):
        if data is None:
            data = self._violin_data()

        myargs = {'label': str(self.pdf)}
        myargs.update(kwargs)
        if 'color' in myargs:
            color = myargs.pop('color')
        else:
            color = None
        if 'label' in myargs:
            label = myargs.pop('label')
        else:
            label = str(self.pdf)
        
        if 'hatches' in myargs:
            hatches = myargs.pop('hatches')
        else:
            hatches = None
            
        if isinstance(data, tuple):
            stats = violin_stats_from_dist(*data)
            vp = ax.violin(stats, **myargs)
        else:
            vp = ax.violinplot(data, **myargs)
        
        for pc in vp['bodies']:
            if color:
                
                if len(color) == 4:
                    pc.set_alpha(color[3])
                pc.set_facecolor(color)
            if hatches:
                pc.set_hatches(hatches)
        if label:
            if not color:
                color =  vp['bodies'][0].get_facecolor()
            vp['bodies'][0].set_label(label)
            handle = matplotlib.patches.Patch(color=color, label=label,
                                              hatch=hatches)
            print(color)

        return vp, handle



class SymHessianResult(Result):

    @_check_central
    def std_error(self, nsigma=1):
        diffsq = (self._all_vals.subtract(self._cv, axis=0))**2
        return diffsq.sum(axis=1).apply(np.sqrt)*nsigma

    def sample_values(self, n):
        diffs = self._all_vals.subtract(self._cv, axis=0)
        for _ in range(n):
            weights = np.random.normal(size=self.nrep)
            error = (diffs*weights).sum(axis=1)
            yield self._cv + error

#TODO: Fix this
#==============================================================================
#     def _violin_data(self):
#         std = self.std_error()
#         mean = self.central_value.as_matrix()
#         dist = scipy.stats.norm(mean,
#                                    std)
#         coords = np.linspace(mean - 3*std, mean+3*std, 1000)
#         vals = dist.pdf(coords)
#         return coords, vals
#==============================================================================




class MCResult(Result):
    #TODO: Is it correct to consider each bin as independant here?
    @_check_central
    def centered_interval(self, percent=68):
        n = percent*self.nrep//100
        def get_lims(row):
            s = np.argsort(np.abs(row))
            sel = row[s][:n]
            return pd.Series({'min':np.min(sel), 'max':np.max(sel)})

        diffs = self._all_vals.subtract(self._cv, axis=0)
        return diffs.apply(get_lims, axis=1).add(self._cv, axis=0)

    @property
    @_check_central
    def std_error(self, nsigma=1):
        return self._all_vals.std(axis=1)*nsigma

    def sample_values(self, n):
        for _ in range(n):
            col = np.random.choice(self._all_vals.columns)
            yield self._all_vals[col]

    def _violin_data(self):
        return self._all_vals.as_matrix().T
    
def aggregate_results(results):
    combined = defaultdict(lambda: {})
    for result in results:
        combined[result.obs][result.pdf] = result
    return combined

def compare_violins(results, base_pdf = None):
    if not isinstance(results, dict):
        combined = aggregate_results(results)
    else:
        combined = results
    for obs in combined:
        figure = plt.figure()
        handles = []
        plt.title(str(obs))
        colors = iter(get_accent_colors(len(combined[obs])).mpl_colors)
        alpha = 1
        base = combined[obs][base_pdf]
        results = sorted(combined[obs].values(), key = lambda x: x!=base)
        for result in results:
            data = result._violin_data()
            if base is not None:
                data /= base.central_value.as_matrix()
            color = next(colors) + (alpha,)
            alpha /= 2
            plot, handle = result.violin_plot(data, color=color,
                                              showextrema=False)
            handles.append(handle)
        plt.xlabel('bins')
        plt.ylabel('Rel to %s' % base_pdf)
        plt.xticks(range(1,len(result.central_value) + 1))
        plt.legend(handles=handles, loc='best')
        yield obs, figure


RESULT_TYPES = defaultdict(lambda:Result,
                           symmhessian = SymHessianResult,
                           replicas   = MCResult,
                           )

def make_result(obs, pdf_name, datas):
    error_type = parse_info(pdf_name)['ErrorType']
    return RESULT_TYPES[error_type](obs, pdf_name, datas)


def make_convolution(pdf, observables):
    datas = defaultdict(lambda:OrderedDict())
    #TODO: load many replicas in C++
    #TODO: Could we loop over observables and then over memebers?
    for rep in pdf['reps']:
        for obs in observables:
            #TODO: hide this call from the api, do in convolute.
            loadpdf(pdf['name'], rep)
            res = convolute(obs.filename, obs.order)
            datas[obs][rep] = np.array(res)
    return datas

def results_from_datas(dataset):
    results = []
    for pdf in dataset:
        data = dataset[pdf]
        results += [make_result(obs, pdf, data[obs]) for obs in data]
    return results

def get_dataset(pdfsets, observables, db=None):
    dataset = OrderedDict()
    for pdf in pdfsets:
        #bool(db) == False if empty
        if db is not None:
            key = str((pdf['name'], tuple(obs.get_key()
                       for obs in observables)))
            if key in db:
                res = db.get(key)
            else:
                res = make_convolution(pdf, observables)
                db[key] = dict(res)
        else:
            res = make_convolution(pdf, observables)

        #TODO: Make key the real pdf class, instead of name
        dataset[pdf['name']] = res
    return dataset

def convolve_or_load(pdfsets, observables, db=None):
    #results = []
    results = results_from_datas(get_dataset(pdfsets, observables, db))
    return results