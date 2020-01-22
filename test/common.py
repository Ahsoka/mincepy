import bson

import mincepy


class Car(mincepy.SavableComparable):
    TYPE_ID = bson.ObjectId('5e075d6244572f823ed93274')

    def __init__(self, make='ferrari', colour='red'):
        super(Car, self).__init__()
        self.make = make
        self.colour = colour

    def __eq__(self, other):
        if type(other) != Car:
            return False

        return self.make == other.make and self.colour == other.colour

    def yield_hashables(self, hasher):
        yield from hasher.yield_hashables(self.make)
        yield from hasher.yield_hashables(self.colour)

    def save_instance_state(self, _depositor: mincepy.Depositor):
        return {'make': self.make, 'colour': self.colour}

    def load_instance_state(self, saved_state, _depositor: mincepy.Depositor):
        self.__init__(saved_state['make'], saved_state['colour'])


class Garage(mincepy.SavableComparable):
    TYPE_ID = bson.ObjectId('5e07b40a44572f823ed9327b')

    def __init__(self, car=None):
        super(Garage, self).__init__()
        self.car = car

    def __eq__(self, other):
        if type(other) != Garage:
            return False

        return self.car == other.car

    def yield_hashables(self, hasher):
        yield from hasher.yield_hashables(self.car)

    def save_instance_state(self, _depositor: mincepy.Depositor):
        return {'car': self.car}

    def load_instance_state(self, saved_state, _depositor: mincepy.Depositor):
        self.__init__(saved_state['car'])
