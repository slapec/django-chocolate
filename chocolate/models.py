import generators
from django.db.models.fields.related import ManyToManyField, ForeignKey
from django.db.models.fields.related import ManyRelatedObjectsDescriptor
from django.db.models.fields.related import ForeignRelatedObjectsDescriptor
from django.db import models


FIELDCLASS_TO_GENERATOR = {
    models.BooleanField: generators.BooleanGenerator,
    models.DateField: generators.DateGenerator,
    models.DateTimeField: generators.DateTimeGenerator,
    models.EmailField: generators.EmailGenerator,
    models.IntegerField: generators.IntegerGenerator,
    models.FloatField: generators.FloatGenerator,
    models.IPAddressField: generators.IPAddressGenerator,
    models.NullBooleanField: generators.NullBooleanGenerator,
    models.PositiveIntegerField: generators.PositiveIntegerGenerator,
    models.PositiveSmallIntegerField: generators.PositiveSmallIntegerGenerator,
    models.SlugField: generators.SlugGenerator,
    models.SmallIntegerField: generators.SmallIntegerGenerator,
    models.TextField: generators.LoremGenerator,
    models.TimeField: generators.TimeGenerator,
    models.URLField: generators.URLGenerator,
    # field generators
    models.CharField: generators.CharFieldGenerator,
    models.DecimalField: generators.DecimalFieldGenerator,
    models.FilePathField: generators.FilePathFieldGenerator,
}

class UnregisteredModel(Exception):
    pass

def get_field_from_related_name(model_class, related_name):
    for field in model_class._meta.local_fields:
        try:
            if field.related.get_accessor_name() == related_name:
                return field
        except AttributeError:
            pass
    return None


class Factory(object):

    def __init__(self):
        self.mockups = {}

    def get_key(self, model):
        key = model
        if not isinstance(model, basestring):
            key = model.__name__
        return key.lower()

    def register(self, model):
        """Registers a model to allow mockup creations of that model."""

        key = self.get_key(model)
        self.mockups[key] = Mockup(model, self)

    def __getitem__(self, model):
        key = self.get_key(model)

        try:
            return self.mockups[key]
        except KeyError:
            raise UnregisteredModel(key)

class MockupData(object):

    def __init__(self, factory=None, force=None):
        self.data = {}
        self.force = force or {}
        self.factory = factory

        self.preset_forced()

    def preset_forced(self):
        """Sets the forced data onto the dataset."""

        self.data.update(self.force)

    def __getitem__(self, name):
        return self.data[name]

    def __setitem__(self, name, value):
        self.data[name] = value

    def __delitem__(self, name):
        del self.data[name]

    def update(self, data):
        return self.data.update(data)

    def to_dict(self):
        return self.data

    def set(self, name, constant=None, model=None):
        if name in self.force:
            #Already forced
            return

        if model is not None:
            obj = self.factory[model].create()
            self.data[name] = obj
            return

        if constant is not None:
            self.data[name] = constant
            return

    def get_data_dict(self, fields):
        data = {}

        for field in fields:
            try:
                data[field] = self[field]
            except KeyError:
                #we have no data for this field.
                pass

        return data

    def create_model(self, model_class):
        "Obtains an instance of the model using this data set."

        tomany_fields, regular_fields = self.get_fields(model_class)

        tomany_data = self.get_data_dict(tomany_fields)
        regular_data = self.get_data_dict(regular_fields)

        model = model_class(**regular_data)
        model.save()

        for tomany_field, values in tomany_data.items():
            manager = getattr(model, tomany_field)
            related_model =  manager.model

            reverse_related_name = get_field_from_related_name(related_model, tomany_field)

            if type(values) is int:
                objs = []
                for x in range(0, values):
                    if reverse_related_name is None:
                        data = {}
                    else:
                        data = {reverse_related_name.name: model}
                    objs.append(self.factory[related_model].create(**data))
                values = objs
            if type(values) is not list:
                values = [values]

            for value in values:
                manager.add(value)

        return model

    def get_fields(self, model_class):
        """Obtains a list of fields of the given model class separated
        between to-many and non-to-many (regular)"""

        many = []
        regular = []

        class_fields = model_class._meta.get_all_field_names()
        for field in class_fields:
            try:
                field_obj = model_class._meta.get_field(field)
                is_tomany = isinstance(field_obj, ManyToManyField)
            except Exception:
                try:
                    field_obj = getattr(model_class, field)
                    is_tomany = isinstance(field_obj,
                        ForeignRelatedObjectsDescriptor)
                    is_tomany = is_tomany or isinstance(field_obj, ManyRelatedObjectsDescriptor)
                except AttributeError:
                    #probably a to-many field with no reverse relationship
                    #defined
                    continue


            if is_tomany:
                many.append(field)
            else:
                regular.append(field)


        return many, regular

class Mockup(object):

    def __init__(self, model_class, factory):
        self.model_class = model_class
        self.factory = factory

    def create(self, **kwargs):
        """Creates a mockup object."""

        force = kwargs

        model_class = self.model_class
        model_data = MockupData(force=force, factory=self.factory)

        fields = model_class._meta.fields
        for field in fields:
            field_type = type(field)
            if isinstance(field, ForeignKey):
                related_model = field.rel.to
                model_data.set(field.name, model=related_model)
            else:
                try:
                    generator_class = FIELDCLASS_TO_GENERATOR[field_type]
                    if issubclass(generator_class, generators.FieldGenerator):
                        generator = generator_class(field)
                    elif issubclass(generator_class, generators.Generator):
                        generator = generator_class()
                    value = generator.get_value()
                    if value is not None:
                        model_data.set(field.name, value)
                except KeyError, e:
                    if e.args[0] != models.fields.AutoField:
                        msg = "Could not mockup data for %s.%s"
                        msg %= (model_class.__name__, field.name)
                        raise Exception(msg)

        return model_data.create_model(model_class)