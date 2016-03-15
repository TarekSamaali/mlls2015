import json
import cPickle
import gzip

import os
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import logging
import traceback

from collections import defaultdict, OrderedDict
from itertools import product

from misc.config import RESULTS_DIR, CACHE_DIR
from experiments.utils import dict_hash

import pdb

logger = logging.getLogger(__name__)


RES_FINGERPRINTS = ['Pubchem', 'Ext', 'Klek']
RES_STRATEGIES = [ 'PassiveStrategy', 'UncertaintySampling', 'QueryByBagging' ,'QuasiGreedyBatch', 'CSJSampling']
RES_COMPOUNDS = ['5-HT1a']


### stuff for analyzing results ###

def save_numpy(content, file_path):
    with open(file_path, 'w') as f:
        np.savez(f, **content)

def save_json(content, file_path):
    with open(file_path, 'w') as f:
        json.dump(content, f)

def load_json(file_path):
    """
    Loads json file to python dict
    :param file_path: string, path ot file
    :return: dict, python dictionary with json contents
    """
    with open(file_path, 'r') as f:
        content = json.load(f)
    return content


def load_pklgz(file_path):
    """
    Load .pkl.gz file from file to python dict
    :param file_path: string, path ot file
    :return: dict, python dictionary with file contents
    """
    with gzip.open(file_path, 'r') as f:
        content = cPickle.load(f)
    return content


def get_mean_experiments_results(results_dir, strategies, batch_sizes=[20, 50, 100]):
    """
    Read all experiments from given directory, calculated mean results for all combinations of
    strategies and batch_sizes
    :param results_dir: string, path to directiory with results
    :param batch_sizes: list of ints, batch sizes the experiments were run on
    :param strategies: string, strategies the experimtens were run on, default 'all'
    :return: dict of dicts: {strategy-batchsize: {metric: mean_results}}
    """

    assert isinstance(strategies, str)

    if strategies == 'unc':
        strategies = ['UncertaintySampling', 'PassiveStrategy']
    else:
        assert results_dir.split("-")[-1] == strategies.split("-")[-1]
        strategies = [strategies]

    mean_scores = {strategy + '-' + str(batch_size): defaultdict(list) for strategy in strategies for batch_size in batch_sizes}

    for results_file in filter(lambda x: x[-4:] == 'json', os.listdir(results_dir)):

        json_path = os.path.join(results_dir, results_file)
        assert os.path.exists(json_path)

        json_results = load_json(json_path)
        strategy = json_results['opts']['strategy']
        batch_size = json_results['opts']['batch_size']

        if strategy in ["CSJSampling", "QuasiGreedyBatch"]:
            strategy_kwargs = json.loads(json_results['opts']['strategy_kwargs'])
            param_c = strategy_kwargs['c']
            key = strategy + "-"  + str(param_c) + '-' + str(batch_size)
        elif strategy == "QueryByBagging":
            strategy_kwargs = json.loads(json_results['opts']['strategy_kwargs'])
            param_k = strategy_kwargs['n_estimators']
            key = strategy + "-"  + str(param_k) + '-' + str(batch_size)
        else:
            key = strategy + '-' + str(batch_size)

        assert key in mean_scores

        for metric, score in json_results['scores'].iteritems():
            mean_scores[key][metric].append(score)

        pkl_path = os.path.join(results_dir, results_file[:-5] + ".pkl.gz")
        assert os.path.exists(pkl_path)

        scores = load_pklgz(pkl_path)

        for metric, values in scores.iteritems():
            mean_scores[key][metric].append(values)

    for strategy, scores in mean_scores.iteritems():
        for metric, values in scores.iteritems():
            if '_mon' in metric \
                    or '_predictions' in metric \
                    or '_true' in metric \
                    or 'selected_' in metric:
                continue

            if '_auc' not in metric and '_mean' not in metric:
                values = adjust_results(values)

            try:
                if '_auc' in metric or '_mean' in metric:
                    mean_scores[strategy][metric] = np.mean(values)
                else:
                    mean_scores[strategy][metric] = np.vstack(values).mean(axis=0)
            except Exception as e:
                traceback.format_exc(e)
                pdb.set_trace()

            if '_auc' in metric or '_mean' in metric:
                assert isinstance(mean_scores[strategy][metric], float)
            else:
                assert mean_scores[strategy][metric].shape[0] > 1

    return mean_scores


def adjust_results(values):

    assert isinstance(values, list)

    min_length = len(values[0])
    fix = False
    for v in values:
        assert isinstance(v, list)
        if len(v) != min_length:
            if len(v) < min_length:
                min_length = len(v)
            fix = True

    if fix:
        for i, v in enumerate(values):
            values[i] = np.array(v)[:min_length]

    return values


def pick_best_param_k_experiment(results_dir, metric):

    assert "_auc" in metric or "_mean" in metric


    result_dirs = [os.path.join(results_dir, 'qbb' + '-' + str(k)) for k in [2, 3, 5, 10, 15]]

    best_result = {str(bs): ("", {}, 0.) for bs in [20, 50, 100]}
    for res_dir in result_dirs:
        qbb_k = res_dir.split("-")[-1]
        mean_res = get_mean_experiments_results(res_dir, strategies="QueryByBagging" + "-" + qbb_k)
        for strat, scores in mean_res.iteritems():
            batch_size = strat.split('-')[-1]
            if metric not in scores.keys():
                raise ValueError("Worng metric: %s" % metric)

            if scores[metric] > best_result[batch_size][2]:
                best_result[batch_size] = (strat, scores, scores[metric])

    ret = {}
    for bs, (strat, scores, best_score) in best_result.iteritems():
        ret[strat] = scores
    return ret


def pick_best_param_c_experiment(results_dir, strategy, metric):

    assert strategy in ["CSJSampling", "QuasiGreedyBatch"]
    assert "_auc" in metric or "_mean" in metric

    if strategy == 'CSJSampling':
        short_strat = 'csj'
    elif strategy == 'QuasiGreedyBatch':
        short_strat = 'qgb'

    result_dirs = [os.path.join(results_dir, short_strat + '-' + str(c)) for c in np.linspace(0.3, 0.7, 5)]

    best_result = {str(bs): ("", {}, 0.) for bs in [20, 50, 100]}
    for res_dir in result_dirs:
        mean_res = get_mean_experiments_results(res_dir, strategies=strategy + res_dir[-4:])
        for strat, scores in mean_res.iteritems():
            batch_size = strat.split('-')[-1]
            if metric not in scores.keys():
                raise ValueError("Worng metric: %s" % metric)

            if scores[metric] > best_result[batch_size][2]:
                best_result[batch_size] = (strat, scores, scores[metric])

    ret = {}
    for bs, (strat, scores, best_score) in best_result.iteritems():
        ret[strat] = scores

    return ret


def curves(scores, metrics=['wac_score_valid'], batch_sizes=[20, 50, 100]):
    """
    Plot curves from given mean scores and metrics
    :param scores: dict of dicts, mean scores for every combination of params
    :param metrics: list of strings or string, which metrics to plot
    :param batch_sizes: list of ints, batch sizes the experiments were run on
    :return:
    """

    if isinstance(metrics, str):
        metrics = [metrics]

    fig, axes = plt.subplots(len(metrics) * len(batch_sizes), 1)
    fig.set_figwidth(15)
    fig.set_figheight(8 * len(axes))

    exp_type = product(batch_sizes, metrics)

    scores = OrderedDict(sorted(scores.items()))

    # plot all passed metrics
    for ax, (batch_size, metric) in zip(axes, exp_type):
        for strategy, score in scores.iteritems():
            if strategy.split('-')[-1] == str(batch_size):
                strategy_name = "-".join(strategy.split('-')[:-1])
                pd.DataFrame({strategy_name: score[metric]}).plot(title='%s %d batch size' % (metric, batch_size), ax=ax)
                ax.legend(loc='best', bbox_to_anchor=(1.0, 0.5))


def process_results(results_dir, best_param_metric, force_recalc=False):
    """
    Process experiment results into ploting-friendly data while picking best strategies parameters
    :param results_dir: string, path to results directory
    :param best_param_metric: string, which metric to choose for picking best strategy params
    :param force_recalc: boolean, if True it will process results even if cache file already exists
    :return:
    """
    name = dict_hash({'path': results_dir, 'best_param_metric': best_param_metric})
    cache_file = os.path.join(CACHE_DIR, "experiments.analyze", name + ".npz")

    if not os.path.exists(cache_file) or force_recalc:

        print("Processing results for `%s` and metric `%s`" % (results_dir, best_param_metric))
        # unc and passive
        mean_scores = {}
        unc_dir = os.path.join(results_dir, "unc")
        all_scores = get_mean_experiments_results(unc_dir, strategies='unc')
        mean_scores.update(all_scores)

        print("\t Uncertainty and Passive done")

        # qbb
        best_strat_qbb = pick_best_param_k_experiment(results_dir, metric=best_param_metric)
        for key in best_strat_qbb.keys():
            assert key not in mean_scores.keys()
        mean_scores.update(best_strat_qbb)

        print("\t QBB done")

        # csj and qgb
        for strategy in ["CSJSampling", "QuasiGreedyBatch"]:
            best_strat_res = pick_best_param_c_experiment(results_dir, strategy, metric=best_param_metric)
            for key in best_strat_res.keys():
                assert key not in mean_scores.keys()
            mean_scores.update(best_strat_res)

        print("\t CSJ and QGB done")

        save_numpy(mean_scores, cache_file)
    else:
        print("Results for `%s` and metric `%s` already processed" % (results_dir, best_param_metric))


def plot_curves(results_dir, metrics, best_param_metric):
    """
    Plots curves for mean results off all experiments in given directory for given metrics
    :param results_dir: string, path to results directory, determines compound and fingerprint
    :param metrics: list of strings or string, which metrics to plot
    :return:
    """

    name = dict_hash({'path': results_dir, 'best_param_metric': best_param_metric})
    cache_file = os.path.join(CACHE_DIR, "experiments.analyze", name + ".pkl.gz")

    mean_scores = load_pklgz(cache_file)

    curves(mean_scores, metrics=metrics)

def get_all_pickle_results(results_dir):
    """
    Loads all results in .pkl.gz files in given directory
    :param results_dir: string, directory with saved results
    :return: dict, file_path: results_dict
    """

    pickle_results = {}

    for pickle_file in filter(lambda x: 'pkl.gz' in x, os.listdir(results_dir)):
        results = load_pklgz(os.path.join(results_dir, pickle_file))

        pickle_results[pickle_file] = results

    return pickle_results


def check_extreme_params_all_results():
    """
    Checks if AdaptiveGridSearchCV picked an extreme parameter as best in WHOLE results directory
    :return: None
    """
    logger.warning("This may take at least a minute!")
    for results_dir in filter(lambda x: 'SVM' in x, os.listdir(RESULTS_DIR)):
        check_extreme_params(os.path.join(RESULTS_DIR, results_dir))


def check_extreme_params(results_dir):
    """
    Checks if AdaptiveGridSearchCV picked an extreme parameter as best in given results directory
    :param results_dir: string, directory with saved results
    :return: None
    """

    all_results = get_all_pickle_results(results_dir)
    found = False
    for i, pickle_results in enumerate(all_results):
        if not _single_check_for_extreme_params:
            logger.warning("Extreme params in %s" % pickle_results.keys())
            found = True

    if found:
        logger.warning( "FOUND SOME PICKED EXTREME PARAMETERS in %s" % results_dir)
    else:
        logger.info("No extreme params found in %s :)" % results_dir)


def _single_check_for_extreme_params(pickle_results, min_c=1e-6, max_c=1e5):
    """
    Check for extreme parameters in given results
    :param pickle_results: dict, experiment results
    :param min_c: float, minimum parameter value
    :param max_c: float, maximum parameter value
    :return: True if there were no extreme parameters picked, False if there were
    """

    best_params = []

    for params in pickle_results['grid_mon']:
        best_params.append(max(params, key=lambda x: x[1])[0].values())

    best_cs = np.unique(best_params)
    return min_c not in best_cs and max_c not in best_cs


def get_corresponding_experiment_results(exp_file, compare_results_dir):
    """
    Returns results of the experiment with the same name (same run parameters) in given directory
    :param exp_file: string, path to base experiment results
    :param compare_results_dir: string, directory in which to look for corresponding experiment
    :return: dict, results of corresponding experiment
    """

    assert exp_file[-4:] == "json"

    base_file_name = exp_file.split("/")[-1]
    file_path = os.path.join(compare_results_dir, base_file_name)
    assert os.path.exists(file_path)
    results = load_json(file_path)

    return results


def compare_json_results(exp_file, compare_results_dir):
    """
    Find and compare results of an experiment with the same parameters as given
    :param exp_file: string, path to base experiment results
    :param string, directory in which to look for corresponding experiment
    :return: None
    """

    base_results = load_json(exp_file)
    compare_results = get_corresponding_experiment_results(exp_file, compare_results_dir)

    assert base_results.keys() == compare_results.keys()

    # results will differ in:
    #    * run results - PID, slight code modification, etc.
    #    * time_reports - depending on machine load
    #    * scores - ONLY IN TIMES! Yes, there are times saved there
    for key in base_results.keys():
        if base_results[key] != compare_results[key]:
            assert key in ['run', 'time_reports', 'scores']

    # make sure differences in scores are only in times
    for (k1, s1), (k2, s2) in zip(base_results['scores'].iteritems(), compare_results['scores'].iteritems()):
        if abs(s1 - s2) > 0:
            assert 'time' in k1


def get_mean_expermients_score(results_dir, metric, batch_size):

    assert "_auc" in metric or "_mean" in metric
    assert isinstance(batch_size, int)

    strat_name = results_dir.split("/")[-1]

    if strat_name == "unc":
        mean_scores = {"UncertaintySampling": [], "PassiveStrategy": []}

        for json_file in filter(lambda x: "json" in x, os.listdir(results_dir)):
            json_path = os.path.join(results_dir, json_file)
            json_results = load_json(json_path)

            if json_results['opts']['batch_size'] != batch_size:
                continue

            strategy = json_results['opts']['strategy']


            assert strategy in mean_scores.keys()
            assert metric in json_results['scores'].keys()

            mean_scores[strategy].append(json_results['scores'][metric])

        for key, val in mean_scores.iteritems():
            mean_scores[key] = np.mean(val)

        return mean_scores

    else:
        if strat_name.split("-")[0] == "csj":
            key = "CSJSampling-" + strat_name.split("-")[1]
        elif strat_name.split("-")[0] == "qgb":
            key = "QuasiGreedyBatch-" + strat_name.split("-")[1]
        elif strat_name.split("-")[0] == "qbb":
            key = "QueryByBagging-" + strat_name.split("-")[1]
        else:
            raise ValueError("Can't parse strategy name out of results dir: %s" % results_dir)

        mean_score = []
        for json_file in filter(lambda x: "json" in x, os.listdir(results_dir)):
            json_path = os.path.join(results_dir, json_file)
            json_results = load_json(json_path)

            if json_results['opts']['batch_size'] != batch_size:
                continue

            assert metric in json_results['scores'].keys()
            mean_score.append(json_results['scores'][metric])

        mean_score = np.mean(mean_score)

        return {key: mean_score}


def collect_mean_scores(results_dir, metric, batch_size, fingerprints='all'):

    assert isinstance(fingerprints, str) or isinstance(fingerprints, list)
    if fingerprints == 'all':
        fingerprints = ['Pubchem', 'Klek', 'Ext']
    else:
        assert isinstance(fingerprints, list)

    mean_scores = {fp: {} for fp in fingerprints}
    for fp in fingerprints:
        fp_results_dir = os.path.join(results_dir, fp)
        for res_dir in os.listdir(fp_results_dir):
            res_dir = os.path.join(fp_results_dir, res_dir)
            scores = get_mean_expermients_score(res_dir, metric=metric, batch_size=batch_size)
            mean_scores[fp].update(scores)

    return mean_scores


def count_wins(results_dir, metric, compounds='all', fingerprints='all', batch_sizes='all'):

    if batch_sizes == 'all':
        batch_sizes = [20, 50, 100]
    else:
        assert isinstance(batch_sizes, list)

    if compounds == 'all':
        compounds = ["5-HT2c", "5-HT2a", "5-HT6", "5-HT7", "5-HT1a", "d2"]
    else:
        assert isinstance(compounds, list)

    wins = defaultdict(int)


    for bs in batch_sizes:
        for compound in compounds:
            res_dir = os.path.join(results_dir, compound)
            mean_scores = collect_mean_scores(res_dir, metric=metric, batch_size=bs, fingerprints=fingerprints)
            for fp, scores in mean_scores.iteritems():
                try:
                    best_strategy = scores.keys()[np.argmax(scores.values())]
                except:
                    pdb.set_trace()
                wins[best_strategy] += 1

    return wins

### Time utils

def get_all_time_reports(compound, fingerprint, model='SVM'):
    path = os.path.join(RESULTS_DIR, model, compound, fingerprint)
    strategies = RES_STRATEGIES
    time_reports = {strategy: [] for strategy in strategies}

    for strat_dir in os.listdir(path):
        for json_file in filter(lambda x: '.json' in x, os.listdir(os.path.join(path, strat_dir))):
            json_path = os.path.join(path, strat_dir, json_file)
            res = load_json(json_path)
            strat = res['opts']['strategy']
            time_reports[strat].append(res['time_reports'])

    return time_reports


def get_mean_time_reports(compound, fingerprint, model='SVM'):

    strategies = RES_STRATEGIES
    time_reports = get_all_time_reports(compound=compound, fingerprint=fingerprint, model=model)
    mean_time_reports = {strategy: defaultdict(list) for strategy in strategies}

    for strat, reports in time_reports.iteritems():
        for report in reports:
            for key, val in report.iteritems():
                if isinstance(val, list):
                    assert len(val) == 2
                    val = val[0]
                assert isinstance(val, float)
                mean_time_reports[strat][key].append(val)

        for key, val in mean_time_reports[strat].iteritems():
            assert isinstance(val, list)
            mean_time_reports[strat][key] = np.mean(val)

    return mean_time_reports


def to_pandas(time_reports):
    strategies = RES_STRATEGIES
    pandas_time_reports = {strategy: defaultdict(list) for strategy in strategies}
    for strat, reports in time_reports.iteritems():
        for key, val in reports.iteritems():
            pandas_time_reports[strat][key] = pd.to_timedelta(val, unit='s')

    df = pd.DataFrame.from_dict(pandas_time_reports)
    cols = ['QuasiGreedyBatch', 'CSJSampling', 'QueryByBagging', 'UncertaintySampling', 'PassiveStrategy']
    df = df[cols].sort_values(by=cols, ascending=False)
    return df