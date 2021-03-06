import unittest
import sys
sys.path.append("..")
import kaggle_ninja
kaggle_ninja.turn_off_cache()

from misc.utils import *
from misc.config import c


class TestUtils(unittest.TestCase):

    def setUp(self):
        self.data_dir = c["DATA_DIR"]

    def test_list_data(self):
        data = list_all_data()
        data_files = filter( lambda x: x.split('.')[1] == 'libsvm', os.listdir(self.data_dir))
        self.assertEqual(len(data), len(data_files))


if __name__ == "__main__":
    unittest.main()