import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.dirname(__file__))
from get_data import get_data
from models.active_model import ActiveLearningExperiment
from models.strategy import random_query
from models.utils import ObstructedY
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score
import copy
from sacred import Experiment
from misc.config import *
from kaggle_ninja import *
from utils import ExperimentResults

ex = Experiment('random_query')


@ex.config
def my_config():
    batch_size = 10
    seed = 778
    timeout = -1
    force_reload = False

@ex.capture
def run(batch_size, seed, _log):
    time.sleep(2)

    comp = [['5ht7', 'ExtFP']]
    loader = ["get_splitted_data",
              {"n_folds": 3,
               "seed":seed,
               "test_size":0.1}]
    preprocess_fncs = []

    sgd = SGDClassifier(random_state=seed)
    model = ActiveLearningExperiment(strategy=random_query, base_model=sgd, batch_size=batch_size)

    folds, test_data, data_desc = get_data(comp, loader, preprocess_fncs).values()[0]
    _log.info(data_desc)

    X = folds[0]['X_train']
    y = ObstructedY(folds[0]['Y_train'])

    X_test = folds[0]['X_valid']
    y_test = folds[0]['Y_valid']

    model.fit(X,y)

    p = model.predict(X_test)
    return ExperimentResults(results={"acc": accuracy_score(p, y_test)}, monitors={}, dumps={})


## Needed boilerplate ##

@ex.main
def main(timeout, force_reload, _log):
    # Load cache unless forced not to
    cached_result = try_load() if not force_reload else None
    if cached_result:
        _log.info("Reading from cache "+ex.name)
        return cached_result
    else:
        if timeout > 0:
            result = abortable_worker(run, timeout=timeout)
        else:
            result = run()
        save(result)
        return result

@ex.capture
def save(results, _config, _log):
    _log.info(results)
    _config_cleaned = copy.deepcopy(_config)
    del _config_cleaned['force_reload']
    ninja_set_value(value=results, master_key=ex.name, **_config_cleaned)

@ex.capture
def try_load(_config, _log):
    _config_cleaned = copy.deepcopy(_config)
    del _config_cleaned['force_reload']
    return ninja_get_value(master_key=ex.name, **_config_cleaned)

if __name__ == '__main__':
    ex.logger = get_logger("al_ecml")
    results = ex.run_commandline().result
    save(results)