import mincepy
from mincepy.testing import *
from mincepy import builtins

# region lists


def test_ref_list(historian: mincepy.Historian):
    """Test references list"""
    list1 = mincepy.RefList()
    list2 = mincepy.RefList()
    car = Car()
    list1.append(car)
    list2.append(car)

    # Test iteration
    for entry in list1:
        assert entry is car

    # Reference condition satisfied
    assert list1[0] is list2[0]

    # Now delete everything, reload, and make sure the condition is still satisfied
    list1_id, list2_id = historian.save(list1, list2)
    del list1, list2, car

    list1_loaded = historian.load(list1_id)
    list2_loaded = historian.load(list2_id)
    assert len(list1_loaded) == 1
    assert len(list2_loaded) == 1
    assert isinstance(list1_loaded[0], Car)
    assert list1_loaded[0] is list2_loaded[0]


def test_ref_list_primitives(historian: mincepy.Historian):
    """Test that we can store primitives in a ref list also"""
    reflist = mincepy.RefList()
    reflist.append(5)
    reflist.append('hello')
    reflist.append(10.8)

    reflist_id = reflist.save()
    del reflist

    loaded = historian.load(reflist_id)
    assert loaded[0] == 5
    assert loaded[1] == 'hello'
    assert loaded[2] == 10.8


def test_live_lists(historian: mincepy.Historian):
    """Basic tests on live list. It's difficult to test the 'syncing' aspects
    of this container without another process"""
    for list_type in (builtins.LiveList, builtins.LiveRefList):
        live_list = list_type()

        car = Car()

        live_list.append(car)
        wrapper_id = live_list.save()
        del live_list

        live_list = historian.load(wrapper_id)
        assert len(live_list) == 1

        # Test getitem
        live_list.append(Car('honda'))
        live_list.append(Car('fiat'))
        assert live_list[2].make == 'fiat'

        # Test delete
        del live_list[2]
        assert len(live_list) == 2


def test_ref_list_none(historian: mincepy.Historian):
    """Test that we can store None in a ref list."""
    lrlist = mincepy.RefList()
    lrlist.append(None)
    assert lrlist[-1] is None
    lrdict_id = lrlist.save()
    del lrlist

    loaded = historian.load(lrdict_id)  # type: mincepy.RefList
    assert loaded[-1] is None


# endregion

# region dict


def test_ref_dict(historian: mincepy.Historian):
    """Test that the ref dict correctly stores entries as references"""
    dict1 = mincepy.builtins.RefDict()
    dict2 = mincepy.builtins.RefDict()
    car = Car()
    dict1['car'] = car
    dict2['car'] = car

    # Test iteration
    for key, value in dict1.items():
        assert key == 'car'
        assert value is car

    # Reference condition satisfied
    assert dict1['car'] is dict2['car']

    # Now delete everything, reload, and make sure the condition is still satisfied
    dict1_id, dict2_id = historian.save(dict1, dict2)
    del dict1, dict2, car

    dict1_loaded = historian.load(dict1_id)
    dict2_loaded = historian.load(dict2_id)
    assert len(dict1_loaded) == 1
    assert len(dict2_loaded) == 1
    assert isinstance(dict1_loaded['car'], Car)
    assert dict1_loaded['car'] is dict2_loaded['car']


def test_ref_dict_primitives(historian: mincepy.Historian):
    """Test that we can store primitives in a ref list also"""
    refdict = mincepy.RefDict()
    refdict['0'] = 5
    refdict['1'] = 'hello'
    refdict['2'] = 10.8

    reflist_id = refdict.save()
    del refdict

    loaded = historian.load(reflist_id)
    assert loaded['0'] == 5
    assert loaded['1'] == 'hello'
    assert loaded['2'] == 10.8


def test_live_dicts(historian: mincepy.Historian):
    """Test live dictionary, difficult to test the sync capability"""
    for dict_type in (builtins.LiveDict, builtins.LiveRefDict):
        dict1 = dict_type()
        dict2 = dict_type()
        car = Car('mini', 'green')
        dict1['car'] = car
        dict2['car'] = car

        # Reference condition satisfied
        assert dict1['car'] is dict2['car']

        # Now delete everything, reload, and make sure the condition is still satisfied
        dict1_id, dict2_id = historian.save(dict1, dict2)
        del dict1, dict2, car

        dict1_loaded = historian.load(dict1_id)
        dict2_loaded = historian.load(dict2_id)
        assert len(dict1_loaded) == 1
        assert len(dict2_loaded) == 1
        assert isinstance(dict1_loaded['car'], Car)
        assert dict1_loaded['car'] == dict2_loaded['car']


def test_live_ref_dict(historian: mincepy.Historian):
    dict1 = builtins.LiveRefDict()
    dict2 = builtins.LiveRefDict()
    car = Car('mini', 'green')
    dict1['car'] = car
    dict2['car'] = car

    # Reference condition satisfied
    assert dict1['car'] is dict2['car']

    # Now delete everything, reload, and make sure the condition is still satisfied
    dict1_id, dict2_id = historian.save(dict1, dict2)
    del dict1, dict2, car

    dict1_loaded = historian.load(dict1_id)
    dict2_loaded = historian.load(dict2_id)
    assert len(dict1_loaded) == 1
    assert len(dict2_loaded) == 1
    assert isinstance(dict1_loaded['car'], Car)
    # Check they are the same object
    assert dict1_loaded['car'] is dict2_loaded['car']


def test_ref_dict_none(historian: mincepy.Historian):
    """Test that we can store None in a ref dict."""
    lrdict = mincepy.LiveRefDict()
    lrdict['test'] = None
    assert lrdict['test'] is None
    lrdict_id = lrdict.save()
    del lrdict

    loaded = historian.load(lrdict_id)  # type: mincepy.RefDict
    assert loaded['test'] is None


# endregion


def test_live_ref_create(historian: mincepy.Historian):
    car = Car('mini', 'green')
    lrdict = builtins.LiveRefDict({'car': car})
    lrdict['car'] = car

    # Now delete everything, reload, and make sure the condition is still satisfied
    dict1_id = historian.save(lrdict)
    car_id = lrdict['car'].obj_id
    assert car_id is not None
    del lrdict, car

    rldict_loaded = historian.load(dict1_id)
    assert len(rldict_loaded) == 1
    assert isinstance(rldict_loaded['car'], Car)
    # Check they are the same object
    assert rldict_loaded['car'].obj_id == car_id


def test_live_ref_lists(historian: mincepy.Historian):
    """Basic tests on live list. It's difficult to test the 'syncing' aspects
    of this container without another process"""
    live_list = builtins.LiveRefList()

    car = Car()

    live_list.append(car)
    wrapper_id = live_list.save()
    car_id = car.obj_id
    assert car_id is not None
    del live_list

    live_list = historian.load(wrapper_id)
    assert len(live_list) == 1

    # Test getitem
    live_list.append(Car('honda'))
    live_list.append(Car('fiat'))
    assert live_list[2].make == 'fiat'

    assert car.obj_id == car_id

    # Test delete
    del live_list[2]
    assert len(live_list) == 2


def test_file_from_disk(tmp_path, historian: mincepy.Historian):
    disk_file_path = tmp_path / 'test.txt'
    disk_file_path.write_text('TEST')
    file = historian.create_file('test.txt')
    file.from_disk(disk_file_path)
    contents = file.read_text()
    assert contents == 'TEST'


def test_file_to_disk(tmp_path, historian: mincepy.Historian):
    disk_file_path = tmp_path / 'test.txt'

    file = historian.create_file('test.txt')
    file.write_text('TEST')

    file.to_disk(tmp_path)

    assert disk_file_path.read_text() == 'TEST'
