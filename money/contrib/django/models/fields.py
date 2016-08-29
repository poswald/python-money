from decimal import Decimal

from django.db import models
from django.utils.translation import ugettext_lazy

from money.contrib.django import forms
from money.money import Money

__all__ = ('MoneyField', 'currency_field_name', 'NotSupportedLookup')


def currency_field_name(name):
    return "%s_currency" % name


def currency_field_db_column(db_column):
    return None if db_column is None else "%s_currency" % db_column


SUPPORTED_LOOKUPS = ('exact', 'lt', 'gt', 'lte', 'gte', 'isnull')


class NotSupportedLookup(TypeError):
    def __init__(self, lookup):
        super(NotSupportedLookup, self).__init__()

        self.lookup = lookup

    def __str__(self):
        return "Lookup '%s' is not supported for MoneyField" % self.lookup


class MoneyFieldProxy(object):
    """
    An equivalent to Django's default attribute descriptor class SubfieldBase
    (normally enabled via `__metaclass__ = models.SubfieldBase` on the custom
    Field class).

    Instead of calling to_python() on our MoneyField class as SubfieldBase
    does, it stores the two different parts separately, and updates them
    whenever something is assigned. If the attribute is read, it builds the
    instance "on-demand" with the current data.

    See: http://blog.elsdoerfer.name/2008/01/08/fuzzydates-or-one-django-model-field-multiple-database-columns/
    """

    def __init__(self, field):
        self.field = field
        self.amount_field_name = field.name
        self.currency_field_name = currency_field_name(field.name)

    def _get_values(self, obj):
        return (obj.__dict__.get(self.field.amount_field_name, None),
                obj.__dict__.get(self.field.currency_field_name, None))

    def _set_values(self, obj, amount, currency):
        obj.__dict__[self.field.amount_field_name] = amount
        obj.__dict__[self.field.currency_field_name] = currency

    def __get__(self, obj, *args):
        amount, currency = self._get_values(obj)
        if amount is None:
            return None
        return Money(amount, currency)

    def __set__(self, obj, value):
        if value is None:  # Money(0) is False
            self._set_values(obj, None, '')
        elif isinstance(value, Money):
            self._set_values(obj, value.amount, value.currency.code)
        elif isinstance(value, Decimal):
            _, currency = self._get_values(obj)  # use what is currently set
            self._set_values(obj, value, currency)
        else:
            # It could be an int, or some other python native type
            try:
                amount = Decimal(str(value))
                _, currency = self._get_values(obj)  # use what is currently set
                self._set_values(obj, amount, currency)
            except TypeError:
                # Lastly, assume string type 'XXX 123' or something Money can
                # handle.
                try:
                    _, currency = self._get_values(obj)  # use what is currently set
                    m = Money.from_string(str(value))
                    self._set_values(obj, m.amount, m.currency)
                except TypeError:
                    msg = 'Cannot assign "%s"' % type(value)
                    raise TypeError(msg)


class InfiniteDecimalField(models.DecimalField):
    def db_type(self, connection):
        engine = connection.settings_dict['ENGINE']

        if 'postgresql' in engine:
            return 'numeric'

        return super(InfiniteDecimalField, self).db_type(connection=connection)

    def get_db_prep_save(self, value, *args, **kwargs):
        """
        Called when the Field value must be saved to the database. As the
        default implementation just calls get_db_prep_value(), you shouldn't
        need to implement this method unless your custom field needs a special
        conversion when being saved that is not the same as the conversion used
        for normal query parameters
        """

        # The superclass DecimalField get_db_prep_save will add decimals up to
        # the precision in the field definition. The point of this class is to
        # use the user-specified precision up to that limit instead. For that
        # reason we will call get_db_prep_value instead
        return self.get_db_prep_value(value, *args, **kwargs)


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


class MoneyField(InfiniteDecimalField):
    description = ugettext_lazy('An amount and type of currency')

    # Don't extend SubfieldBase since we need to have access to both fields when
    # to_python is called. We need our code there instead of subfieldBase
    # __metaclass__ = models.SubfieldBase

    def __init__(self, *args, **kwargs):
        # We add the currency field except when using frozen south orm. See introspection rules below.
        default_currency = kwargs.pop("default_currency", '')
        default = kwargs.get("default", None)
        self.add_currency_field = not kwargs.pop('no_currency_field', False)

        self.blankable = kwargs.get('blank', False)

        if isinstance(default, Money):
            self.default_currency = default.currency  # use the default's currency
            kwargs['default'] = default.amount
        else:
            self.default_currency = default_currency or ''  # use the kwarg passed in

        super(MoneyField, self).__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super(MoneyField, self).deconstruct()
        kwargs['no_currency_field'] = True
        return name, path, args, kwargs

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
        self.name = name
        self.amount_field_name = name
        self.currency_field_name = currency_field_name(name)

        if self.add_currency_field and not cls._meta.abstract:
            c_field = CurrencyField(
                max_length=3,
                default=self.default_currency,
                editable=False,
                null=False,  # empty char fields should be ''
                blank=self.blankable,
                db_column=currency_field_db_column(self.db_column),
            )
            # Use this field's creation counter for the currency field. This
            # field will get a +1 when we call super
            c_field.creation_counter = self.creation_counter
            cls.add_to_class(self.currency_field_name, c_field)

        # Set ourselves up normally
        super(MoneyField, self).contribute_to_class(cls, name)

        # As we are not using SubfieldBase, we need to set our proxy class here
        setattr(cls, self.name, MoneyFieldProxy(self))

        # Set our custom manager
        if not hasattr(cls, '_default_manager'):
            from .managers import MoneyManager
            cls.add_to_class('objects', MoneyManager())

    def get_db_prep_save(self, value, *args, **kwargs):
        """
        Called when the Field value must be saved to the database. As the
        default implementation just calls get_db_prep_value(), you shouldn't
        need to implement this method unless your custom field needs a special
        conversion when being saved that is not the same as the conversion used
        for normal query parameters
        """
        if isinstance(value, Money):
            value = value.amount

        return super(MoneyField, self).get_db_prep_save(value, *args, **kwargs)

    def get_prep_lookup(self, lookup_type, value):
        """
        Prepares the value for passing to the database when used in a lookup
        (a WHERE constraint in SQL).

        "Your method must be prepared to handle all of these lookup_type values
        and should raise either a ValueError if the value is of the wrong sort
        (a list when you were expecting an object, for example) or a TypeError
        if your field does not support that type of lookup."

        """
        if lookup_type not in SUPPORTED_LOOKUPS:
            raise NotSupportedLookup(lookup_type)

        if isinstance(value, Money):
            value = value.amount
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
        return value.amount

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
        patterns=[r"^money\.contrib\.django.\models\.fields\.MoneyField"],
        rules=[
            (
                (MoneyField,),
                [],
                {'no_currency_field': ('add_currency_field', {})}
            )
        ]
    )
    add_introspection_rules(
        patterns=[r"^money\.contrib\.django.\models\.fields\.CurrencyField"],
        rules=[]
    )
except ImportError:
    # South isn't installed
    pass
