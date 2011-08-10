from django.db import models
from django.utils.encoding import smart_unicode
from django.utils.translation import ugettext_lazy as _
from money.contrib.django import forms
from money import Money

__all__ = ('MoneyField', 'currency_field_name', 'NotSupportedLookup')

currency_field_name = lambda name: "%s_currency" % name


SUPPORTED_LOOKUPS = ('exact', 'lt', 'gt', 'lte', 'gte')

class NotSupportedLookup(Exception):
    def __init__(self, lookup):
        self.lookup = lookup
    def __str__(self):
        return "Lookup '%s' is not supported for MoneyField" % self.lookup

class MoneyFieldProxy(object):
    """
    An equivalent to Django's default attribute descriptor class (enabled via
    the SubfieldBase metaclass, see module doc for details). However, instead
    of callig to_python() on our MoneyField class, it stores the two
    different parts separately, and updates them whenever something is assigned.
    If the attribute is read, it builds the instance "on-demand" with the
    current data.
    (see: http://blog.elsdoerfer.name/2008/01/08/fuzzydates-or-one-django-model-field-multiple-database-columns/)
    """
    def __init__(self, field):
        self.field = field
        self.currency_field_name = currency_field_name(self.field.name)

    def _money_from_obj(self, obj):
        return Money(obj.__dict__[self.field.name], obj.__dict__[self.currency_field_name])

    def __get__(self, obj, type=None):
        if obj is None:
            raise AttributeError('Can only be accessed via an instance.')
        if not isinstance(obj.__dict__[self.field.name], Money):
            obj.__dict__[self.field.name] = self._money_from_obj(obj)
        return obj.__dict__[self.field.name]

    def __set__(self, obj, value):
        if isinstance(value, Money):
            obj.__dict__[self.field.name] = value.amount
            setattr(obj, self.currency_field_name, smart_unicode(value.currency))
        else:
            if value: value = str(value)
            obj.__dict__[self.field.name] = self.field.to_python(value)


class CurrencyField(models.CharField):
    """
    This field will be added to the model behind the scenes to hold the
    currency. It is used to enable outputting of currency data as a separate
    value when serializing to JSON.
    """

    def value_to_string(self, obj):
        """
        When serializing, we want to output as two values. This will be just
        the currency part as stored directly in the database.
        """
        value = self._get_val_from_obj(obj)
        return value


class MoneyField(models.DecimalField):
    description = _('An amount and type of currency')

    # Don't extend SubfieldBase since we need to have access to both fields when
    # to_python is called. We need our code there instead of subfieldBase
    #__metaclass__ = models.SubfieldBase

    def __init__(self, verbose_name=None, name=None,
                 max_digits=None, decimal_places=None,
                 default=None, default_currency=None, blank=True, **kwargs):
        # We add the currency field except when using frozen south orm. See introspection rules below.
        self.add_currency_field = not kwargs.pop('no_currency_field', False)
        if isinstance(default, Money):
            self.default_currency = default.currency
        self.default_currency = default_currency
        super(MoneyField, self).__init__(verbose_name, name, max_digits, decimal_places, default=default, blank=blank, **kwargs)

    def get_internal_type(self):
         return "DecimalField"

    # Implementing to_python should not be needed because we are directly
    # assigning the attributes to the model with the proxy class. Some parts
    # of the model forms code still tries to call to_python on the field
    # directly which will coerce the Money value into a string
    # representation. To handle this, we're checking for string and seeing if
    # we can split it into two pieces. Otherwise we assume we're dealing with
    # a string value
    def to_python(self, value):
        if isinstance(value, str):
            try:
                (currency, value) = value.split()
                if currency and value:
                    return Money(value, currency)
            except ValueError:
                pass
        return value

    def contribute_to_class(self, cls, name):
        if self.add_currency_field and not cls._meta.abstract:
            c_field = CurrencyField(max_length=3, default=self.default_currency, editable=False)
            c_field.creation_counter = self.creation_counter+1
            cls.add_to_class(currency_field_name(name), c_field)

        super(MoneyField, self).contribute_to_class(cls, name)
        setattr(cls, self.name, MoneyFieldProxy(self))

        if not hasattr(cls, '_default_manager'):
            from managers import MoneyManager
            cls.add_to_class('objects', MoneyManager())

    def get_db_prep_save(self, value, *args, **kwargs):
        if isinstance(value, Money):
            value = value.amount
        return super(MoneyField, self).get_db_prep_save(value, *args, **kwargs)

    def get_prep_lookup(self, lookup_type, value):
        if not lookup_type in SUPPORTED_LOOKUPS:
            raise NotSupportedLookup(lookup_type)
        value = self.get_db_prep_save(value)
        return super(MoneyField, self).get_prep_lookup(lookup_type, value)

    def get_default(self):
        if isinstance(self.default, Money):
            return self.default
        else:
            return super(MoneyField, self).get_default()

    def value_to_string(self, obj):
        """
        When serializing this field, we will output both value and currency.
        Here we only need to output the value. The contributed currency field
        will get called to output itself
        """
        value = self._get_val_from_obj(obj)
        return  value.amount

    def formfield(self, **kwargs):
        defaults = {'form_class': forms.MoneyField}
        defaults.update(kwargs)
        return super(MoneyField, self).formfield(**defaults)


# South introspection rules
# (see http://south.aeracode.org/docs/customfields.html#extending-introspection)
try:
    from south.modelsinspector import add_introspection_rules
    # South must know if a field was dynamically added to the class when it freezes it. We pass
    # this in as a parameter to the field when it is created. The 'add_currency_field' attribute
    # is normally True in a MoneyField. This means that 'no_currency_field' is True when frozen.
    #
    # See: http://south.aeracode.org/ticket/327
    # See: https://bitbucket.org/carljm/django-markitup/changeset/eb788c807dd8
    # See: http://south.aeracode.org/docs/customfields.html
    add_introspection_rules(
        patterns=["^money\.contrib\.django.\models\.fields\.MoneyField"],
        rules=[
            (   (MoneyField,),
                [],
                {'no_currency_field': ('add_currency_field', {})}
            )
        ]
    )
    add_introspection_rules(
        patterns=["^money\.contrib\.django.\models\.fields\.CurrencyField"],
        rules=[]
    )
except ImportError:
    # South isn't installed
    pass