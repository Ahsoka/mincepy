import pymongo
import pytest

import mincepy

from . import common


@pytest.fixture
def mongodb_archive():
    client = pymongo.MongoClient()
    db = client.test_database
    mongo_archive = mincepy.mongo.MongoArchive(db)
    yield mongo_archive
    client.drop_database(db)


@pytest.fixture
def historian(mongodb_archive):
    hist = mincepy.Historian(mongodb_archive)
    hist.register_types(common.HISTORIAN_TYPES)
    mincepy.set_historian(hist)
    yield hist
    mincepy.set_historian(None)
